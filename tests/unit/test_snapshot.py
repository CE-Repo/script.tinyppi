# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The snapshot the dashboard receives (web/snapshot.py, its rows in
web/rows.py) and the thread that builds it (web/producer.py)."""

import threading
import time

import pytest

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from info import dvinfo
from web import producer as producer_module
from web import rows as web_rows
from web import snapshot
from web.producer import Producer
from web.snapshot import SnapshotBuilder

PLAYING = {
    "VideoPlayer.Title": "Film", "Player.Filename": "Film.2160p.mkv",
    "Player.Process(videowidth)": "3,840", "Player.Process(videoheight)": "2,160",
    "Player.Time": "00:10:00", "Player.Duration": "02:00:00",
    "Player.FinishTime": "22:15", "Player.Progress": "8.3",
    "System.CPUTemperature": "55 °C", "VideoPlayer.VideoCodec": "hevc",
    "VideoPlayer.Year": "2021", "VideoPlayer.Genre": "Drama",
    "VideoPlayer.Tagline": "One night.", "VideoPlayer.Plot": "Somebody does something.",
    "VideoPlayer.Director": "Somebody / Somebody Else", "VideoPlayer.Studio": "A Studio / Another",
    "VideoPlayer.Cast": "\n".join(f"Actor {n}" for n in range(1, 25)),
}


@pytest.fixture(autouse=True)
def private_home(monkeypatch, tmp_path):
    """The IMAX title list is looked up in the profile: keep it per test."""
    monkeypatch.setattr(xbmcvfs, "HOME", str(tmp_path))


def play(**info):
    xbmc.CONDITIONS["Player.HasVideo"] = True
    xbmc.INFO.update(PLAYING)
    xbmc.INFO.update(info)


# --- Snapshots ----------------------------------------------------------------

def test_nothing_playing():
    builder = SnapshotBuilder()
    first, second = builder.build(), builder.build()
    assert first["playing"] is False and first["groups"] == [] and first["last"] == {}
    assert second["seq"] == first["seq"] + 1


def test_a_playing_title():
    play()
    shot = SnapshotBuilder().build(control=False)
    assert (shot["playing"], shot["title"], shot["time"], shot["duration"]) == (
        True, "Film", "00:10:00", "02:00:00")
    assert shot["finish"] == "22:15"
    assert shot["metrics"]["frame"] == {"w": 3840, "h": 2160}
    assert shot["metrics"]["cpu_temp"] == 55.0 and shot["metrics"]["progress"] == 8.3
    assert shot["media"]["year"] == "2021" and shot["media"]["genre"] == "Drama"
    assert shot["media"]["tagline"] == "One night."
    assert shot["media"]["plot"] == "Somebody does something."
    # Who made it, as names; every director and the cast's first twenty,
    # said to have more.  The genre is only the card above's.
    assert "genres" not in shot["media"]
    assert shot["media"]["directors"] == ["Somebody", "Somebody Else"]
    assert "directors_more" not in shot["media"]
    assert shot["media"]["studios"] == ["A Studio"]
    assert "studios_more" not in shot["media"]
    assert shot["media"]["cast"] == [f"Actor {n}" for n in range(1, 21)]
    assert shot["media"]["cast_more"] is True
    assert shot["controls"] == {}
    ids = [group["id"] for group in shot["groups"]]
    assert ids[0] == "video" and len(ids) == len(set(ids))
    for group in shot["groups"]:
        for row in group["rows"]:
            assert row["value"]                       # empty readings read N/A


def test_the_genre_is_cut_to_its_first_two():
    play(**{"VideoPlayer.Genre": "[B]Action[/B] / Adventure / Drama"})
    assert SnapshotBuilder().build()["media"]["genre"] == "Action / Adventure"
    play(**{"VideoPlayer.Genre": ""})
    assert SnapshotBuilder().build()["media"]["genre"] == ""


def test_the_filename_respects_its_setting():
    play()
    builder = SnapshotBuilder()
    assert builder.build(allow_filename=True)["filename"] == "Film.2160p.mkv"
    assert builder.build(allow_filename=False)["filename"] == ""


def test_without_detail_only_the_session_moves():
    play()
    builder = SnapshotBuilder()
    assert builder.build(detail=False) is None
    assert builder.session.history()["t"]            # sampled


def test_the_last_title_is_kept_after_it_ends():
    play()
    builder = SnapshotBuilder()
    builder.build()
    builder.build()
    xbmc.CONDITIONS["Player.HasVideo"] = False
    builder.build()                                  # marks the end
    idle = builder.build()
    assert idle["playing"] is False and idle["last"]["title"] == "Film"


def test_metadata_needs_dolby_vision_and_the_setting():
    play()
    xbmcgui.Window(10000).setProperty("TinyPPI.HdrType", "hdr10")
    assert SnapshotBuilder().build(metadata=True)["metadata"] == []


def test_controls_when_allowed(monkeypatch):
    play()
    asked = []
    monkeypatch.setattr(snapshot, "player_controls", lambda: asked.append(1) or {"volume": 50})
    builder = SnapshotBuilder()
    assert builder.build(control=True)["controls"] == {"volume": 50}
    builder.build(control=True)                      # within the static interval
    assert asked == [1]


CHAPTERS = [
    {"index": 1, "start": 0, "at": 0.0, "time": "00:00:00", "name": "Opening"},
    {"index": 2, "start": 300, "at": 4.167, "time": "00:05:00", "name": ""},
    {"index": 3, "start": 3600, "at": 50.0, "time": "01:00:00", "name": "Finale"},
]


@pytest.fixture
def chapters(monkeypatch):
    """Kodi's chapters for whatever plays; records the lengths asked for."""
    asked = []
    found = list(CHAPTERS)
    monkeypatch.setattr(snapshot, "chapter_list", lambda duration: asked.append(duration) or list(found))
    return asked, found


