# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Artwork sources and types (web/artwork.py)."""

import pytest

import xbmc
from web import artwork

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_image_type_comes_from_the_bytes():
    assert artwork.image_type(JPEG, "image/png") == "image/jpeg"
    assert artwork.image_type(PNG, "image/jpeg") == "image/png"
    assert artwork.image_type(b"RIFF0000WEBP", "x") == "image/webp"
    assert artwork.image_type(b"????", "image/gif") == "image/gif"


def test_the_texture_cache_comes_first():
    plain = "/films/Film (2020)/poster.png"
    assert artwork.art_sources(plain)[0] == "image://%2Ffilms%2FFilm%20%282020%29%2Fposter.png/"
    assert artwork.art_sources(plain)[1] == plain
    wrapped = "image://smb%3a%2f%2fnas%2fposter.jpg/"
    assert artwork.art_sources(wrapped) == (wrapped, "smb://nas/poster.jpg")


def test_credentials_are_kept_out_of_logs():
    assert artwork.redacted("smb://user:secret@nas/poster.jpg") == "smb://***@nas/poster.jpg"


def test_playing_artwork_prefers_the_cache_and_sniffs_the_type(monkeypatch):
    reads = []

    def read_art(path):
        reads.append(path)
        return JPEG if path.startswith("image://") else PNG

    monkeypatch.setattr(artwork, "read_art", read_art)
    monkeypatch.setattr(artwork, "art_path", lambda kind: "/films/poster.png")
    cache = artwork.PlayingArtwork()
    data, content_type = cache.get("poster")
    # Kodi's cache keeps an opaque PNG as a JPEG; the type follows the bytes.
    assert data == JPEG and content_type == "image/jpeg"
    assert reads == ["image://%2Ffilms%2Fposter.png/"]
    cache.get("poster")
    assert len(reads) == 1        # held for the same picture


def test_playing_artwork_falls_back_to_the_original(monkeypatch):
    monkeypatch.setattr(artwork, "read_art",
                        lambda path: None if path.startswith("image://") else PNG)
    monkeypatch.setattr(artwork, "art_path", lambda kind: "/films/poster.png")
    assert artwork.PlayingArtwork().get("poster") == (PNG, "image/png")


@pytest.mark.parametrize(("data", "content_type"), [
    (b"GIF87a" + b"0" * 8, "image/gif"),
    (b"GIF89a" + b"0" * 8, "image/gif"),
    (b"RIFF0000WAVE", "image/bmp"),         # RIFF, but no WebP
    (b"", "image/bmp"),
])
def test_other_image_types_and_the_fallback(data, content_type):
    assert artwork.image_type(data, "image/bmp") == content_type


@pytest.mark.parametrize(("path", "content_type"), [
    ("/a/poster.PNG", "image/png"), ("/a/fanart.webp", "image/webp"), ("/a/poster", "image/jpeg"),
    ("/a/poster.tbn", "image/jpeg"),
])
def test_the_extension_names_the_expected_type(path, content_type):
    assert artwork.art_type(path) == content_type


def test_unwrapping_leaves_plain_paths_alone():
    assert artwork.unwrap_image_url("/films/poster.jpg") == "/films/poster.jpg"
    assert artwork.unwrap_image_url("image://%2Ffilms%2Fposter.jpg") == "/films/poster.jpg"


def test_artwork_is_read_through_the_vfs(tmp_path):
    picture = tmp_path / "poster.jpg"
    picture.write_bytes(JPEG)
    assert artwork.read_art(str(picture)) == JPEG


def test_an_empty_artwork_file_is_no_artwork(tmp_path):
    picture = tmp_path / "poster.jpg"
    picture.write_bytes(b"")
    assert artwork.read_art(str(picture)) is None


