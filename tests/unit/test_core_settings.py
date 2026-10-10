# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The cached settings handle (core/settings.py)."""

import os

import pytest

import xbmcaddon
import xbmcvfs
from core import settings


@pytest.fixture
def values_file(monkeypatch, tmp_path):
    """The stored values file under a private special:// folder, not yet written."""
    monkeypatch.setattr(xbmcvfs, "HOME", str(tmp_path))
    monkeypatch.setattr(settings, "_current", settings._Handle())
    path = tmp_path / "profile" / "addon_data" / "script.tinyppi" / "settings.xml"
    path.parent.mkdir(parents=True)
    return path


def test_the_handle_is_kept_while_no_values_are_stored(values_file):
    first = settings.addon()
    assert isinstance(first, xbmcaddon.Addon)
    assert settings.addon() is first


def test_a_changed_values_file_gives_a_new_handle(values_file):
    before = settings.addon()
    values_file.write_text("<settings version='2'/>")
    stored = settings.addon()
    assert stored is not before
    assert settings.addon() is stored                    # unchanged: kept
    values_file.write_text("<settings version='2'><setting id='a'>1</setting></settings>")
    assert settings.addon() is not stored


def test_the_values_file_is_found_through_special_paths(values_file):
    handle = settings._Handle()
    assert handle._values_stamp() is None                # nothing to stat yet
    handle.get()
    assert handle._path == str(values_file)
    values_file.write_text("x" * 7)
    stamp = handle._values_stamp()
    assert stamp is not None and stamp[1] == 7
    assert stamp == (os.stat(values_file).st_mtime_ns, 7, os.stat(values_file).st_ino)


def test_a_failing_addon_lookup_is_raised(values_file, monkeypatch):
    def unregistered():
        raise RuntimeError("Unknown addon id 'script.tinyppi'.")
    monkeypatch.setattr(xbmcaddon, "Addon", unregistered)
    with pytest.raises(RuntimeError, match="Unknown addon id"):
        settings.addon()
