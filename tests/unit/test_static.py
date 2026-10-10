# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's route table and static file cache (web/static.py)."""

import builtins
import gzip
import os
import random

import pytest

import xbmcaddon
from web import static

HTML = "text/html; charset=utf-8"


@pytest.fixture
def addon_folder(tmp_path, monkeypatch):
    """Point the add-on's install path at an empty folder."""
    real = xbmcaddon.Addon.getAddonInfo

    def info(self, key):
        return str(tmp_path) if key == "path" else real(self, key)

    monkeypatch.setattr(xbmcaddon.Addon, "getAddonInfo", info)
    return tmp_path


def _write(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def test_the_page_and_its_files_are_routed_from_the_addon_folder():
    table = static.routes()
    web = os.path.join(xbmcaddon.ROOT, "resources", "web")
    index = (os.path.join(web, "index.html"), HTML)
    for route in ("/", "/index.html", "/metadata", "/metadata.html"):
        assert table[route] == index
    assert table["/manifest.webmanifest"] == (os.path.join(web, "manifest.webmanifest"),
                                              "application/manifest+json")
    assert table["/icon.png"] == (os.path.join(xbmcaddon.ROOT, "icon.png"), "image/png")
    assert table["/fanart.png"] == (os.path.join(xbmcaddon.ROOT, "fanart.png"), "image/png")
    assert table["/css/base.css"] == (os.path.join(web, "css", "base.css"),
                                      "text/css; charset=utf-8")


def test_only_known_types_directly_in_the_served_folders_are_routed(addon_folder):
    web = addon_folder / "resources" / "web"
    style = _write(web / "css" / "site.css")
    logo = _write(web / "icons" / "Logo.SVG")
    _write(web / "css" / ".hidden.css")
    _write(web / "css" / "notes.txt")
    _write(web / "css" / "old.css" / "inside.css")
    _write(web / "fonts" / "font.css")
    # No js folder at all: skipped, not an error.

    table = static.routes()

    served = {route: entry for route, entry in table.items()
              if route.startswith(("/css/", "/js/", "/icons/", "/fonts/"))}
    assert served == {
        "/css/site.css": (style, "text/css; charset=utf-8"),
        "/icons/Logo.SVG": (logo, "image/svg+xml"),
    }
    # The fixed routes are there whether or not their files exist.
    assert table["/"] == (str(web / "index.html"), HTML)
    assert table["/icon.png"] == (str(addon_folder / "icon.png"), "image/png")


def test_a_missing_file_is_not_found(tmp_path):
    assert static.StaticFiles().get(str(tmp_path / "gone.css"), "text/css") is None


def test_a_folder_in_place_of_a_file_is_not_found(tmp_path):
    folder = tmp_path / "style.css"
    folder.mkdir()
    assert static.StaticFiles().get(str(folder), "text/css") is None


_NOISE = random.Random(7).randbytes(2000)


@pytest.mark.parametrize(("content_type", "body", "compressed"), [
    ("text/css; charset=utf-8", b"body { color: red; }\n" * 60, True),
    ("application/json", b'{"seq": 1}, ' * 80, True),
    ("application/manifest+json", b'{"name": "TinyPPI"} ' * 40, True),
    ("image/svg+xml", b"<path d='M0 0h24v24H0z'/>" * 30, True),
    ("text/plain", b"a" * static.MIN_COMPRESS, True),
    ("text/plain", b"a" * (static.MIN_COMPRESS - 1), False),
    ("image/png", b"\x89PNG" + b"\0" * 2000, False),
    ("text/javascript; charset=utf-8", _NOISE, False),
], ids=["css", "json", "manifest", "svg", "at-minimum", "below-minimum", "png", "incompressible"])
def test_text_worth_compressing_gets_a_gzip_copy(tmp_path, content_type, body, compressed):
    path = _write(tmp_path / "file", body)

    plain, packed, _etag = static.StaticFiles().get(path, content_type)

    assert plain == body
    if compressed:
        assert len(packed) < len(body)
        assert gzip.decompress(packed) == body
    else:
        assert packed is None


def test_an_unchanged_file_keeps_its_etag_across_restarts(tmp_path):
    path = _write(tmp_path / "site.css", b"body {}")
    other = _write(tmp_path / "other.css", b"p {}")
    first = static.StaticFiles().get(path, "text/css")[2]
    # A new cache (the server restarted) gives the same validator, so browsers keep their copy.
    assert static.StaticFiles().get(path, "text/css")[2] == first
    assert first.startswith('"') and first.endswith('"') and len(first) > 2
    assert static.StaticFiles().get(other, "text/css")[2] != first


def test_a_file_is_read_once_until_it_changes(tmp_path, monkeypatch):
    opened = []

    def counting_open(path, *args, **kwargs):
        opened.append(path)
        return builtins.open(path, *args, **kwargs)

    monkeypatch.setattr(static, "open", counting_open, raising=False)
    path = _write(tmp_path / "site.css", b"body {}")
    files = static.StaticFiles()

    first = files.get(path, "text/css")
    assert files.get(path, "text/css") is first
    assert opened == [path]

    # Replaced with a different size.
    _write(tmp_path / "site.css", b"body { margin: 0; }")
    resized = files.get(path, "text/css")
    assert resized[0] == b"body { margin: 0; }"
    assert resized[2] != first[2]

    # Same size, newer mtime (an update rewrote it).
    _write(tmp_path / "site.css", b"body { margin: 1; }")
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    touched = files.get(path, "text/css")
    assert touched[0] == b"body { margin: 1; }"
    assert touched[2] != resized[2]
    assert opened == [path] * 3