def test_chapters_travel_without_control(chapters):
    play()
    shot = SnapshotBuilder().build(control=False)
    assert shot["chapters"] == CHAPTERS and shot["chapter"] == 2
    assert chapters[0] == ["02:00:00"]


def test_chapters_are_read_once_per_title(chapters, monkeypatch):
    asked, _found = chapters
    play()
    builder = SnapshotBuilder()
    builder.build()
    monkeypatch.setattr(builder, "STATIC_INTERVAL", 0.0)
    builder.build()                                  # same title, chapters known
    assert asked == ["02:00:00"]
    play(**{"Player.Filename": "Next.mkv", "Player.Duration": "45:00"})
    assert builder.build()["chapter"] == 2
    assert asked == ["02:00:00", "45:00"]


def test_chapters_are_asked_for_again_while_there_are_none(chapters, monkeypatch):
    asked, found = chapters
    found.clear()
    play()
    builder = SnapshotBuilder()
    assert builder.build()["chapters"] == []
    builder.build()                                  # within the static interval
    assert len(asked) == 1
    monkeypatch.setattr(builder, "STATIC_INTERVAL", 0.0)
    found.extend(CHAPTERS)
    assert builder.build()["chapters"] == CHAPTERS
    assert len(asked) == 2


@pytest.fixture
def rated(monkeypatch):
    """The ratings Kodi gives whatever plays; None while it cannot say yet."""
    asked = []
    given = {"found": {"ratings": [{"source": "imdb", "rating": 8.5, "votes": 10}],
                       "mpaa": "FSK 12", "age": "fsk12", "age_level": "12",
                       "userrating": 9, "top250": 27, "ids": {"imdb": "tt0111161"}}}
    monkeypatch.setattr(snapshot, "playing_ratings", lambda: asked.append(1) or given["found"])
    return asked, given


def test_the_ratings_travel_in_the_media_block(rated):
    play()
    media = SnapshotBuilder().build()["media"]
    assert media["ratings"] == [{"source": "imdb", "rating": 8.5, "votes": 10}]
    assert (media["mpaa"], media["age"], media["age_level"]) == ("FSK 12", "fsk12", "12")
    assert (media["userrating"], media["top250"]) == (9, 27)


