# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Artwork sources and types (web/artwork.py)."""

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
    monkeypatch.setattr(artwork, "read_art", lambda path: None if path.startswith("image://") else PNG)
    monkeypatch.setattr(artwork, "art_path", lambda kind: "/films/poster.png")
    assert artwork.PlayingArtwork().get("poster") == (PNG, "image/png")
