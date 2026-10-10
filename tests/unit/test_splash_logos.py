# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""What the codec-logo splash shows (ui/splash_logos.py)."""

import pytest

import xbmc
from info import imax
from info.properties import output_hdr_token
from ui import splash_logos as logos


@pytest.mark.parametrize(("gamut", "token"), [
    ("DV-STD BT2020", "dolbyvision"), ("DOLBYVISION", "dolbyvision"), ("dv-ll", "dolbyvision"),
    ("HDR10+ BT2020", "hdr10+"), ("HDR10PLUS", "hdr10+"),
    ("HLG BT2020", "hlg"), ("HDR10 BT2020", "hdr10"), ("HDR", "hdr10"),
    ("SDR BT709", ""), ("", ""), (None, ""),
    ("HDR10, BT2020", "hdr10"), ("DV-STD,BT2020", "dolbyvision"),   # as web/vs10.py cuts it
])
def test_the_output_mode_picks_the_logo_key(gamut, token):
    assert output_hdr_token(gamut) == token


@pytest.mark.parametrize(("source", "gamut", "converting"), [
    ("hdr10", "DV-STD", True),               # HDR10 shown as Dolby Vision
    ("", "DV-LL", True),                     # SDR shown as Dolby Vision
    ("dolbyvision", "SDR BT709", True),      # DV tone-mapped to SDR
    ("hlg", "SDR", True),
    ("dolbyvision", "HDR10 BT2020", True),   # DV as HDR10
    ("", "HDR10 BT2020", True),              # SDR up-converted
    ("dolbyvision", "DV-STD", False),        # passed through
    ("hdr10", "HDR10 BT2020", False),
    ("", "SDR BT709", False),
    ("hlg", "HLG", False),
])
def test_a_conversion_is_told_from_the_output(source, gamut, converting):
    assert logos.is_converting(source, gamut) is converting


@pytest.mark.parametrize(("output", "source", "el_type", "pill"), [
    ("dolbyvision", "dolbyvision", "fel", "fel"),
    ("dolbyvision", "dolbyvision", "MEL", "mel"),
    ("dolbyvision", "dolbyvision", "", "other"),     # profile 5 or 8
    ("dolbyvision", "hdr10", "", "other"),           # converted to DV
    ("hdr10", "dolbyvision", "FEL", ""),             # not DV on the wire
    ("", "dolbyvision", "MEL", ""),
])
def test_the_layer_pill_follows_the_output(output, source, el_type, pill):
    assert logos.dv_layer_token(output, source, el_type) == pill


def test_logos_for_the_output_and_codec(monkeypatch):
    monkeypatch.setattr(logos, "is_known_imax_title", lambda: False)
    xbmc.INFO["VideoPlayer.AudioCodec"] = " TrueHD "
    video, audio = logos.current_logos("dolbyvision")
    assert video == "codecs/Dolby_Vision.png"
    assert audio.endswith(".png") and "true" in audio.lower()
    xbmc.INFO["VideoPlayer.AudioCodec"] = "nonesuch"
    assert logos.current_logos("unknown") == ("codecs/SDR.png", "")


def test_imax_titles_get_the_combined_logo_when_installed(monkeypatch):
    monkeypatch.setattr(logos, "is_known_imax_title", lambda: True)
    monkeypatch.setattr(imax, "_logo_installed", {"codecs/HDR10_IMAX.png": True,
                                                  "codecs/Dolby_Vision_IMAX.png": False})
    assert logos.current_logos("hdr10")[0] == "codecs/HDR10_IMAX.png"
    assert logos.current_logos("dolbyvision")[0] == "codecs/Dolby_Vision.png"   # not installed
    assert logos.current_logos("hlg")[0] == "codecs/HLG.png"                    # no IMAX variant


class Player:
    def __init__(self, streams=None, fail=False):
        self.streams, self.fail = streams or [], fail

    def getAvailableAudioStreams(self):
        if self.fail:
            raise RuntimeError("playback ended")
        return self.streams


def test_audio_is_known_from_the_codec_or_the_player():
    xbmc.INFO["VideoPlayer.AudioCodec"] = "ac3"
    assert logos.video_has_audio(Player())
    xbmc.INFO["VideoPlayer.AudioCodec"] = ""
    assert logos.video_has_audio(Player(["English"]))     # codec not named yet
    assert not logos.video_has_audio(Player())
    assert logos.video_has_audio(Player(fail=True))       # keeps the stack as it is
