# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The overlay's readings, one per row (info/properties.py)."""

import pytest

import xbmc
import xbmcgui
from info import properties


@pytest.mark.parametrize("code, short", [
    ("ger", "DEU"),
    ("unk", "UNK"),
    ("xyz", "XYZ"),
    ("", "UNK"),
])
def test_subtitle_short_code(code, short):
    xbmc.INFO["VideoPlayer.SubtitlesLanguage"] = code
    assert properties.get_SubtitleNameShortVar() == short


@pytest.mark.parametrize("code, short", [
    ("eng", "ENG"),
    ("fre", "FRA"),
    ("chi", "ZHO"),
    ("xyz", "XYZ"),
    ("", "UNK"),
])
def test_audio_short_code(code, short):
    xbmc.INFO["VideoPlayer.AudioCodec"] = "dtshd_ma"
    xbmc.INFO["VideoPlayer.AudioLanguage"] = code
    assert properties.get_AudioNameShortVar() == short


@pytest.mark.parametrize("code, name", [("ger", "Deutsch"), ("abk", "Apsua"), ("xyz", "")])
def test_audio_native_name(code, name):
    xbmc.INFO["VideoPlayer.AudioCodec"] = "dtshd_ma"
    xbmc.INFO["VideoPlayer.AudioLanguage"] = code
    assert properties.get_AudioNameVar() == name


def test_audio_short_code_without_audio():
    assert properties.get_AudioNameShortVar() == ""


def test_untagged_subtitle_event_label():
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


# --- Video rows ---------------------------------------------------------------

def show_channels(hdr_type=""):
    home = xbmcgui.Window(10000)
    home.setProperty("TinyPPI.ShowChannelIcon", "1")
    home.setProperty("TinyPPI.EffectiveHdrType", hdr_type)


@pytest.mark.parametrize("hw, short, long", [(True, "HW", "Hardware"), (False, "SW", "Software")])
def test_the_decoder_mode(hw, short, long):
    xbmc.CONDITIONS["Player.Process(videohwdecoder)"] = hw
    assert properties.get_VideoDecoderVar() == short
    assert properties.get_VideoDecoderLongVar() == long


@pytest.mark.parametrize("raw, shown", [
    ("10-bit, YUV420", "10-bit (YUV 4:2:0)"),
    ("12-bit , yuv422", "12-bit (YUV 4:2:2)"),
    ("10-bit,YUV444", "10-bit (YUV 4:4:4)"),
    ("8-bit, RGB", "8-bit, RGB"),
    ("unknown format", "unknown format"),
    ("   ", ""),
])
def test_the_pixel_format(raw, shown):
    xbmc.INFO["Player.Process(amlogic.pixformat)"] = raw
    assert properties.get_VideoPixelFormatVar() == shown


@pytest.mark.parametrize("raw, shown", [
    ("1080p23.976hz", "1080p 23.976Hz"),
    ("3840x2160p 60Hz", "3840x2160p 60Hz"),
    ("2160i 50.000 HZ", "2160i 50Hz"),
    ("auto", "auto"),
    ("", ""),
])
def test_the_display_mode(raw, shown):
    xbmc.INFO["Player.Process(amlogic.displaymode)"] = raw
    assert properties.get_DisplayModeVar() == shown


def test_the_resolution_needs_width_and_height():
    xbmc.INFO.update({"Player.Process(videowidth)": "3,840",
                      "Player.Process(videoscantype)": "p",
                      "Player.Process(videofps)": "23.976"})
    assert properties.get_VideoResolutionVar() == ""
    xbmc.INFO["Player.Process(videoheight)"] = "2,160"
    assert properties.get_VideoResolutionVar() == "3840x2160p 23.976FPS"


def frame(width="1920", height="1080", dar="1.78"):
    xbmc.INFO.update({"Player.Process(videowidth)": width,
                      "Player.Process(videoheight)": height,
                      "Player.Process(videodar)": dar})