def test_mdblist_ratings_lie_over_the_librarys_and_the_ids_stay_behind(rated, monkeypatch):
    asked = []

    def over(ratings, key):
        asked.append(ratings["ids"])
        merged = ratings.copy()
        merged["ratings"] = [{"source": "letterboxd", "rating": 8.0, "votes": 3}]
        return merged

    monkeypatch.setattr(snapshot, "with_mdblist", over)
    play()
    media = SnapshotBuilder().build()["media"]
    assert media["ratings"] == [{"source": "letterboxd", "rating": 8.0, "votes": 3}]
    assert "ids" not in media
    assert asked == [{"imdb": "tt0111161"}]


def test_the_ratings_are_read_once_per_title_and_not_for_the_session_pass(rated, monkeypatch):
    asked, _given = rated
    play()
    builder = SnapshotBuilder()
    assert builder.build(detail=False) is None       # nobody watching: no JSON-RPC
    assert asked == []
    builder.build()
    monkeypatch.setattr(builder, "STATIC_INTERVAL", 0.0)
    builder.build()                                  # same title, Kodi could say
    assert len(asked) == 1
    play(**{"Player.Filename": "Next.mkv"})
    builder.build()
    assert len(asked) == 2


def test_the_mdblist_key_is_read_once_a_static_interval(rated, monkeypatch):
    read, given = [], []
    monkeypatch.setattr(snapshot, "api_key", lambda: read.append(1) or "KEY")

    def over(ratings, key):
        given.append(key)
        return ratings

    monkeypatch.setattr(snapshot, "with_mdblist", over)
    play()
    builder = SnapshotBuilder()
    builder.build()
    builder.build()
    assert len(read) == 1 and given == ["KEY", "KEY"]
    # A key given mid-film is read again on the next interval, the same
    # title still playing.
    monkeypatch.setattr(builder, "STATIC_INTERVAL", 0.0)
    builder.build()
    assert len(read) == 2


def test_the_ratings_are_asked_for_again_while_kodi_cannot_say(rated, monkeypatch):
    asked, given = rated
    found = given["found"]
    given["found"] = None
    play()
    builder = SnapshotBuilder()
    assert builder.build()["media"]["ratings"] == []
    builder.build()                                  # within the static interval
    assert len(asked) == 1
    monkeypatch.setattr(builder, "STATIC_INTERVAL", 0.0)
    given["found"] = found
    assert builder.build()["media"]["mpaa"] == "FSK 12"
    builder.build()                                  # known now: not asked again
    assert len(asked) == 2


def test_the_ratings_are_dropped_when_playback_ends(rated):
    asked, _given = rated
    play()
    builder = SnapshotBuilder()
    builder.build()
    xbmc.CONDITIONS["Player.HasVideo"] = False
    builder.build()
    play()
    builder.build()                                  # the same film again
    assert len(asked) == 2


def test_chapters_are_dropped_when_playback_ends(chapters):
    asked, _found = chapters
    play()
    builder = SnapshotBuilder()
    builder.build()
    xbmc.CONDITIONS["Player.HasVideo"] = False
    assert "chapters" not in builder.build()
    play()
    builder.build()                                  # the same film again
    assert len(asked) == 2


@pytest.fixture
def dolby_vision(monkeypatch):
    """Serve a Dolby Vision frame from dvinfo and fake the metadata view's rows."""
    fields = {"hdr_format": "dolbyvision", "output_mode": "Dolby Vision Profile 8.1",
              "dv_profile": "8.1", "dv_rpu_present": "true", "dv_bl_present": "true",
              "dv_el_present": "false", "l1_nits": "0.01 | 1000 | 92",
              "l5_offsets": "0 | 0 | 276 | 276"}
    built = []

    def static_rows(parsed, origin, carried):
        built.append(carried)
        return [("row", "[B]RPU[/B]", xbmc.getLocalizedString(107))]

    monkeypatch.setattr(snapshot.dvmetadata, "build_scene_rows",
                        lambda: ([("table", "L2", ["1", "2"])], {}, {}, "carried"))
    monkeypatch.setattr(snapshot.dvmetadata, "build_static_rows", static_rows)
    monkeypatch.setattr(dvinfo, "_snapshot", lambda: (fields, True))
    return built


