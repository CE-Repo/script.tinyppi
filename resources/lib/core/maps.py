# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Static lookup tables keyed on the lowercase codec or language id from Kodi."""

import json
import os

# Video codec map (VideoPlayer.VideoCodec -> display label)
VIDEO_CODEC_MAP = {
    "3iv2":       "3ivx",
    "av1":        "AV1",
    "avc1":       "H.264",
    "div2":       "DivX",
    "div3":       "DivX",
    "divx":       "DivX",
    "divx 4":     "DivX",
    "dx50":       "DivX",
    "flv":        "FLV",
    "h264":       "H.264",
    "hev1":       "H.265",
    "hevc":       "H.265",
    "hvc1":       "H.265",
    "microsoft":  "Microsoft Video",
    "mp42":       "MS MPEG-4 v2",
    "mp43":       "MS MPEG-4 v3",
    "mp4v":       "MPEG-4",
    "mpeg1":      "MPEG-1",
    "mpeg1video": "MPEG-1",
    "mpeg2":      "MPEG-2",
    "mpeg2video": "MPEG-2",
    "mpeg4":      "MPEG-4",
    "mpg4":       "MPEG-4",
    "rv40":       "RealVideo 9/10",
    "svq1":       "Sorenson Video 1",
    "svq3":       "Sorenson Video 3",
    "theora":     "Theora",
    "vc-1":       "VC-1",
    "vc1":        "VC-1",
    "vp6f":       "On2 VP6",
    "vp8":        "VP8",
    "vp9":        "VP9",
    "wmv":        "WMV",
    "wmv2":       "WMV 8",
    "wmv3":       "WMV 9",
    "wvc1":       "VC-1",
    "xvid":       "XviD",
}

# Subtitle codec map (VideoPlayer.SubtitleCodec -> display label)
SUBTITLE_CODEC_MAP = {
    "ass":               "ASS",
    "dvb_subtitle":      "DVB-SUB",
    "dvb_teletext":      "DVB-Text",
    "dvd_subtitle":      "VobSub",
    "hdmv_pgs_subtitle": "PGS",
    "microdvd":          "MicroDVD",
    "mov_text":          "Timed Text",
    "mpl2":              "MPL2",
    "realtext":          "RealText",
    "sami":              "SAMI",
    "srt":               "SubRip",
    "ssa":               "SSA",
    "subrip":            "SubRip",
    "text":              "Text",
    "ttml":              "TTML",
    "vplayer":           "VPlayer",
    "webvtt":            "WebVTT",
    "xsub":              "XSUB",
}

# Audio codec map (VideoPlayer.AudioCodec -> display label)
AUDIO_CODEC_MAP = {
    # AAC
    "aac":             "AAC",
    "aac_latm":        "AAC",
    "aac_lc":          "AAC-LC",
    "he_aac":          "HE-AAC",
    "he_aac_v2":       "HE-AAC v2",
    "aac_ssr":         "AAC-SSR",
    "aac_ltp":         "AAC-LTP",

    # Dolby
    "ac3":             "Dolby Digital",
    "dolbydigital":    "Dolby Digital",
    "eac3":            "Dolby Digital Plus",
    "eac3_ddp_atmos":  "Dolby Digital Plus",
    "truehd":          "Dolby TrueHD",
    "truehd_atmos":    "Dolby TrueHD",

    # DTS
    "dca":             "DTS",
    "dts":             "DTS",
    "dts_96_24":       "DTS 96/24",
    "dts_es":          "DTS-ES",
    "dts_express":     "DTS Express",
    "dtshd":           "DTS-HD",
    "dtshd_ma":        "DTS-HD MA",
    "dtshd_hra":       "DTS-HD HRA",
    "dtshd_ma_x":      "DTS:X",
    "dtshd_ma_x_imax": "DTS:X",

    # Lossless / PCM
    "alac":            "ALAC",
    "flac":            "FLAC",
    "pcm":             "PCM",
    "pcm_bluray":      "LPCM",
    "pcm_s16le":       "PCM",
    "pcm_s24le":       "PCM",
    "wav":             "WAV",
    "wavpack":         "WavPack",

    # Compressed
    "ape":             "Monkey's Audio (APE)",
    "mp1":             "MP1",
    "mp2":             "MP2",
    "mp3":             "MP3",
    "mp3float":        "MP3",
    "ogg":             "Ogg Vorbis",
    "opus":            "Opus",
    "vorbis":          "Vorbis",
    "wmapro":          "WMA Pro",
    "wmav2":           "WMA",

    # Misc
    "aif":             "AIFF",
    "aifc":            "AIFF-C",
    "aiff":            "AIFF",
    "avc":             "AVC",
    "cdda":            "CD Audio",
}

