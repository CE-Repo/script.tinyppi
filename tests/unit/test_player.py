# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Player state and the dashboard's transport commands (web/player.py)."""

import math

import pytest

import xbmc
from web import player


class Kodi:
    """Answers JSON-RPC like a Kodi playing a video; records every call."""

    def __init__(self, playing=True):
        self.playing = playing
        self.calls = []
        self.answers = {}

    def __call__(self, request):
        method, params = request["method"], request.get("params", {})
        self.calls.append((method, params))
        if method in self.answers:
            return self.answers[method]
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1, "type": "video"}] if self.playing else []}
        return {"result": "OK"}

    def sent(self, method):
        return [params for name, params in self.calls if name == method]


@pytest.fixture
def kodi():
    fake = Kodi()
    xbmc.RPC = fake
    return fake


# --- Commands ----------------------------------------------------------------

@pytest.mark.parametrize("action", ["", "Player.Stop", "System.Shutdown", "seek ", "SEEK"])
def test_only_listed_actions_run(kodi, action):
    assert player.apply_command(action, 1) is False
    assert kodi.calls == []


@pytest.mark.parametrize(("value", "seconds"), [
    (30, 30), (-30, -30), ("10", 10), (2.9, 2), (3600, 3600), (-3600, -3600),
])
def test_seek_by_seconds(kodi, value, seconds):
    assert player.apply_command("seek", value)
    assert kodi.sent("Player.Seek") == [{"playerid": 1, "value": {"seconds": seconds}}]


@pytest.mark.parametrize("value", [
    None, "", "x", [], {}, True, False, float("nan"), float("inf"), "-inf", 3601, -3601, "1e9",
])
def test_bad_seek_values_send_nothing(kodi, value):
    assert player.apply_command("seek", value) is False
    assert kodi.sent("Player.Seek") == []


@pytest.mark.parametrize(("value", "ok"), [
    (0, True), (50.5, True), (100, True), (-1, False), (101, False), ("half", False), (None, False),
])
def test_seek_by_percentage(kodi, value, ok):
    assert player.apply_command("seek_percent", value) is ok
    expected = [{"playerid": 1, "value": {"percentage": float(value)}}] if ok else []
    assert kodi.sent("Player.Seek") == expected


def test_seek_on_live_tv_is_relative_to_the_broadcast(kodi):
    xbmc.CONDITIONS["PVR.IsPlayingTV"] = True
    xbmc.INFO["PVR.EpgEventDuration(hh:mm:ss)"] = "01:00:00"
    xbmc.INFO["PVR.EpgEventElapsedTime(hh:mm:ss)"] = "00:15:00"
    assert player.apply_command("seek_percent", 50)
    assert kodi.sent("Player.Seek") == [{"playerid": 1, "value": {"seconds": 900}}]


def test_seek_on_live_tv_without_a_position(kodi):
    xbmc.CONDITIONS["PVR.IsPlayingTV"] = True
    xbmc.INFO["PVR.EpgEventDuration(hh:mm:ss)"] = "01:00:00"
    xbmc.INFO["PVR.EpgEventElapsedTime(hh:mm:ss)"] = "--:--"
    assert player.apply_command("seek_percent", 50) is False
    assert kodi.sent("Player.Seek") == []


@pytest.mark.parametrize(("value", "sent"), [
    (0, 0), (2, 2), ("3", 3), (64, 64), (-1, None), (65, None), (True, None), ("en", None),
])
def test_audio_track(kodi, value, sent):
    assert player.apply_command("audio", value) is (sent is not None)
    expected = [{"playerid": 1, "stream": sent}] if sent is not None else []
    assert kodi.sent("Player.SetAudioStream") == expected


def test_subtitles_on_and_off(kodi):
    assert player.apply_command("subtitle", -1)
    assert player.apply_command("subtitle", 2)
    assert player.apply_command("subtitle", -2) is False
    assert kodi.sent("Player.SetSubtitle") == [
        {"playerid": 1, "subtitle": "off"},
        {"playerid": 1, "subtitle": 2, "enable": True},
    ]


