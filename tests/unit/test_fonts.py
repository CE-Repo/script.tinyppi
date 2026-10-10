# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Registering the overlay's fonts in the skin's Font.xml (ui/fonts.py)."""

import os

import pytest

import xbmc
import xbmcgui
import xbmcvfs
from ui import fonts

FONT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<fonts>
    <fontset id="Default" idloc="31390">
        <include>Fonts</include>
        <font>
            <name>font32</name>
            <filename>arial.ttf</filename>
            <size>30</size>
        </font>
    </fontset>
    <fontset id="Arial">
        <font>
            <name>font13</name>
            <filename>arial.ttf</filename>
            <size>20</size>
        </font>
    </fontset>
</fonts>
"""

ADDON_XML = """<addon id="skin.test">
    <extension point="xbmc.gui.skin">
        <res width="1920" height="1080" aspect="16:9" default="true" folder="xml" />
        <!-- <res width="1280" height="720" folder="720p" /> -->
        <res width="3840" height="2160" folder="../outside" />
        <res width="1280" height="720" folder="" />
    </extension>
</addon>
"""


@pytest.fixture
def skin(tmp_path, monkeypatch):
    folder = tmp_path / "skin.test"
    (folder / "xml").mkdir(parents=True)
    (folder / "addon.xml").write_text(ADDON_XML)
    (folder / "xml" / "Font.xml").write_text(FONT_XML)
    monkeypatch.setattr(fonts, "_get_skin_path", lambda: str(folder))
    return folder


def home():
    return xbmcgui.Window(10000)


def entries(text):
    return [fonts._fontset_entries(inner) for _open, inner, _close in fonts._FONTSET_RE.findall(text)]


def test_only_the_declared_folders_inside_the_skin_count(skin):
    (skin / "720p").mkdir()
    (skin / "720p" / "Font.xml").write_text(FONT_XML)
    assert fonts._res_folders(str(skin)) == [str(skin / "xml")]
    assert fonts._find_font_xmls(str(skin)) == [str(skin / "xml" / "Font.xml")]


def test_without_res_folders_the_skin_is_walked(skin):
    (skin / "addon.xml").write_text("<addon/>")
    (skin / "media").mkdir()
    (skin / "media" / "font.xml").write_text(FONT_XML)          # skipped
    (skin / "16x9").mkdir()
    (skin / "16x9" / "font.XML").write_text(FONT_XML)
    assert fonts._find_font_xmls(str(skin)) == sorted(
        [str(skin / "16x9" / "font.XML"), str(skin / "xml" / "Font.xml")])


def test_a_skin_without_font_xml(tmp_path):
    assert fonts._find_font_xmls(str(tmp_path)) == []


def test_every_fontset_gets_the_missing_entries_after_its_include(skin):
    path = str(skin / "xml" / "Font.xml")
    assert not fonts.fonts_already_installed(path)
    assert fonts._install_xml(path)
    with open(path) as handle:
        text = handle.read()
    required = {fonts._spec_entry(spec) for spec in fonts._REQUIRED_FONTS}
    assert all(required <= found for found in entries(text))
    # Ours come first, right after the include, at its indent.
    assert "<include>Fonts</include>\n        <font>\n            <name>font23_narrow</name>" in text
    # The skin's own entries are kept as they were.
    assert "<name>font32</name>\n            <filename>arial.ttf</filename>\n            <size>30</size>" in text
    assert fonts.fonts_already_installed(path)
    assert not fonts._install_xml(path)                         # nothing left to add


def test_line_endings_are_kept(skin):
    path = skin / "xml" / "Font.xml"
    path.write_bytes(FONT_XML.replace("\n", "\r\n").encode())
    assert fonts._install_xml(str(path))
    data = path.read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")


def test_name_file_and_size_must_come_from_one_entry():
    mixed = ("<font><name>font32</name><filename>other.ttf</filename><size>32</size></font>\n"
             f"<font><name>x</name><filename>{fonts._FONT_FILE}</filename><size>32</size></font>\n")
    assert ("font32", fonts._FONT_FILE, "32") not in fonts._fontset_entries(mixed)
    assert fonts._block_entry("<font><name>a</name></font>") is None


def test_unreadable_files(skin):
    assert not fonts.fonts_already_installed(str(skin / "missing.xml"))
    (skin / "bad.xml").write_bytes(b"\xff\xfe<fonts/>")
    assert not fonts._install_xml(str(skin / "bad.xml"))
    (skin / "empty.xml").write_text("<fonts/>")
    assert not fonts.fonts_already_installed(str(skin / "empty.xml"))


def test_ensure_fonts_installs_once_and_reloads_the_skin(skin, monkeypatch):
    fonts.ensure_fonts()
    assert xbmc.BUILTINS == ["ReloadSkin(reload)"]
    assert home().getProperty(fonts.PROP_FONTS_READY).startswith(xbmc.getSkinDir())
    # The mark holds: no file is read again.
    monkeypatch.setattr(fonts, "_read_font_xml", pytest.fail)
    fonts.ensure_fonts()
    assert xbmc.BUILTINS == ["ReloadSkin(reload)"]


def test_a_complete_skin_is_not_reloaded(skin):
    fonts._install_xml(str(skin / "xml" / "Font.xml"))
    fonts.ensure_fonts()
    assert xbmc.BUILTINS == []
    assert home().getProperty(fonts.PROP_FONTS_READY)


def test_a_replaced_font_xml_is_checked_again(skin):
    fonts.ensure_fonts()
    path = skin / "xml" / "Font.xml"
    path.write_text(FONT_XML + "\n")                    # a skin update
    os.utime(path, (1, 1))
    assert not fonts._settled()
    fonts.ensure_fonts()
    assert fonts.fonts_already_installed(str(path))


def test_another_skin_or_version_lapses_the_mark(skin, monkeypatch):
    fonts.ensure_fonts()
    assert fonts._settled()
    monkeypatch.setattr(xbmc, "getSkinDir", lambda: "skin.other")
    assert not fonts._settled()


def test_an_unwritable_font_xml_is_remembered_as_failed(skin, monkeypatch):
    def refuse(_path, _data):
        raise PermissionError("read-only file system")
    monkeypatch.setattr(fonts, "atomic_write", refuse)
    fonts.ensure_fonts()
    assert xbmc.BUILTINS == []
    assert home().getProperty(fonts.PROP_FONTS_FAILED)
    assert not home().getProperty(fonts.PROP_FONTS_READY)
    monkeypatch.setattr(fonts, "_install_xml", pytest.fail)    # not tried again
    fonts.ensure_fonts()


def test_a_crash_in_the_install_is_logged_and_remembered(skin, monkeypatch):
    def crash(_path):
        raise RuntimeError("parser broke")
    monkeypatch.setattr(fonts, "_install_xml", crash)
    fonts.ensure_fonts()
    assert any("Installation error: parser broke" in line for _level, line in xbmc.LOG)
    assert home().getProperty(fonts.PROP_FONTS_FAILED)


def test_no_font_xml_is_remembered_as_failed(skin):
    os.remove(skin / "xml" / "Font.xml")
    fonts.ensure_fonts()
    skin_dir, _version = home().getProperty(fonts.PROP_FONTS_FAILED).split("\n")
    assert skin_dir == xbmc.getSkinDir()


def test_a_skin_still_loading_is_not_remembered(monkeypatch):
    monkeypatch.setattr(fonts, "_get_skin_path", lambda: None)
    fonts.ensure_fonts()
    assert not home().getProperty(fonts.PROP_FONTS_READY)
    assert not home().getProperty(fonts.PROP_FONTS_FAILED)


def test_a_folder_declared_twice_is_searched_once(skin):
    (skin / "addon.xml").write_text('<addon><res folder="xml" /><res folder="./xml/" /></addon>')
    assert fonts._res_folders(str(skin)) == [str(skin / "xml")]


def test_a_declared_folder_that_is_missing_falls_back_to_the_walk(skin):
    (skin / "addon.xml").write_text('<addon><res folder="1080i" /></addon>')
    assert fonts._font_xml_in(str(skin / "1080i")) is None
    assert fonts._find_font_xmls(str(skin)) == [str(skin / "xml" / "Font.xml")]


def test_a_folder_called_font_xml_is_not_taken_for_the_file(skin):
    (skin / "xml" / "Font.xml").unlink()
    (skin / "xml" / "Font.xml").mkdir()
    (skin / "xml" / "font.xml").write_text(FONT_XML)
    assert fonts._font_xml_in(str(skin / "xml")) == str(skin / "xml" / "font.xml")


def test_the_skin_path_is_where_kodi_loaded_the_skin_from(tmp_path, monkeypatch):
    monkeypatch.setattr(xbmcvfs, "HOME", str(tmp_path))
    assert fonts._get_skin_path() is None                       # not loaded yet
    (tmp_path / "skin").mkdir()
    assert fonts._get_skin_path() == str(tmp_path / "skin")


def test_an_incomplete_font_entry_does_not_count(skin):
    path = skin / "xml" / "Font.xml"
    path.write_text(
        '<fonts><fontset id="Default">\n'
        f"<font><name>font23_narrow</name><filename>{fonts._FONT_FILE}</filename></font>\n"
        f"<font><name>font32</name><filename>{fonts._FONT_FILE}</filename><size>32</size></font>\n"
        "</fontset></fonts>\n")
    assert not fonts.fonts_already_installed(str(path))
    assert fonts._install_xml(str(path))
    [found] = entries(path.read_text())
    assert found == {fonts._spec_entry(spec) for spec in fonts._REQUIRED_FONTS}
    assert path.read_text().count("<name>font32</name>") == 1   # only the missing one was added


def test_a_mark_for_a_vanished_font_xml_is_not_set(tmp_path):
    fonts._remember(home(), xbmc.getSkinDir(), [str(tmp_path / "Font.xml")])
    assert home().getProperty(fonts.PROP_FONTS_READY) == ""
    assert any(level == xbmc.LOGWARNING and "cannot stat Font.xml" in line for level, line in xbmc.LOG)


def test_a_removed_font_xml_lapses_the_mark(skin):
    fonts.ensure_fonts()
    assert fonts._settled()
    os.remove(skin / "xml" / "Font.xml")
    assert not fonts._settled()
    fonts.ensure_fonts()
    assert home().getProperty(fonts.PROP_FONTS_FAILED)


def test_a_launch_waiting_for_another_install_does_not_repeat_it(skin, monkeypatch):
    real_install = fonts._install_fonts

    class OtherCallerFirst:
        """The lock, taken while another caller installs the fonts."""

        def __enter__(self):
            real_install()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(fonts, "_install_lock", OtherCallerFirst())
    monkeypatch.setattr(fonts, "_install_fonts", pytest.fail)
    fonts.ensure_fonts()
    assert xbmc.BUILTINS == ["ReloadSkin(reload)"]              # the other caller's reload only
    assert fonts.fonts_already_installed(str(skin / "xml" / "Font.xml"))
