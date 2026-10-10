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


@pytest.mark.parametrize("action", ["playpause", "stop", "seek", "audio", "subtitle", "chapter_next"])
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
