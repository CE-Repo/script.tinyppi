# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The media source row (info/mediasource.py): release type, container, size."""

import pytest

import xbmc
import xbmcvfs
from info import mediasource


@pytest.fixture
def playing(monkeypatch):
    """Return a function that makes Kodi report *path* as the playing file."""
    monkeypatch.setattr(mediasource, "_sizes", mediasource.KeyedMemo())

    def play(path):
        class Player(xbmc.Player):
            def getPlayingFile(self):
                return path
        monkeypatch.setattr(xbmc, "Player", Player)
    return play


@pytest.mark.parametrize(("name", "label"), [
    ("Film.2019.2160p.UHD.BluRay.REMUX.HEVC", "Remux"),
    ("Film.2019.2160p.UHD.BluRay.x265", "UHD BD"),
    ("Film.2019.1080p.BluRay.x264", "BD"),
    ("Film.2019.1080p.WEB-DL.DDP5.1", "WEB-DL"),
    ("Film.2019.1080p.WEBRip.x264", "WEBRip"),
    ("Film.2019.1080p.WEB.h264", "WEB"),
    ("Film.2019.HDTV.x264", "HDTV"),
    ("Film.2019.DVDRip", "DVD"),
    # "Web" as an ordinary word, and "BR" as a language tag, say nothing.
    ("Charlotte's Web (1973)", ""),
    ("Film.2019.German.BR", ""),
    ("Film (2019)", ""),
])
def test_release_types(name, label):
    assert mediasource._release_type(name) == label


def test_tags_on_the_folder_count_too():
    path = "/films/Film.2019.2160p.UHD.BluRay.REMUX/film.mkv"
    assert mediasource._release_type_from_path(path) == "Remux"


@pytest.mark.parametrize(("path", "label"), [
    ("/films/film.mkv", "MKV"),
    ("/films/film.M2TS", "TS"),
    ("http://server/stream/film.mp4?token=abc", "MP4"),
    ("http://server/live/index.m3u8", ""),
    ("/films/no-extension", ""),
])
def test_containers(path, label):
    assert mediasource._container(path) == label


@pytest.mark.parametrize(("path", "protocol"), [
    ("http://cdn/live/index.m3u8", "HLS"),
    ("https://cdn/manifest.mpd", "DASH"),
    ("rtmp://server/live", "RTMP"),
    ("rtsp://camera/stream", "RTSP"),
    ("/films/film.mkv", ""),
])
def test_stream_protocols(path, protocol):
    assert mediasource._stream_protocol(path) == protocol


def test_a_local_file_reads_type_container_and_size(playing, tmp_path):
    film = tmp_path / "Film.2019.1080p.BluRay.x264.mkv"
    film.write_bytes(b"\0" * (3 * 1024 * 1024))
    playing(str(film))
    assert mediasource.get_MediaSourceVar() == "BD · MKV · 3MB"


def test_addon_streams_are_never_measured():
    xbmc.INFO["Player.FilenameAndPath"] = "plugin://plugin.video.example/play/1"
    assert not mediasource._statable("https://cdn.example.com/video/film.mp4")
    assert not mediasource._statable("plugin://plugin.video.example/play/1")
    assert mediasource._statable("smb://nas/films/film.mkv")


def test_live_items_name_the_transport(playing):
    playing("http://cdn/live/channel.m3u8")
    assert mediasource.get_MediaSourceVar() == "HLS"
    xbmc.CONDITIONS["PVR.IsPlayingTV"] = True
    playing("pvr://channels/tv/1.pvr")
    assert mediasource.get_MediaSourceVar() == "PVR"


def test_discs(playing):
    playing("bluray://udf%3a%2f%2f%252fFilme%252fDunkirk.iso%2f/BDMV/PLAYLIST/00800.mpls")
    assert mediasource.get_MediaSourceVar() == "BD Disc"


def test_an_opaque_server_path_names_the_protocol(playing):
    playing("smb://nas/library/12345")
    assert mediasource.get_MediaSourceVar() == "SMB"


def test_nothing_known_reads_na(playing):
    playing("")
    assert mediasource.get_MediaSourceVar() == mediasource.na_label()


def test_a_bare_file_name_has_no_folder_to_read():
    assert mediasource._release_type_from_path("Film.2019.1080p.BluRay.x264.mkv") == "BD"
    assert mediasource._release_type_from_path("film") == ""
    assert mediasource._release_type_from_path("/") == ""


class FakeStat:
    """xbmcvfs.Stat answering from SIZES, counting calls; None raises."""

    SIZES: dict = {}
    calls: list = []

    def __init__(self, path):
        FakeStat.calls.append(path)
        self._size = FakeStat.SIZES[path]
        if self._size is None:
            raise RuntimeError("no such file")

    def st_size(self):
        return self._size


