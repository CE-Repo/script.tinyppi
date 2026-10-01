# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

import os
import stat

import pytest
import xbmc

from core import files, log
from core.helpers import format_fps, normalize_fps


# --- core.log ------------------------------------------------------------------

def test_log_tags_every_line(kodi):
    log.log("hello")
    assert kodi.logged == [("TinyPPI: hello", xbmc.LOGDEBUG)]


def test_channel_names_its_area_and_default_level(kodi):
    write = log.channel("web", xbmc.LOGINFO)
    write("listening")
    write("gone", xbmc.LOGERROR)
    assert kodi.logged == [
        ("TinyPPI [web]: listening", xbmc.LOGINFO),
        ("TinyPPI [web]: gone", xbmc.LOGERROR),
    ]


def test_force_debug_promotes_debug_lines_only(kodi, monkeypatch):
    monkeypatch.setattr(log, "FORCE_DEBUG", True)
    log.log("detail")
    log.log("problem", xbmc.LOGWARNING)
    assert kodi.logged == [("TinyPPI: detail", xbmc.LOGINFO),
                           ("TinyPPI: problem", xbmc.LOGWARNING)]


# --- core.files ----------------------------------------------------------------

def test_atomic_write_creates_and_replaces(tmp_path):
    target = tmp_path / "Font.xml"
    files.atomic_write(str(target), b"first")
    files.atomic_write(str(target), b"second")
    assert target.read_bytes() == b"second"
    assert os.listdir(tmp_path) == ["Font.xml"]


def test_atomic_write_keeps_permissions(tmp_path):
    target = tmp_path / "Font.xml"
    target.write_bytes(b"old")
    os.chmod(target, 0o640)
    files.atomic_write(str(target), b"new")
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o640


def test_failed_write_leaves_target_and_no_temp_file(tmp_path):
    target = tmp_path / "Font.xml"
    target.write_bytes(b"intact")
    with pytest.raises(TypeError):
        files.atomic_write(str(target), "not bytes")  # type: ignore[arg-type]
    assert target.read_bytes() == b"intact"
    assert os.listdir(tmp_path) == ["Font.xml"]


def test_temp_path_is_recognisable():
    assert files.temp_path("/x/logo.png").endswith(".tmp")
    assert files.temp_path("/x/logo.png").startswith("/x/logo.png.")


# --- core.helpers --------------------------------------------------------------

@pytest.mark.parametrize("raw, shown", [
    (23.976023, "23.976"),
    (24.0, "24"),
    ("25", "25"),
    (29.97002, "29.97"),
    (59.94006, "59.94"),
    (48.5, "48.5"),          # nowhere near a standard rate
    ("n/a", "n/a"),
])
def test_normalize_fps(raw, shown):
    assert normalize_fps(raw) == shown


@pytest.mark.parametrize("raw, shown", [
    (23.99, "23.976"),
    (60.005, "60"),
    (25.0, "25"),
    (12.3456, "12.346"),
    (None, ""),
])
def test_format_fps(raw, shown):
    assert format_fps(raw) == shown
