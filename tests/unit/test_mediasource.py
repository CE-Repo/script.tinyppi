# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The media source row (info/mediasource.py): release type, container, size."""

import pytest

import xbmc
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
