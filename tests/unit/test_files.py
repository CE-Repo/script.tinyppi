# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Atomic file writes (core/files.py)."""

import os
import stat
import threading

import pytest

from core import files


def test_the_temporary_name_sits_next_to_the_target_and_differs_per_thread():
    names = []
    worker = threading.Thread(target=lambda: names.append(files.temp_path("/skin/Font.xml")))
    worker.start()
    worker.join()
    names.append(files.temp_path("/skin/Font.xml"))
    assert names[0] != names[1]
    for name in names:
        assert name.startswith("/skin/Font.xml.") and name.endswith(".tmp")
        assert os.path.dirname(name) == "/skin"
    assert files.temp_path("/skin/Font.xml") == names[1]       # stable within a thread


def test_a_new_file_is_written(tmp_path):
    target = tmp_path / "cache.json"
    files.atomic_write(str(target), b"{}")
    assert target.read_bytes() == b"{}"
    assert os.listdir(tmp_path) == ["cache.json"]


def test_a_replaced_file_keeps_its_permission_bits(tmp_path):
    target = tmp_path / "Font.xml"
    target.write_bytes(b"old")
    os.chmod(target, 0o640)
    files.atomic_write(str(target), b"new")
    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o640
    assert os.listdir(tmp_path) == ["Font.xml"]


def test_a_failed_rename_leaves_the_target_and_no_temporary_file(tmp_path):
    target = tmp_path / "Font.xml"
    target.mkdir()                          # a file cannot replace a directory
    (target / "inside").write_bytes(b"kept")
    with pytest.raises(OSError):
        files.atomic_write(str(target), b"new")
    assert os.listdir(tmp_path) == ["Font.xml"]
    assert (target / "inside").read_bytes() == b"kept"


def test_a_missing_folder_raises_without_leaving_anything(tmp_path):
    with pytest.raises(FileNotFoundError):
        files.atomic_write(str(tmp_path / "missing" / "Font.xml"), b"new")
    assert os.listdir(tmp_path) == []


def test_an_interrupted_write_removes_the_temporary_file(tmp_path, monkeypatch):
    target = tmp_path / "Font.xml"
    target.write_bytes(b"old")

    def interrupted(_fd):
        raise KeyboardInterrupt
    monkeypatch.setattr(files.os, "fsync", interrupted)
    with pytest.raises(KeyboardInterrupt):
        files.atomic_write(str(target), b"new")
    assert target.read_bytes() == b"old"
    assert os.listdir(tmp_path) == ["Font.xml"]