@pytest.mark.parametrize(("action", "input_action"), [
    ("volume_up", "volumeup"), ("volume_down", "volumedown"), ("mute", "mute"),
])
def test_volume_goes_through_input_actions(kodi, action, input_action):
    kodi.playing = False                    # works without a video too
    assert player.apply_command(action)
    assert kodi.sent("Input.ExecuteAction") == [{"action": input_action}]


def test_absolute_volume_for_older_clients(kodi):
    assert player.apply_command("volume", "42.7")
    assert player.apply_command("volume", 101) is False
    assert kodi.sent("Application.SetVolume") == [{"volume": 42}]


def test_chapters_need_at_least_two(kodi):
    xbmc.INFO["Player.ChapterCount"] = "1"
    assert player.apply_command("chapter_next") is False
    xbmc.INFO["Player.ChapterCount"] = "x"
    assert player.apply_command("chapter_next") is False
    xbmc.INFO["Player.ChapterCount"] = "12"
    assert player.apply_command("chapter_next")
    assert player.apply_command("chapter_previous")
    assert kodi.sent("Input.ExecuteAction") == [
        {"action": "chapterorbigstepforward"}, {"action": "chapterorbigstepback"}]


def _chapters(kodi, *entries, count="3"):
    """Make Kodi list *entries* as the playing file's chapters."""
    xbmc.INFO["Player.ChapterCount"] = count
    kodi.answers["Player.GetChapters"] = {"result": {"chapters": list(entries)}}


def test_a_chapter_jump_seeks_to_the_time_the_box_lists(kodi):
    xbmc.INFO["Player.Duration"] = "02:00:00"
    _chapters(kodi, {"index": 1, "time": 0}, {"index": 2, "time": 3723},
              {"index": 3, "time": 5400, "name": "End"})
    assert player.apply_command("chapter_goto", 2)
    assert player.apply_command("chapter_goto", "3")
    assert kodi.sent("Player.Seek") == [
        {"playerid": 1, "value": {"time": {"hours": 1, "minutes": 2, "seconds": 3,
                                           "milliseconds": 0}}},
        {"playerid": 1, "value": {"time": {"hours": 1, "minutes": 30, "seconds": 0,
                                           "milliseconds": 0}}},
    ]
    assert kodi.sent("Player.GetChapters") == [{"playerid": 1}] * 2


@pytest.mark.parametrize("value", [None, "x", True, 0, 1.5, 4, 201, float("nan"), "-1"])
def test_a_chapter_jump_needs_a_chapter_the_box_lists(kodi, value):
    xbmc.INFO["Player.Duration"] = "02:00:00"
    _chapters(kodi, {"index": 1, "time": 0}, {"index": 2, "time": 60}, {"index": 3, "time": 120})
    assert player.apply_command("chapter_goto", value) is False
    assert kodi.sent("Player.Seek") == []


def test_a_chapter_jump_reports_kodis_answer(kodi):
    xbmc.INFO["Player.Duration"] = "10:00"
    _chapters(kodi, {"index": 1, "time": 0}, {"index": 2, "time": 60})
    kodi.answers["Player.Seek"] = {"error": {"code": -32100}}
    assert player.apply_command("chapter_goto", 2) is False


# --- Chapters ------------------------------------------------------------------

def test_the_chapter_list_places_each_chapter_on_the_length(kodi):
    _chapters(kodi, {"index": 1, "time": 0, "name": "Opening"},
              {"index": 2, "time": 1800, "name": "  [B]Arrival[/B] "},
              {"index": 3, "time": 7200})
    assert player.chapter_list("02:00:00") == [
        {"index": 1, "start": 0, "at": 0.0, "time": "00:00:00", "name": "Opening"},
        {"index": 2, "start": 1800, "at": 25.0, "time": "00:30:00", "name": "Arrival"},
        {"index": 3, "start": 7200, "at": 100.0, "time": "02:00:00", "name": ""},
    ]


def test_a_chapter_under_the_hour_is_written_like_the_position(kodi):
    _chapters(kodi, {"index": 1, "time": 0}, {"index": 2, "time": 125})
    assert [chapter["time"] for chapter in player.chapter_list("45:00")] == ["00:00", "02:05"]
    assert player.chapter_list("45:00")[1]["at"] == 4.63