def test_a_dolby_vision_title(dolby_vision):
    play()
    shot = SnapshotBuilder().build()
    assert shot["hdr_type"] == "dolbyvision"
    assert shot["metrics"]["l1"] == {"min": 0.01, "max": 1000.0, "avg": 92.0}
    assert shot["metrics"]["bars"] == [0.0, 0.0, 276.0, 276.0]
    ids = [group["id"] for group in shot["groups"]]
    assert "hdr" not in ids and ids.count("metadata") == 1
    # The static and the RPU readings form one Metadata card.
    metadata = next(group for group in shot["groups"] if group["id"] == "metadata")
    labels = [row["id"] for row in metadata["rows"]]
    assert labels[:2] == ["metadata.32256", "metadata.32257"] and "metadata.32271" in labels
    dv = next(group for group in shot["groups"] if group["id"] == "dv")
    flags = next(row for row in dv["rows"] if row["id"] == "dv.32262")
    assert flags["value"] == "✔ | ✔"


def test_dolby_vision_metadata_rows(dolby_vision):
    play()
    builder = SnapshotBuilder()
    rows = builder.build(metadata=True)["metadata"]
    assert rows[0] == {"kind": "table", "name": "L2", "cells": ["1", "2"]}
    assert rows[-1] == {"kind": "row", "name": "RPU", "value": "✔"}
    assert len(rows) == 3                            # a blank row between the halves
    builder.build(metadata=True)
    assert dolby_vision == ["carried"]               # static rows within their interval
    assert builder.build(metadata=False)["metadata"] == []
    builder.build(metadata=True)
    assert dolby_vision == ["carried", "carried"]    # rebuilt after being switched off


def test_static_metadata_rows_are_rebuilt_on_their_interval(dolby_vision):
    play()
    builder = SnapshotBuilder()
    builder.STATIC_INTERVAL = 0.0
    builder.build(metadata=True)
    builder.build(metadata=True)
    assert len(dolby_vision) == 2


def test_a_card_without_any_value_is_left_out(dolby_vision, monkeypatch):
    monkeypatch.setattr(dvinfo, "_snapshot", lambda: ({"hdr_format": "dolbyvision"}, True))
    play()
    ids = [group["id"] for group in SnapshotBuilder().build()["groups"]]
    assert "dv" not in ids and "metadata" in ids


def test_an_unknown_frame_size_is_left_out():
    play(**{"Player.Process(videowidth)": ""})
    assert SnapshotBuilder().build()["metrics"]["frame"] is None


# --- Helpers ----------------------------------------------------------------

def test_the_property_sink_behaves_like_a_window():
    sink = snapshot.PropertySink()
    sink.setProperty("A", None)
    sink.setProperty("B", 5)
    assert (sink.getProperty("A"), sink.getProperty("B"), sink.getProperty("C")) == ("", "5", "")
    sink.clearProperty("B")
    sink.clearProperty("never set")
    assert sink.values == {"A": ""}


@pytest.mark.parametrize(("codec", "passthrough", "sink", "row"), [
    ("", True, "5.1", ""),                           # no audio track reads N/A
    ("truehd", True, "5.1", "#32242"),               # Passthrough
    ("truehd", False, "5.1", "5.1"),
    ("truehd", False, "", "#32243"),                 # Decoding
])
def test_the_audio_output_row(codec, passthrough, sink, row):
    xbmc.INFO["VideoPlayer.AudioCodec"] = codec
    xbmc.CONDITIONS["Player.Passthrough"] = passthrough
    assert web_rows.overlay_rows({"AudioChannelsSink": sink})["AudioOutputRow"] == row


SUBTITLE_VALUES = {"SubtitleNameShortVar": "DEU", "SubtitleNameVar": "Deutsch",
                   "SubtitleCodecVar": "PGS"}


@pytest.mark.parametrize(("has", "enabled", "rows"), [
    (True, True, {"SubtitleShortRow": "DEU", "SubtitleNameRow": "Deutsch",
                  "SubtitleCodecRow": "PGS"}),
    (True, False, {"SubtitleStateRow": "#32246"}),   # Disabled
    (False, True, {}),
])
def test_the_subtitle_rows(has, enabled, rows):
    xbmc.CONDITIONS["VideoPlayer.HasSubtitles"] = has
    xbmc.CONDITIONS["VideoPlayer.SubtitlesEnabled"] = enabled
    found = web_rows.overlay_rows(SUBTITLE_VALUES)
    assert {key: value for key, value in found.items() if key.startswith("Subtitle")} == rows


