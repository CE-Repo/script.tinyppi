# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

import os
import re

import pytest

from ui import fonts

FONT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<fonts>
    <fontset id="Default" idloc="31390">
        <include name="Defaults"/>
        <font>
            <name>font10</name>
            <filename>NotoSans-Regular.ttf</filename>
            <size>20</size>
        </font>
    </fontset>
    <fontset id="Arial" idloc="31391">
        <font>
            <name>font32</name>
            <filename>arial.ttf</filename>
            <size>40</size>
        </font>
    </fontset>
</fonts>
"""


@pytest.fixture
def skin(kodi):
    """The skin special://skin/ points at, with a Font.xml in its 1080i
    folder."""
    root = kodi.special["special://skin/"]
    os.makedirs(os.path.join(root, "1080i"))
    path = os.path.join(root, "1080i", "Font.xml")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(FONT_XML)
    return path


def _read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def test_entries_go_into_every_fontset(skin):
    assert not fonts.fonts_already_installed("", skin)
    assert fonts._install_xml("", skin)
    assert fonts.fonts_already_installed("", skin)
    text = _read(skin)
    assert text.count("<name>font23_narrow</name>") == 2
    # Ahead of the skin's own font32, which Kodi then never reads.
    assert text.index("<size>32</size>") < text.index("<size>40</size>")


def test_nothing_else_in_the_file_changes(skin):
    fonts._install_xml("", skin)
    # Each inserted block, with the line break it was introduced by.
    inserted = re.compile(
        r"\n[ \t]*<font>(?:(?!</font>).)*special://xbmc/(?:(?!</font>).)*</font>",
        re.DOTALL)
    assert inserted.sub("", _read(skin)) == FONT_XML


def test_second_install_changes_nothing(skin):
    assert fonts._install_xml("", skin)
    before = _read(skin)
    assert not fonts._install_xml("", skin)
    assert _read(skin) == before


def test_crlf_line_endings_are_kept(skin):
    with open(skin, "w", encoding="utf-8", newline="") as handle:
        handle.write(FONT_XML.replace("\n", "\r\n"))
    fonts._install_xml("", skin)
    text = _read(skin)
    assert "\n" not in text.replace("\r\n", "")


def test_skin_is_found_through_special_skin(skin, kodi):
    assert fonts._get_skin_path() == os.path.normpath(
        kodi.special["special://skin/"])


def test_ensure_fonts_installs_and_marks(skin, kodi):
    fonts.ensure_fonts()
    assert fonts.fonts_already_installed("", skin)
    assert "ReloadSkin(reload)" in kodi.builtins
    assert fonts._mark_holds(fonts.PROP_FONTS_READY)


def test_failed_install_is_not_retried_until_the_file_changes(skin, kodi,
                                                             monkeypatch):
    def refuse(path, data):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(fonts, "atomic_write", refuse)
    attempts = []
    real_install = fonts._install_fonts
    monkeypatch.setattr(fonts, "_install_fonts",
                        lambda: (attempts.append(1), real_install()))

    fonts.ensure_fonts()
    fonts.ensure_fonts()
    fonts.ensure_fonts()
    assert len(attempts) == 1
    assert _read(skin) == FONT_XML
    assert fonts._mark_holds(fonts.PROP_FONTS_FAILED)

    # A skin update rewrites the file: the mark lapses and it is tried again.
    with open(skin, "a", encoding="utf-8") as handle:
        handle.write("<!-- updated -->\n")
    fonts.ensure_fonts()
    assert len(attempts) == 2


def test_marks_lapse_with_a_skin_switch(skin, kodi):
    fonts.ensure_fonts()
    kodi.skin_dir = "skin.other"
    assert not fonts._settled()