def test_long_names_and_long_lists_are_cut_off(kodi):
    _chapters(kodi, *({"index": n, "time": n, "name": "x" * 120} for n in range(1, 300)))
    chapters = player.chapter_list("01:00:00")
    assert len(chapters) == 200 and len(chapters[0]["name"]) == 80


@pytest.mark.parametrize("entry", [
    "junk", {"time": 10}, {"index": 2}, {"index": True, "time": 10}, {"index": 2, "time": False},
    {"index": 2, "time": 10.5}, {"index": 2, "time": -1}, {"index": 2, "time": 3601},
])
def test_malformed_chapters_are_left_out(kodi, entry):
    _chapters(kodi, {"index": 1, "time": 0}, {"index": 3, "time": 60}, entry)
    assert [chapter["index"] for chapter in player.chapter_list("01:00:00")] == [1, 3]


@pytest.mark.parametrize("name", [
    "Chapter 06", "chapter 1", "Chapters 3", "Ch. 3", "Ch3", "Chap 4", "Chapter #7", "Chapter IV",
    "Kapitel 12", "Kap. 5", "Chapitre 4", "Capítulo 2", "Capitolo 5", "Hoofdstuk 7",
    "Rozdział 8", "Kapitola 9", "Глава 9", "Κεφάλαιο 3", "6. fejezet", "6. Bölüm", "第6章",
    "第 12 章", "章节 3", "06", "6", "#6", "00:57:32", "00:57:32.000", "57:32",
    "Chapter 1 - 00:05:00", "Chapter 2: Chapter 2", "", None,
])
def test_a_name_a_tool_made_up_is_no_name(name):
    assert player._chapter_name(name) == ""


@pytest.mark.parametrize(("name", "kept"), [
    ("Chapter 6: The Hunt", "The Hunt"), ("Chapter 6 - The Hunt", "The Hunt"),
    ("Chapter 6 The Hunt", "The Hunt"), ("Chapter 6:The Hunt", "The Hunt"),
    ("Chapter IV: The End", "The End"), ("06. The Hunt", "The Hunt"), ("06 - The Hunt", "The Hunt"),
    ("1. Advent", "Advent"), ("6. fejezet: Die Jagd", "Die Jagd"), ("第6章：狩猎", "狩猎"),
])
def test_a_real_name_behind_a_number_keeps_only_the_name(name, kept):
    assert player._chapter_name(name) == kept


@pytest.mark.parametrize("name", [
    "Die Ankunft", "Opening Credits", "Chill", "Chic", "Civic", "3 Days Later", "1917",
    "2001: A Space Odyssey", "The Chapter 6 Story", "Act 1", "Part 2", "Chapter",
])
def test_a_real_name_is_kept_as_it_is(name):
    assert player._chapter_name(name) == name


def test_made_up_names_leave_the_chapters_unnamed(kodi):
    _chapters(kodi, {"index": 1, "time": 0, "name": "Chapter 01"},
              {"index": 2, "time": 60, "name": "Chapter 02: Arrival"})
    assert [chapter["name"] for chapter in player.chapter_list("01:00:00")] == ["", "Arrival"]


def test_one_chapter_is_no_chapters(kodi):
    _chapters(kodi, {"index": 1, "time": 0}, "junk")
    assert player.chapter_list("01:00:00") == []


@pytest.mark.parametrize("answer", [{}, {"result": "junk"}, {"result": {"chapters": "junk"}},
                                    {"error": {"code": -32601}}])
def test_a_box_that_cannot_list_chapters_lists_none(kodi, answer):
    xbmc.INFO["Player.ChapterCount"] = "3"
    kodi.answers["Player.GetChapters"] = answer
    assert player.chapter_list("01:00:00") == []


def test_chapters_are_only_asked_for_when_there_are_some(kodi):
    xbmc.INFO["Player.ChapterCount"] = "1"
    assert player.chapter_list("01:00:00") == []
    xbmc.INFO["Player.ChapterCount"] = "3"
    kodi.playing = False
    assert player.chapter_list("01:00:00") == []
    kodi.playing = True
    assert player.chapter_list("") == [] and player.chapter_list("00:00") == []
    assert kodi.sent("Player.GetChapters") == []