@pytest.mark.parametrize("offsets, shown", [
    ("0 | 0 | 140 | 140", "2.39"),                  # 2.403 snaps to the film ratio
    ("N/A", "1.78"),                                # no bars: Kodi's ratio
    ("0 | 0 | 0 | 0", "1.78"),                      # dvinfo's placeholder outside DV
    ("0 | 0 | 540 | 540", "1.78"),                  # nothing left of the picture
])
def test_the_aspect_ratio_inside_the_bars(offsets, shown):
    frame()
    assert properties.get_AspectRatioVar(offsets) == shown


def test_an_unusual_aspect_ratio_is_shown_as_computed():
    frame(width="1000", height="1000", dar="1.5")
    assert properties.get_AspectRatioVar("0 | 0 | 250 | 250") == "3.00"


def test_all_zero_bars_are_a_real_no_crop_in_dolby_vision():
    frame(dar="1.77")
    assert properties.get_AspectRatioVar("0 | 0 | 0 | 0", is_dv=True) == "1.78"
    assert properties.get_AspectRatioVar("0 | 0 | 0 | 0", is_dv=False) == "1.77"
    xbmcgui.Window(10000).setProperty("TinyPPI.EffectiveHdrType", "dolbyvision")
    assert properties.get_AspectRatioVar("0 | 0 | 0 | 0") == "1.78"


def measured(offsets):
    xbmcgui.Window(10000).setProperty("TinyPPI.MeasuredBars", offsets)


@pytest.mark.parametrize("l5, is_dv, shown", [
    ("N/A", False, "2.39"),                         # no L5: the measured bars
    ("0 | 0 | 0 | 0", False, "2.39"),               # dvinfo's placeholder
    ("0 | 0 | 0 | 0", True, "2.39"),                # Dolby Vision without bars in L5
    ("0 | 0 | 20 | 20", True, "2.39"),              # ahead of the bars L5 declares
])
def test_measured_bars_come_first(l5, is_dv, shown):
    frame()
    measured("0 | 0 | 138 | 138")
    assert properties.get_AspectRatioVar(l5, is_dv=is_dv) == shown


def test_measured_bars_that_leave_no_picture_fall_back_to_kodi():
    frame()
    measured("0 | 0 | 540 | 540")
    assert properties.get_AspectRatioVar("N/A") == "1.78"


# --- The IMAX mark ------------------------------------------------------------

def imax_film(monkeypatch, known=True, widest="2.39", enhanced=False):
    monkeypatch.setattr(properties, "is_known_imax_title", lambda: known)
    monkeypatch.setattr(properties, "is_enhanced_title", lambda: enhanced)
    xbmcgui.Window(10000).setProperty("TinyPPI.WidestAspect", widest)


@pytest.mark.parametrize("canary, l5, known", [
    (True, "N/A", True),                            # measured from the picture
    (True, "0 | 0 | 0 | 0", True),
    (False, "0 | 0 | 276 | 276", True),             # declared by L5
    (False, "0 | 0 | 0 | 0", False),                # often just a missing L5
    (False, "N/A", False),
])
def test_the_framing_is_known_when_measured_or_declared(canary, l5, known):
    xbmcgui.Window(10000).setProperty("TinyPPI.CanMeasure", "1" if canary else "")
    assert properties.is_framing_known(l5) is known


@pytest.mark.parametrize("known, enhanced, shown", [
    (False, True, ""), (True, False, "IMAX"), (True, True, "IMAX Enhanced"),
])
def test_a_film_of_unknown_framing_is_marked_all_through(
        monkeypatch, known, enhanced, shown):
    imax_film(monkeypatch, known=known, enhanced=enhanced)
    assert properties.get_ImaxVar("2.39", False) == shown
    assert properties.get_ImaxVar("1.78", False) == shown


@pytest.mark.parametrize("aspect", ["1.78", "2.39", "1.33"])
def test_an_unknown_framing_is_given_no_format_name(monkeypatch, aspect):
    imax_film(monkeypatch, known=False)
    assert properties.get_AspectFormatVar(aspect, False) == ""