@pytest.mark.parametrize(("conditions", "values", "rows"), [
    ({"PVR.IsPlayingTV": True}, {}, {"PlaybackStateRow": "#32235"}),    # Live TV, no EPG
    ({"PVR.IsPlayingTV": True}, {"BroadcastTimes": "1", "PlayerDuration": "01:00:00",
                                 "PlayerTime": "00:30:00", "PlayerProgress": "50.0"},
     {"PlaybackTimeRow": "00:30:00", "PlaybackDurationRow": "01:00:00",
      "PlaybackProgressRow": "50.0"}),
    ({"Player.IsInternetStream": True}, {}, {"PlaybackStateRow": "#32236"}),  # no length
    ({}, {"PlayerDuration": "02:00:00", "PlayerTime": "00:10:00", "PlayerProgress": "8.3"},
     {"PlaybackTimeRow": "00:10:00", "PlaybackDurationRow": "02:00:00",
      "PlaybackProgressRow": "8.3"}),
    ({}, {}, {}),                                    # nothing known yet
])
def test_the_playback_rows(conditions, values, rows):
    xbmc.CONDITIONS.update(conditions)
    found = web_rows.overlay_rows(values)
    assert {key: value for key, value in found.items() if key.startswith("Playback")} == rows


@pytest.mark.parametrize("condition", [
    "Player.IsLive", "PVR.IsPlayingRecording", "PVR.IsPlayingRadio",
])
def test_no_finish_time_for_live_items_and_recordings(condition):
    xbmc.CONDITIONS[condition] = True
    values = {"PlayerDuration": "01:30:00", "PlayerFinishTime": "21:00"}
    assert web_rows.finish_time(values) == ""


def test_render_drops_empty_segments_and_their_separators():
    segments = (("a", "", ""), ("b", " | ", ""), ("c", " (", ")"))
    assert web_rows.render(segments, {"a": "1", "b": "", "c": "x"}) == "1 (x)"
    assert web_rows.render(segments, {}) == ""


@pytest.mark.parametrize(("live", "average", "row"), [
    ("12 Mb/s", "10 Mb/s", ("12 Mb/s -", "(Ø 10 Mb/s)")),
    ("12 Mb/s", "", ("12 Mb/s", "")), ("", "10 Mb/s", ("10 Mb/s", "")), ("", "", ("", "")),
])
def test_bitrate_rows(live, average, row):
    assert web_rows._bitrate_row(live, average) == row


def test_finish_time_only_for_a_known_length():
    assert web_rows.finish_time({"PlayerDuration": "00:00:00", "PlayerFinishTime": "21:00"}) == ""
    assert web_rows.finish_time({"PlayerDuration": "01:30:00", "PlayerFinishTime": "21:00"}) == "21:00"
    xbmc.CONDITIONS["PVR.IsPlayingTV"] = True
    assert web_rows.finish_time({"PlayerFinishTime": "21:00"}) == ""        # no EPG
    assert web_rows.finish_time({"BroadcastTimes": "1", "PlayerFinishTime": "21:00"}) == "21:00"


@pytest.mark.parametrize(("mode", "source", "output"), [
    ("DV-STD", "hdr10", "dolbyvision"), ("HDR10+", "hdr10plus", "hdr10plus"),
    ("HLG", "hlg", "hlg"), ("HDR10 BT2020", "dolbyvision", "hdr10"),
    ("SDR BT709", "hdr10", ""), ("", "dolbyvision", "dolbyvision"), ("  ", "hdr10", "hdr10"),
])
def test_the_output_type(mode, source, output):
    assert snapshot._output_hdr_type(mode, source) == output


def test_presence_values_become_markers():
    yes, no = xbmc.getLocalizedString(107), xbmc.getLocalizedString(106)
    row = snapshot._metadata_row("row", "[B]RPU[/B]", f"{yes} | 1000")
    assert row["name"] == "RPU" and row["value"].startswith("✔")
    cells = snapshot._metadata_row("table", "L2", [no, "3"])["cells"]
    assert cells == ["✘", "3"]