@pytest.mark.parametrize(("position", "current"), [
    ("", 0), ("00:00:00", 1), ("00:29:59", 1), ("00:30:00", 2), ("01:59:59", 2), ("02:00:00", 3),
])
def test_the_current_chapter_follows_the_position(kodi, position, current):
    _chapters(kodi, {"index": 1, "time": 0}, {"index": 2, "time": 1800},
              {"index": 3, "time": 7200})
    chapters = player.chapter_list("02:00:00")
    assert player.current_chapter(chapters, position) == current


def test_before_the_first_chapter_there_is_none():
    first = {"index": 1, "start": 60, "at": 1.0, "time": "01:00", "name": ""}
    assert player.current_chapter([first], "00:30") == 0
    assert player.current_chapter([], "00:30") == 0


@pytest.mark.parametrize("action", ["playpause", "stop", "seek", "audio", "subtitle", "chapter_next",
                                    "chapter_goto"])
def test_player_commands_need_a_video(kodi, action):
    kodi.playing = False
    xbmc.INFO["Player.ChapterCount"] = "12"
    assert player.apply_command(action, 1) is False
    assert [method for method, _ in kodi.calls] == ["Player.GetActivePlayers"]


def test_play_pause_and_stop_report_kodis_answer(kodi):
    assert player.apply_command("playpause")
    kodi.answers["Player.Stop"] = {"error": {"code": -32100}}
    assert player.apply_command("stop") is False


# --- State -------------------------------------------------------------------

def test_a_broken_answer_is_an_empty_one(monkeypatch):
    monkeypatch.setattr(xbmc, "executeJSONRPC", lambda _request: "not json")
    assert player.rpc("JSONRPC.Ping") == {}
    monkeypatch.setattr(xbmc, "executeJSONRPC", lambda _request: "[1, 2]")
    assert player.rpc("JSONRPC.Ping") == {}
    assert any("JSON-RPC JSONRPC.Ping failed" in line for _level, line in xbmc.LOG)


def test_only_a_video_player_counts(kodi):
    kodi.answers["Player.GetActivePlayers"] = {"result": [{"playerid": 0, "type": "audio"}]}
    assert player.video_player_id() is None
    kodi.answers["Player.GetActivePlayers"] = {"result": "junk"}
    assert player.video_player_id() is None


@pytest.mark.parametrize(("stream", "label"), [
    ({"name": "English", "language": "eng"}, "ENG · English"),
    ({"name": "eng - Commentary", "language": "eng"}, "ENG - Commentary"),
    ({"name": "", "language": "ger"}, "GER"),
    ({"name": "Director", "language": ""}, "Director"),
    ({"name": "Forced", "language": "Deutsch"}, "Deutsch · Forced"),
    ({}, "#3"),
])
def test_track_labels(stream, label):
    assert player._stream_label(stream, "#3") == label


def test_player_controls(kodi):
    kodi.answers["Application.GetProperties"] = {"result": {"volume": 70, "muted": True}}
    xbmc.INFO["Player.ChapterCount"] = "8"
    kodi.answers["Player.GetProperties"] = {"result": {
        "audiostreams": [{"index": 0, "name": "English", "language": "eng"},
                         {"index": 1, "name": "", "language": "ger"}],
        "currentaudiostream": {"index": 1},
        "subtitles": [{"index": 0, "name": "", "language": ""}],
        "currentsubtitle": {"index": 0}, "subtitleenabled": False,
    }}
    state = player.player_controls()
    assert state["volume"] == 70 and state["muted"] is True and state["chapters"] == 8
    assert state["audio"] == [{"index": 0, "label": "ENG · English"}, {"index": 1, "label": "GER"}]
    assert state["subtitle"] == [{"index": 0, "label": "#1"}]
    assert (state["audio_current"], state["subtitle_current"], state["subtitle_on"]) == (1, 0, False)