@pytest.mark.parametrize("aspect, scene", [
    ("1.78", True),                                 # the picture opened up
    ("1.90", True),
    ("1.43", True),
    ("2.39", False),                                # the regular framing
    ("2.35", False),                                # a neighbouring ratio is no scene
    ("", False),
])
def test_the_imax_mark_shows_only_during_an_imax_scene(monkeypatch, aspect, scene):
    imax_film(monkeypatch)
    assert properties.is_imax_scene(aspect) is scene
    assert properties.get_ImaxVar(aspect, True) == ("IMAX" if scene else "")


def test_an_imax_enhanced_film_is_marked_as_such(monkeypatch):
    imax_film(monkeypatch, enhanced=True)
    assert properties.get_ImaxVar("1.90", True) == "IMAX Enhanced"
    assert properties.get_ImaxVar("2.39", True) == ""


@pytest.mark.parametrize("widest", ["", "1.90"])
def test_a_film_in_imax_all_through_is_one_imax_scene(monkeypatch, widest):
    imax_film(monkeypatch, widest=widest)           # no other framing shown
    assert properties.get_ImaxVar("1.90", True) == "IMAX"
    assert properties.get_ImaxVar("2.39", True) == ""


def test_a_picture_clearly_taller_than_the_regular_framing_is_a_scene(monkeypatch):
    imax_film(monkeypatch, widest="2.76")
    assert properties.is_imax_scene("2.20") is True
    assert properties.is_imax_scene("2.55") is False


def test_only_an_imax_film_has_imax_scenes(monkeypatch):
    imax_film(monkeypatch, known=False)
    assert properties.get_ImaxVar("1.78", True) == ""


def test_the_regular_framing_of_an_imax_film_is_named_after_its_format(monkeypatch):
    imax_film(monkeypatch)
    assert properties.get_AspectFormatVar("2.39", True) == "Scope"
    assert properties.get_AspectFormatVar("1.78", True) == ""     # the IMAX mark's place


@pytest.mark.parametrize("aspect, shown", [
    ("1.33", "4:3"), ("1.37", "Academy"), ("1.66", "#32492"), ("1.78", "16:9"),
    ("1.85", "#32493"), ("2.00", "Univisium"), ("2.20", "70 mm"), ("2.35", "Scope"),
    ("2.39", "Scope"), ("2.55", "CinemaScope"), ("2.76", "Ultra Panavision"),
    ("1.43", ""), ("1.90", ""),                     # IMAX's own: the IMAX mark's
    ("2.10", ""), ("", ""),                         # no standard ratio, no name
])
def test_a_standard_ratio_is_named_after_its_format(monkeypatch, aspect, shown):
    monkeypatch.setattr(properties, "is_known_imax_title", lambda: False)
    assert properties.get_AspectFormatVar(aspect, True) == shown


@pytest.mark.parametrize("raw, shown", [
    ("25,000", "25 Mb/s"), ("24500", "24.5 Mb/s"), ("", ""), ("n/a", ""),
])
def test_the_video_bitrate(raw, shown):
    xbmc.INFO["VideoPlayer.VideoBitrate"] = raw
    assert properties.get_VideoBitrateMBVar() == shown


@pytest.mark.parametrize("raw, shown", [("12,3 Mb/s", "12.3 Mb/s"), ("", "")])
def test_the_live_video_bitrate(raw, shown):
    xbmc.INFO["Player.Process(videolivebitrate)"] = raw
    assert properties.get_VideoLiveBitrateVar() == shown


@pytest.mark.parametrize("raw, shown", [("AVC1", "H.264"), ("weird", "WEIRD"), (" ", "")])
def test_the_video_codec(raw, shown):
    xbmc.INFO["VideoPlayer.VideoCodec"] = raw
    assert properties.get_VideoCodecVar() == shown


@pytest.mark.parametrize("raw, shown", [
    ("am-h265", "AML-"), ("FF-hevc", "FF-"), ("mediacodec", "MEDIACODEC"), ("", ""),
])
def test_the_decoder_vendor(raw, shown):
    xbmc.INFO["Player.Process(videodecoder)"] = raw
    assert properties.get_VideoDecoderNameVar() == shown


