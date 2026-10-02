# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The language codes of the audio and subtitle rows."""

import pytest
import xbmc


@pytest.mark.parametrize("code, short", [
    ("ger", "DEU"),
    ("unk", "UNK"),
    ("xyz", "XYZ"),
    ("", "UNK"),
])
def test_subtitle_short_code(code, short):
    from info import properties
    xbmc.INFO["VideoPlayer.SubtitlesLanguage"] = code
    assert properties.get_SubtitleNameShortVar() == short


@pytest.mark.parametrize("code, short", [
    ("eng", "ENG"),
    ("xyz", "XYZ"),
    ("", ""),
])
def test_audio_short_code(code, short):
    from info import properties
    xbmc.INFO["VideoPlayer.AudioLanguage"] = code
    assert properties.get_AudioNameShortVar() == short


def test_untagged_subtitle_event_label():
    from info import properties
    from web.snapshot import subtitle_event_label
    xbmc.INFO["VideoPlayer.SubtitleCodec"] = "hdmv_pgs_subtitle"
    values = {
        "SubtitleNameShortVar": properties.get_SubtitleNameShortVar(),
        "SubtitleNameVar": properties.get_SubtitleNameVar(),
        "SubtitleCodecVar": properties.get_SubtitleCodecVar(),
    }
    assert subtitle_event_label(values) == "UNK (PGS)"