# Audio codec -> splash logo (codecs/*.png in the skin's media folder).
# Unmapped codecs show no audio logo.
AUDIO_LOGO_MAP = {
    # AAC
    "aac":             "codecs/AAC.png",
    "aac_latm":        "codecs/AAC_LATM.png",
    "aac_lc":          "codecs/AAC-LC.png",
    "he_aac":          "codecs/HE-AAC.png",
    "he_aac_v2":       "codecs/HE_AAC_v2.png",
    "aac_ssr":         "codecs/AAC_SSR.png",
    "aac_ltp":         "codecs/AAC_LTP.png",

    # Dolby
    "ac3":             "codecs/Dolby_Digital.png",
    "dolbydigital":    "codecs/Dolby_Digital.png",
    "eac3":            "codecs/Dolby_Digital_Plus.png",
    "eac3_ddp_atmos":  "codecs/Dolby_Digital_Plus_Atmos.png",
    "truehd":          "codecs/Dolby_TrueHD.png",
    "truehd_atmos":    "codecs/Dolby_TrueHD_Atmos.png",

    # DTS
    "dca":             "codecs/DTS.png",
    "dts":             "codecs/DTS.png",
    "dts_96_24":       "codecs/DTS-96-24.png",
    "dts_es":          "codecs/DTS-ES.png",
    "dts_express":     "codecs/DTS-Express.png",
    "dtshd":           "codecs/DTS-HD-MA.png",
    "dtshd_ma":        "codecs/DTS-HD-MA.png",
    "dtshd_hra":       "codecs/DTS-HD-HRA.png",
    "dtshd_ma_x":      "codecs/DTSX.png",
    "dtshd_ma_x_imax": "codecs/IMAX.png",

    # Lossless / PCM
    "flac":            "codecs/FLAC.png",
    "pcm":             "codecs/PCM.png",
    "pcm_bluray":      "codecs/PCM.png",
    "pcm_s16le":       "codecs/PCM.png",
    "pcm_s24le":       "codecs/PCM.png",

    # Compressed
    "mp1":             "codecs/MP1.png",
    "mp2":             "codecs/MP2.png",
    "mp3":             "codecs/MP3.png",
    "mp3float":        "codecs/MP3.png",
    "ogg":             "codecs/OGG.png",
    "opus":            "codecs/OPUS.png",
    "vorbis":          "codecs/VORBIS.png",
}

# HDR type -> splash logo (codecs/*.png).  The empty string maps to the SDR
# logo, so every video gets a video logo.
HDR_LOGO_MAP = {
    "":            "codecs/SDR.png",
    "hdr10":       "codecs/HDR10.png",
    "hdr10+":      "codecs/HDR10Plus.png",
    "hlg":         "codecs/HLG.png",
    "dolbyvision": "codecs/Dolby_Vision.png",
}

# Replacements for the logos above while IMAX material plays (see
# ui.splash_logos.current_logos, which falls back to the plain logo when one is
# not installed).  HLG and SDR have no IMAX variant.
IMAX_LOGO_MAP = {
    "hdr10":       "codecs/HDR10_IMAX.png",
    "hdr10+":      "codecs/HDR10Plus_IMAX.png",
    "dolbyvision": "codecs/Dolby_Vision_IMAX.png",
}

# Channel count -> surround layout string
CHANNELS_MAP = {
    1:  "1.0",
    2:  "2.0",
    4:  "4.0",
    5:  "5.0",
    6:  "5.1",
    7:  "6.1",
    8:  "7.1",
    10: "9.1",
}

# Channel count -> full speaker-label string
CHANNELS_INPUT_MAP = {
    1:  "Mono",
    2:  "FL, FR",
    3:  "FL, FR, LFE",
    4:  "FL, FR, BL, BR",
    5:  "FL, FR, LFE, BL, BR",
    6:  "FL, FR, FC, LFE, SL, SR",
    7:  "FL, FR, FC, LFE, BC, SL, SR",
    8:  "FL, FR, FC, LFE, BL, BR, SL, SR",
    9:  "FL, FR, FC, LFE, BL, BR, SL, SR, FWL",
    10: "FL, FR, FC, LFE, BL, BR, SL, SR, FWL, FWR",
}

# Channel count -> speaker-layout graphic in the channels/<box>/ folder
# chosen by properties.py.  Unmapped counts show no graphic.
CHANNELS_ICON_MAP = {
    1: "1.0",
    2: "2.0",
    3: "2.1",
    4: "3.1",
    5: "4.1",
    6: "5.1",
    7: "6.1",
    8: "7.1",
}

# Codecs with height channels: the Atmos and DTS:X families (IMAX Enhanced is
# DTS:X based).  Kodi reports only the channel count, so height speakers are
# inferred from the codec.
HEIGHT_CHANNEL_CODECS = frozenset({
    "eac3_ddp_atmos",
    "truehd_atmos",
    "dtshd_ma_x",
    "dtshd_ma_x_imax",
})

# Channel count -> speaker-layout graphic for the codecs above.
CHANNELS_ICON_HEIGHT_MAP = {
    6: "5.1.2",
    8: "7.1.2",
}

# ISO 639-2/B language code -> native language name.  Nearly 500 entries of
# pure data, so they live in resources/data rather than here.
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

with open(os.path.join(_DATA_DIR, "languages.json"), encoding="utf-8") as _file:
    LANGUAGE_MAP: dict[str, str] = json.load(_file)

# ISO 639-2/B language code -> ISO 639-2/T code (uppercase), where they
# differ.  Every other code reads as itself, uppercased.
LANGUAGE_MAP_SHORT = {
    "alb": "SQI",
    "arm": "HYE",
    "baq": "EUS",
    "bur": "MYA",
    "chi": "ZHO",
    "cze": "CES",
    "dut": "NLD",
    "fre": "FRA",
    "geo": "KAT",
    "ger": "DEU",
    "gre": "ELL",
    "ice": "ISL",
    "mac": "MKD",
    "may": "MSA",
    "mao": "MRI",
    "per": "FAS",
    "rum": "RON",
    "slo": "SLK",
    "tib": "BOD",
    "wel": "CYM",
}