@pytest.mark.parametrize("depth, hdr, shown", [
    ("12", "dolbyvision", "12-bit"),
    ("", "hdr10", "10-bit"),
    ("", "", "8-bit"),
    (None, "hlg", "10-bit"),                        # None: the N/A label
])
def test_the_video_bit_depth(monkeypatch, depth, hdr, shown):
    from info.dvinfo import na_label
    monkeypatch.setattr(properties, "get_bit_depth", lambda: na_label() if depth is None else depth)
    monkeypatch.setattr(properties, "get_hdr_format", lambda: hdr)
    assert properties.get_VideoBitDepthVar() == shown


# --- HDR rows -----------------------------------------------------------------

class SysfsFile:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.text


@pytest.fixture
def sysfs(monkeypatch):
    """Answers reads of the DV mode file; ``mode`` None makes the read fail."""
    from core.memo import KeyedMemo
    state = {"mode": "1", "opened": []}

    def fake_open(path, *args, **kwargs):
        state["opened"].append(path)
        if state["mode"] is None:
            raise OSError("no such file")
        return SysfsFile(state["mode"] + "\n")

    monkeypatch.setattr(properties, "_dovi_tunnel", KeyedMemo())
    monkeypatch.setattr(properties, "open", fake_open, raising=False)
    return state


def test_dv_tunnel_is_read_once_per_pixel_format(sysfs):
    xbmc.INFO["Player.Process(amlogic.pixformat)"] = "8-bit, YUV422"
    assert properties.get_DoviTunnelVar() == "DV Tunnel"
    assert properties.get_DoviTunnelVar() == "DV Tunnel"
    assert sysfs["opened"] == ["/sys/module/aml_media/parameters/dolby_vision_mode"]


def test_dv_tunnel_needs_mode_1_and_8_bit_output(sysfs):
    sysfs["mode"] = "0"
    xbmc.INFO["Player.Process(amlogic.pixformat)"] = "8-bit, YUV422"
    assert properties.get_DoviTunnelVar() == ""
    sysfs["mode"] = "1"
    xbmc.INFO["Player.Process(amlogic.pixformat)"] = "10-bit, YUV420"
    assert properties.get_DoviTunnelVar() == ""
    assert len(sysfs["opened"]) == 1                # 10-bit never reads the file


def test_an_unreadable_dv_mode_is_retried(sysfs):
    sysfs["mode"] = None
    xbmc.INFO["Player.Process(amlogic.pixformat)"] = "8-bit, RGB"
    assert properties.get_DoviTunnelVar() == ""
    sysfs["mode"] = "1"
    assert properties.get_DoviTunnelVar() == "DV Tunnel"
    assert len(sysfs["opened"]) == 2


def test_units_skip_status_labels_and_empty_values():
    from info.dvinfo import na_label
    assert properties.with_unit("1000 | 400", "nits") == "1000 | 400 nits"
    assert properties.with_unit("1000", "") == "1000"
    assert properties.with_unit("", "nits") == ""
    assert properties.with_unit(na_label(), "nits") == na_label()
    assert properties.separated("1000 | 400") == "1000 l 400"


@pytest.mark.parametrize("raw, mode, gamut", [
    ("HDR10 BT2020", "HDR10", "BT2020"), ("SDR", "SDR", ""), ("", "", ""),
])
def test_mode_and_gamut_fields(raw, mode, gamut):
    xbmc.INFO["Player.Process(amlogic.eoft_gamut)"] = raw
    assert (properties.get_ModeVar(), properties.get_GamutVar()) == (mode, gamut)


@pytest.mark.parametrize("raw, token", [
    ("DV-LL", "dolbyvision"), ("HDR10PLUS", "hdr10+"), ("HLG BT2020", "hlg"),
    ("HDR BT2020", "hdr10"), ("SDR BT709", ""), ("", ""), (None, ""),
])
def test_the_output_hdr_token(raw, token):
    assert properties.output_hdr_token(raw) == token