def test_player_controls_without_a_video(kodi):
    kodi.playing = False
    state = player.player_controls()
    assert state["audio"] == [] and state["chapters"] == 0


def test_track_tokens(kodi):
    kodi.answers["Player.GetProperties"] = {"result": {
        "currentaudiostream": {"index": 1, "name": "English", "language": "eng"},
        "currentsubtitle": {"index": 0}, "subtitleenabled": False,
    }}
    assert player.current_track_state() == {
        "audio": "#2 · ENG · English", "audio_id": "#2", "subtitle": "__off__"}
    kodi.playing = False
    assert player.current_track_state() == {"audio": "", "audio_id": "", "subtitle": ""}


@pytest.mark.parametrize(("clock", "total"), [
    ("01:02:03", 3723), ("02:03", 123), (" 00:00 ", 0), ("5", None), ("1:2:3:4", None),
    ("ab:cd", None), ("", None),
])
def test_clock_to_seconds(clock, total):
    assert player.seconds(clock) == total


def test_broadcast_times_from_the_epg():
    assert player.broadcast_times() == {}            # not live TV
    xbmc.CONDITIONS["PVR.IsPlayingRadio"] = True
    xbmc.INFO["PVR.EpgEventDuration(hh:mm:ss)"] = "00:00:00"
    assert player.broadcast_times() == {}            # no EPG data
    xbmc.INFO["PVR.EpgEventDuration(hh:mm:ss)"] = "02:00:00"
    xbmc.INFO["PVR.EpgEventElapsedTime(hh:mm:ss)"] = "02:30:00"   # running late
    times = player.broadcast_times()
    assert times["PlayerProgress"] == "100.0" and times["BroadcastTimes"] == "1"
    assert not math.isnan(float(times["PlayerProgress"]))


@pytest.mark.parametrize("answer", [{"result": ["junk"]}, {"result": "junk"}])
def test_player_controls_ignore_malformed_track_lists(kodi, answer):
    kodi.answers["Application.GetProperties"] = {"result": {"volume": 30, "muted": False}}
    xbmc.INFO["Player.ChapterCount"] = "4"
    kodi.answers["Player.GetProperties"] = answer
    state = player.player_controls()
    assert (state["volume"], state["chapters"]) == (30, 4)
    assert state["audio"] == [] and state["subtitle"] == []
    assert (state["audio_current"], state["subtitle_current"]) == (-1, -1)


def test_player_controls_keep_defaults_for_malformed_current_tracks(kodi):
    kodi.answers["Application.GetProperties"] = {"result": "junk"}
    kodi.answers["Player.GetProperties"] = {"result": {
        "audiostreams": [{"name": "Main"}],
        "currentaudiostream": "1", "currentsubtitle": ["0"], "subtitleenabled": True,
    }}
    state = player.player_controls()
    assert state["volume"] is None and state["muted"] is False
    assert state["audio"] == [{"index": 0, "label": "Main"}]    # the position stands in
    assert state["audio_current"] == state["subtitle_current"] == -1
    assert state["subtitle_on"] is True


def test_track_tokens_from_a_malformed_answer_are_empty(kodi):
    kodi.answers["Player.GetProperties"] = {"result": ["junk"]}
    assert player.current_track_state() == {"audio": "", "audio_id": "", "subtitle": ""}


@pytest.mark.parametrize(("audio", "subtitle", "expected"), [
    # A stream without an index has no token, as does one that is no dict.
    ({"name": "English"}, {"index": 2, "language": "ger"},
     {"audio": "", "audio_id": "", "subtitle": "#3 · GER"}),
    ("eng", {}, {"audio": "", "audio_id": "", "subtitle": ""}),
    # Without a label the number alone is the token.
    ({"index": 0}, {"index": 1}, {"audio": "#1", "audio_id": "#1", "subtitle": "#2"}),
])
def test_track_tokens_with_subtitles_on(kodi, audio, subtitle, expected):
    kodi.answers["Player.GetProperties"] = {"result": {
        "currentaudiostream": audio, "currentsubtitle": subtitle, "subtitleenabled": True,
    }}
    assert player.current_track_state() == expected