def test_artwork_skips_skin_textures():
    xbmc.INFO["VideoPlayer.Cover"] = "DefaultVideoCover.png"
    assert snapshot.art_path("poster") == ""
    xbmc.INFO["Player.Art(tvshow.poster)"] = "/art/show.jpg"
    assert snapshot.art_path("poster") == "/art/show.jpg"
    tags = snapshot._art_tags()
    assert len(tags["poster"]) == 8 and tags["fanart"] == ""
    assert snapshot.art_path("banner") == ""


def test_event_labels():
    values = {"AudioNameShortVar": "ENG", "AudioCodecVar": "TrueHD", "AudioChannelsVar": "7.1",
              "AudioCodecSpatialVar": "Atmos", "SubtitleNameShortVar": "DEU",
              "SubtitleNameVar": "Deutsch", "SubtitleCodecVar": "PGS"}
    assert snapshot.audio_event_label(values) == "ENG | TrueHD 7.1 Atmos"
    assert snapshot.subtitle_event_label(values) == "DEU | Deutsch (PGS)"
    assert snapshot.audio_event_label({}) == "" and snapshot.subtitle_event_label({}) == ""


# --- The producer -------------------------------------------------------------

class Builder:
    """Stands in for SnapshotBuilder: counts passes, can fail."""

    def __init__(self):
        self.seq = 0
        self.idle_passes = 0
        self.fail = False
        self.failures = 0
        self.session = type("Session", (), {"history": lambda self: {"t": [1]}})()
        self.options = []

    def build(self, detail=True, **options):
        if self.fail:
            self.failures += 1
            raise RuntimeError("side data unreadable")
        if not detail:
            self.idle_passes += 1
            return None
        self.options.append(options)
        self.seq += 1
        return {"seq": self.seq, "playing": True}


@pytest.fixture
def producer(monkeypatch):
    monkeypatch.setattr(producer_module, "PRODUCE_INTERVAL", 0.02)
    monkeypatch.setattr(producer_module, "_IDLE_INTERVAL", 0.02)
    monkeypatch.setattr(producer_module.library, "revision", lambda: 7)
    stop = threading.Event()
    thread = Producer(stop)
    thread._builder = Builder()
    thread.start()
    yield thread
    stop.set()
    thread.wake()
    thread.join(2)
    assert not thread.is_alive()


def wait_until(check, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return False


def test_without_watchers_only_the_session_is_kept(producer):
    assert wait_until(lambda: producer._builder.idle_passes >= 3)
    assert producer._builder.seq == 0


def test_a_watcher_gets_snapshots_with_the_library_revision(producer):
    seen = producer.watch()
    shot = producer.wait_for(seen, 2)
    assert shot["seq"] > seen and shot["library"] == 7
    later = producer.wait_for(shot["seq"], 2)
    assert later["seq"] > shot["seq"]
    producer.unwatch()
    producer.unwatch()                               # never below zero
    assert producer._watchers == 0


def test_settings_reach_the_builder(producer):
    xbmcaddon.SETTINGS.update({"filename": "false", "web_metadata": "true",
                               "web_allow_control": "true"})
    producer.watch()
    assert wait_until(lambda: producer._builder.options)
    assert producer._builder.options[-1] == {
        "allow_filename": False, "metadata": True, "control": True}


def test_fresh_builds_one_for_a_request(producer):
    shot = producer.fresh()
    assert shot["seq"] >= 1
    assert producer.history() == {"t": [1]}


def test_a_failing_pass_is_logged_once_and_recovery_too(producer):
    producer._builder.fail = True
    producer.watch()
    assert wait_until(lambda: producer._builder.failures >= 3)
    producer._builder.fail = False
    assert wait_until(lambda: any("snapshot recovered" in line for _level, line in xbmc.LOG))
    failures = [line for _level, line in xbmc.LOG if "snapshot failed" in line]
    assert len(failures) == 1


def test_waiting_ends_at_once_on_stop():
    stop = threading.Event()
    idle = Producer(stop)
    stop.set()
    started = time.monotonic()
    assert idle.wait_for(0, 5) is None
    assert time.monotonic() - started < 0.5
