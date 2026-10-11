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
    assert shot["controls"] == {}
    ids = [group["id"] for group in shot["groups"]]
    assert ids[0] == "video" and len(ids) == len(set(ids))
    for group in shot["groups"]:
        for row in group["rows"]:
            assert row["value"]                       # empty readings read N/A


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