@pytest.mark.parametrize("hdr, mode", [
    ("", "SDR"), ("Dolby Vision", "Dolby Vision"), ("dovi", "Dolby Vision"),
    ("HDR10+", "HDR10+"), ("hdr10plus", "HDR10+"), ("HLG", "HLG"),
    ("HDR10", "HDR10"), ("pq", "HDR10"), ("something", "SDR"),
])
def test_the_output_mode_from_kodi(hdr, mode):
    xbmc.INFO["VideoPlayer.HDRType"] = hdr
    assert properties.output_mode_from_videoplayer() == mode


# --- Audio rows ---------------------------------------------------------------

def audio(codec="truehd_atmos", **labels):
    xbmc.INFO["VideoPlayer.AudioCodec"] = codec
    xbmc.INFO.update(labels)


@pytest.mark.parametrize("raw, shown", [("640", "640 Kb/s"), ("4,608.5", "4.608 Kb/s"), ("x", "")])
def test_the_audio_bitrate(raw, shown):
    audio(**{"VideoPlayer.AudioBitrate": raw})
    assert properties.get_AudioBitrateKBVar() == shown


@pytest.mark.parametrize("raw, shown", [("4,6 Mb/s", "4.6 Mb/s"), ("", "")])
def test_the_live_audio_bitrate(raw, shown):
    audio(**{"Player.Process(audiolivebitrate)": raw})
    assert properties.get_AudioLiveBitrateVar() == shown


@pytest.mark.parametrize("codec, name, spatial", [
    ("truehd_atmos", "Dolby TrueHD", "(Atmos)"),
    ("eac3_ddp_atmos", "Dolby Digital Plus", "(Atmos)"),
    ("dtshd_ma_x_imax", "DTS:X", "(IMAX Enhanced)"),
    ("dtshd_ma", "DTS-HD MA", ""),
    ("madeup", "madeup", ""),                       # unknown codecs as Kodi names them
])
def test_the_audio_codec(codec, name, spatial):
    audio(codec)
    assert properties.get_AudioCodecVar() == name
    assert properties.get_AudioCodecSpatialVar() == spatial


def test_no_audio_codec_reads_na():
    from info.dvinfo import na_label
    assert properties.get_AudioCodecVar() == na_label()
    assert properties.get_AudioCodecSpatialVar() == ""


@pytest.mark.parametrize("channels, layout, speakers", [
    ("8", "7.1", "FL, FR, FC, LFE, BL, BR, SL, SR"),
    ("3", "", "FL, FR, LFE"),                       # no surround name for 3
    ("many", "", None),                              # None: the N/A label
])
def test_the_channel_rows(channels, layout, speakers):
    from info.dvinfo import na_label
    audio("dtshd_ma", **{"VideoPlayer.AudioChannels": channels})
    assert properties.get_AudioChannelsVar() == layout
    assert properties.get_AudioChannelsInputVar() == (speakers or na_label())


def test_unknown_channel_counts_read_na():
    from info.dvinfo import na_label
    audio("dtshd_ma", **{"VideoPlayer.AudioChannels": "42"})
    assert properties.get_AudioChannelsInputVar() == na_label()


@pytest.mark.parametrize("codec, channels, hdr_type, icon", [
    ("truehd_atmos", "8", "", "channels/495x298/7.1.2.png"),
    ("truehd_atmos", "2", "hdr10", "channels/495x298/2.0.png"),  # no height variant
    ("dtshd_ma", "6", "dolbyvision", "channels/400x241/5.1.png"),
    ("dtshd_ma", "12", "", ""),
    ("dtshd_ma", "?", "", ""),
    ("", "6", "", ""),
])
def test_the_channel_graphic(codec, channels, hdr_type, icon):
    show_channels(hdr_type)
    audio(codec, **{"VideoPlayer.AudioChannels": channels})
    assert properties.get_ChannelIconVar() == icon


def test_channel_graphics_off_show_nothing():
    audio("dtshd_ma", **{"VideoPlayer.AudioChannels": "6"})
    assert properties.get_ChannelIconVar() == ""
    assert properties.get_ChannelLayerVar() == ""
    show_channels("dolbyvision")
    assert properties.get_ChannelLayerVar() == "channels/400x241/layer.png"
    show_channels("hlg")
    assert properties.get_ChannelLayerVar() == "channels/495x298/layer.png"


