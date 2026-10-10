# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Tagged logging into Kodi's log (core/log.py)."""

import pytest

import xbmc
from core import log


def test_lines_are_tagged_with_the_addon():
    log.log("mode 'dv' set")
    log.log("driver refused", xbmc.LOGERROR)
    assert xbmc.LOG == [(xbmc.LOGDEBUG, "TinyPPI: mode 'dv' set"),
                        (xbmc.LOGERROR, "TinyPPI: driver refused")]


def test_a_channel_tags_its_area_and_uses_its_default_level():
    web = log.channel("web", xbmc.LOGINFO)
    web("dashboard listening")
    web("port in use", xbmc.LOGWARNING)
    log.channel("images")("scaled")
    assert xbmc.LOG == [(xbmc.LOGINFO, "TinyPPI [web]: dashboard listening"),
                        (xbmc.LOGWARNING, "TinyPPI [web]: port in use"),
                        (xbmc.LOGDEBUG, "TinyPPI [images]: scaled")]


@pytest.mark.parametrize(("level", "written"), [
    (xbmc.LOGDEBUG, xbmc.LOGINFO), (xbmc.LOGINFO, xbmc.LOGINFO),
    (xbmc.LOGWARNING, xbmc.LOGWARNING), (xbmc.LOGERROR, xbmc.LOGERROR),
])
def test_forced_debug_raises_only_debug_lines_to_info(monkeypatch, level, written):
    monkeypatch.setattr(log, "FORCE_DEBUG", True)
    log.log("line", level)
    log.channel("web")("line", level)
    levels = [entry[0] for entry in xbmc.LOG]
    assert levels == [written, written]
    assert [entry[1] for entry in xbmc.LOG] == ["TinyPPI: line", "TinyPPI [web]: line"]


@pytest.mark.parametrize(("path", "logged"), [
    ("smb://user:secret@nas/Films/film.mkv", "smb://***@nas/Films/film.mkv"),
    ("ftp://user@host/film.mkv", "ftp://***@host/film.mkv"),
    ("/storage/videos/film.mkv", "/storage/videos/film.mkv"),
])
def test_credentials_are_taken_out_of_a_logged_path(path, logged):
    assert log.redacted(path) == logged
