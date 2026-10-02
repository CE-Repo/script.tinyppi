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
    ("", "UNK"),
])
def test_audio_short_code(code, short):
    from info import properties
    xbmc.INFO["VideoPlayer.AudioCodec"] = "dtshd_ma"
    xbmc.INFO["VideoPlayer.AudioLanguage"] = code
    assert properties.get_AudioNameShortVar() == short


def test_audio_short_code_without_audio():
    from info import properties
    assert properties.get_AudioNameShortVar() == ""


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


def test_audio_rows_without_codec_read_na():
    """Channels and bitrates Kodi still reports are not shown without a codec."""
    from info import properties
    from info.dvinfo import na_label
    xbmc.INFO.update({
        "VideoPlayer.AudioChannels": "2",
        "VideoPlayer.AudioBitrate": "1536",
        "Player.Process(audiolivebitrate)": "1.536 Kb/s",
        "Player.Process(AudioBitsPerSample)": "24",
        "Player.Process(AudioSamplerate)": "48000",
        "VideoPlayer.AudioLanguage": "eng",
    })
    assert properties.get_AudioChannelsInputVar() == na_label()
    for getter in (properties.get_AudioChannelsVar,
                   properties.get_AudioBitrateKBVar,
                   properties.get_AudioLiveBitrateVar,
                   properties.get_AudioBitDepthVar,
                   properties.get_AudioSampleRateVar,
                   properties.get_AudioNameVar,
                   properties.get_AudioNameShortVar):
        assert getter() == "", getter.__name__

    xbmc.INFO["VideoPlayer.AudioCodec"] = "dtshd_ma"
    xbmc.INFO["VideoPlayer.AudioChannels"] = "6"
    assert properties.get_AudioChannelsInputVar() == "FL, FR, FC, LFE, SL, SR"
    assert properties.get_AudioBitrateKBVar() == "1.536 Kb/s"