def test_an_unreadable_artwork_is_logged_at_debug(tmp_path):
    missing = str(tmp_path / "missing.jpg")
    assert artwork.read_art(missing) is None
    [(level, line)] = [entry for entry in xbmc.LOG if missing in entry[1]]
    assert level == xbmc.LOGDEBUG and f"artwork {missing} unreadable" in line


class Handle:
    """A VFS file that fails as told; records whether it was closed."""

    opened: list = []

    def __init__(self, path, mode="r"):
        self.closed = False
        Handle.opened.append(self)

    def readBytes(self, size=-1):  # noqa: N802 - Kodi API
        if self.fail_read:
            raise RuntimeError("share went away")
        return bytearray(PNG)

    def close(self):
        self.closed = True
        if self.fail_close:
            raise OSError("close failed")


@pytest.mark.parametrize(("fail_read", "fail_close", "result"), [
    (True, False, None),
    (False, True, PNG),       # a failing close is not the caller's problem
    (True, True, None),
])
def test_an_opened_artwork_is_always_closed(monkeypatch, fail_read, fail_close, result):
    monkeypatch.setattr(Handle, "opened", [])
    monkeypatch.setattr(Handle, "fail_read", fail_read, raising=False)
    monkeypatch.setattr(Handle, "fail_close", fail_close, raising=False)
    monkeypatch.setattr(artwork.xbmcvfs, "File", Handle)
    assert artwork.read_art("smb://nas/poster.png") == result
    assert [handle.closed for handle in Handle.opened] == [True]


def test_nothing_playing_has_no_artwork(monkeypatch):
    reads = []
    monkeypatch.setattr(artwork, "art_path", lambda kind: "")
    monkeypatch.setattr(artwork, "read_art", reads.append)
    assert artwork.PlayingArtwork().get("poster") is None
    assert reads == []


def test_unreadable_playing_artwork_is_none_and_not_held(monkeypatch):
    reads = []

    def read_art(path):
        reads.append(path)

    monkeypatch.setattr(artwork, "read_art", read_art)
    monkeypatch.setattr(artwork, "art_path", lambda kind: "smb://user:pw@nas/poster.png")
    cache = artwork.PlayingArtwork()
    assert cache.get("poster") is None
    assert cache.get("poster") is None
    assert len(reads) == 4                 # cache copy and original, each time


def test_a_new_playing_picture_replaces_the_held_one(monkeypatch):
    path = ["/films/a.png"]
    monkeypatch.setattr(artwork, "art_path", lambda kind: path[0])
    monkeypatch.setattr(artwork, "read_art", lambda source: source.encode())
    cache = artwork.PlayingArtwork()
    assert cache.get("poster")[0] == b"image://%2Ffilms%2Fa.png/"
    path[0] = "/films/b.png"
    assert cache.get("poster")[0] == b"image://%2Ffilms%2Fb.png/"


def test_an_original_sent_without_a_cached_copy_is_logged_without_credentials(monkeypatch):
    monkeypatch.setattr(artwork, "read_art",
                        lambda path: None if path.startswith("image://") else JPEG)
    assert artwork.shelf_picture("smb://user:pw@nas/poster.png") == (JPEG, "image/jpeg")
    [line] = [line for level, line in xbmc.LOG if "no cached texture" in line]
    assert "smb://***@nas/poster.png" in line and "pw" not in line


def test_a_shelf_without_a_picture_reads_nothing(monkeypatch):
    reads = []
    monkeypatch.setattr(artwork, "read_art", reads.append)
    assert artwork.shelf_picture("") is None
    assert artwork.shelf_picture("/films/poster.jpg") is None
    assert reads == ["image://%2Ffilms%2Fposter.jpg/", "/films/poster.jpg"]


def test_an_unreadable_artwork_logs_no_credentials():
    assert artwork.read_art("smb://user:secret@nas/posters/film.jpg") is None
    lines = [line for _level, line in xbmc.LOG if "unreadable" in line]
    assert lines and "secret" not in lines[0] and "smb://***@nas/posters/film.jpg" in lines[0]