@pytest.mark.parametrize("raw, shown", [("24", "24-bit"), ("0", ""), ("", "")])
def test_the_audio_bit_depth(raw, shown):
    audio(**{"Player.Process(AudioBitsPerSample)": raw})
    assert properties.get_AudioBitDepthVar() == shown


@pytest.mark.parametrize("raw, shown", [
    ("48000", "48 kHz"), ("44,100", "44.1 kHz"), ("0", ""), ("", ""),
])
def test_the_audio_sample_rate(raw, shown):
    audio(**{"Player.Process(AudioSamplerate)": raw})
    assert properties.get_AudioSampleRateVar() == shown


# --- Subtitle rows ------------------------------------------------------------

@pytest.mark.parametrize("code, name", [("ger", "Deutsch"), ("", "")])
def test_the_subtitle_native_name(code, name):
    xbmc.INFO["VideoPlayer.SubtitlesLanguage"] = code
    assert properties.get_SubtitleNameVar() == name


@pytest.mark.parametrize("codec, shown", [("ASS", "ASS"), ("newsub", "NEWSUB"), ("", "")])
def test_the_subtitle_codec(codec, shown):
    xbmc.INFO["VideoPlayer.SubtitleCodec"] = codec
    assert properties.get_SubtitleCodecVar() == shown


# --- System rows --------------------------------------------------------------

@pytest.fixture
def fresh_cores(monkeypatch):
    monkeypatch.setattr(properties, "_last_core_loads", {})


@pytest.mark.parametrize("raw, cores, average, bar", [
    ("#0: 12.5% #1: 8% #2: 15% #3: 10%", "12% | 08% | 15% | 10%", "11%", 11.375),
    ("#0: 1.2.3% #1: 40%", "40%", "40%", 40.0),     # an unreadable core is skipped
    ("#0: nan% #1: nan% #2: nan% #3: nan%", "", "", 0.0),
    ("#0: nan% #1: 30%", "30%", "30%", 30.0),       # never read before: skipped
    ("busy", "", "", 0.0),                          # never the raw text
    ("", "", "", 0.0),
])
def test_the_cpu_load(fresh_cores, raw, cores, average, bar):
    xbmc.INFO["System.CpuUsage"] = raw
    assert properties.get_CpuUsageVar() == cores
    assert properties.get_CpuTopUsageVar() == average
    assert properties.get_CpuTotalProgressVar() == pytest.approx(bar)


def test_a_nan_core_keeps_its_last_load(fresh_cores):
    xbmc.INFO["System.CpuUsage"] = "#0: 25% #1: 40% #2: 33% #3: 34%"
    assert properties.get_CpuUsageVar() == "25% | 40% | 33% | 34%"
    xbmc.INFO["System.CpuUsage"] = "#0: nan% #1: 50% #2: -nan% #3: inf%"
    assert properties.get_CpuUsageVar() == "25% | 50% | 33% | 34%"
    assert properties.get_CpuTopUsageVar() == "36%"


@pytest.mark.parametrize("count, cores", [
    (4, "10% | 11% | 12% | 13%"),
    (5, "10% | 11% | 12% | 13% | 14%"),
    (6, "10 | 11 | 12 | 13 | 14 | 15"),          # more than five: no percent signs
    (7, "10 | 11 | 12 | 13 | 14 | 15 | 16"),
    (8, "10, 11, 12, 13, 14, 15, 16, 17"),      # more than seven: commas
])
def test_more_cores_get_a_tighter_row(fresh_cores, count, cores):
    xbmc.INFO["System.CpuUsage"] = " ".join(f"#{n}: {10 + n}%" for n in range(count))
    assert properties.get_CpuUsageVar() == cores


@pytest.mark.parametrize("raw, percent", [
    ("55 °C", 50.0), ("131 °F", 50.0), ("-5°C", 0.0), ("250 F", 100.0),
    ("hot", 0.0), ("", 0.0),
])
def test_the_cpu_temperature_bar(raw, percent):
    xbmc.INFO["System.CPUTemperature"] = raw
    assert properties.get_CpuTemperatureProgressVar() == pytest.approx(percent)