@pytest.fixture
def stat(monkeypatch):
    monkeypatch.setattr(mediasource, "_sizes", mediasource.KeyedMemo())
    monkeypatch.setattr(xbmcvfs, "Stat", FakeStat)
    monkeypatch.setattr(FakeStat, "SIZES", {})
    monkeypatch.setattr(FakeStat, "calls", [])
    return FakeStat


@pytest.mark.parametrize(("size", "text"), [
    (42 * 1024 ** 3, "42GB"),
    (int(1.6 * 1024 ** 3), "2GB"),
    (700 * 1024 ** 2, "700MB"),
    (512 * 1024, ""),
    (0, ""),
    (None, ""),
])
def test_sizes_in_whole_gigabytes_or_megabytes(stat, size, text):
    stat.SIZES["smb://nas/films/film.mkv"] = size
    assert mediasource._size_text("smb://nas/films/film.mkv") == text


def test_a_failed_stat_is_logged():
    assert mediasource._measure("/nowhere/film.mkv") == ""
    assert any("size of /nowhere/film.mkv unknown" in line for _level, line in xbmc.LOG)


def test_the_size_is_measured_once_per_path(stat):
    stat.SIZES.update({"/films/a.mkv": 2 * 1024 ** 3, "/films/b.mkv": None})
    assert mediasource._size_text("/films/a.mkv") == "2GB"
    assert mediasource._size_text("/films/a.mkv") == "2GB"
    # Failures are remembered too, so a bad path is not stat'd every tick.
    assert mediasource._size_text("/films/b.mkv") == ""
    assert mediasource._size_text("/films/b.mkv") == ""
    assert stat.calls == ["/films/a.mkv", "/films/b.mkv"]
    assert mediasource._size_text("") == ""


@pytest.mark.parametrize("path", [
    "", "plugin://plugin.video.example/play/1", "pvr://channels/tv/1.pvr",
    "bluray://udf/BDMV/PLAYLIST/00800.mpls",
])
def test_paths_that_are_never_measured(stat, path):
    assert not mediasource._statable(path)
    assert mediasource._measure(path) == ""
    assert stat.calls == []


def test_the_addon_is_found_from_the_playing_item(monkeypatch):
    class Item:
        def getPath(self):
            return "PLUGIN://plugin.video.example/play/1"

    class Player(xbmc.Player):
        def getPlayingItem(self):
            return Item()
    monkeypatch.setattr(xbmc, "Player", Player)
    assert mediasource._item_path() == "PLUGIN://plugin.video.example/play/1"
    assert mediasource._is_addon_item()
    assert not mediasource._statable("https://cdn.example.com/film.mp4")


def test_without_a_playing_item_the_link_is_not_an_addons():
    # The stub player raises for the item, like Kodi with nothing playing.
    assert mediasource._item_path() == ""
    assert not mediasource._is_addon_item()
    assert mediasource._statable("https://server.example.com/library/film.mkv")


# The condition Kodi < 22 uses for "live": an internet stream without a duration.
NO_DURATION = "Player.IsInternetStream + String.IsEmpty(Player.Duration)"


def test_a_media_server_file_reads_like_a_local_one(playing, stat):
    url = "https://server.example.com/library/Film.2019.2160p.WEB-DL.x265.mkv"
    stat.SIZES[url] = 18 * 1024 ** 3
    # Kodi calls an http file an internet stream, but it has a duration.
    xbmc.CONDITIONS["Player.IsInternetStream"] = True
    playing(url)
    assert mediasource.get_MediaSourceVar() == "WEB-DL · MKV · 18GB"


@pytest.mark.parametrize("condition", ["Player.IsLive", NO_DURATION])
def test_a_live_http_stream_is_neither_named_nor_measured(playing, stat, condition):
    xbmc.CONDITIONS[condition] = True
    playing("https://server.example.com/live/Film.2019.2160p.WEB-DL.x265.mkv")
    assert mediasource.is_live()
    assert mediasource.get_MediaSourceVar() == "MKV"
    assert stat.calls == []


def test_nothing_playing_reads_na():
    # The stub player raises, like Kodi with nothing playing.
    assert mediasource.get_MediaSourceVar() == mediasource.na_label()


def test_a_live_stream_without_a_protocol_shows_its_container(playing):
    xbmc.CONDITIONS["Player.IsLive"] = True
    playing("http://tuner.local/stream/channel.ts")
    assert mediasource.get_MediaSourceVar() == "TS"


def test_a_failed_stat_logs_no_credentials():
    assert mediasource._measure("smb://user:secret@nas/films/film.mkv") == ""
    lines = [line for _level, line in xbmc.LOG if "unknown" in line]
    assert lines and "secret" not in lines[0] and "smb://***@nas/films/film.mkv" in lines[0]
