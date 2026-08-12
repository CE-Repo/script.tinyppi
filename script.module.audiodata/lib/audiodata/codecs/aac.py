"""AAC: ADTS frame headers, AudioSpecificConfig and LOAS/LATM StreamMuxConfig."""

from ..bitreader import BitReader
from ..codecinfo import CodecInfo

SAMPLE_RATES = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050,
                16000, 12000, 11025, 8000, 7350)


def _channels_from_config(cfg: int):
    """Return ``(channels, lfe)`` for a channel configuration index."""
    if cfg == 0:
        return None, None            # signalled in-band (PCE)
    if cfg == 7:
        return 8, True               # 7.1
    if cfg == 6:
        return 6, True               # 5.1
    if cfg <= 5:
        return cfg, False
    return None, None


def _object_type_name(aot: int) -> str:
    return {
        1: "AAC Main", 2: "AAC-LC", 3: "AAC SSR", 4: "AAC LTP",
        5: "HE-AAC", 23: "AAC-LD", 29: "HE-AACv2", 39: "AAC-ELD",
    }.get(aot, "AAC")


def parse_asc(data: bytes):
    """Parse an AudioSpecificConfig (Matroska CodecPrivate or an esds DSI)."""
    try:
        return parse_asc_bits(BitReader(data))
    except EOFError:
        return None


def parse_asc_bits(r: BitReader):
    """Parse an AudioSpecificConfig from an already-positioned bit reader."""
    aot = r.read(5)
    if aot == 31:
        aot = 32 + r.read(6)
    sfi = r.read(4)
    if sfi == 15:
        rate = r.read(24)
    elif sfi < len(SAMPLE_RATES):
        rate = SAMPLE_RATES[sfi]
    else:
        return None
    chan_cfg = r.read(4)
    if aot in (5, 29):
        # Explicit SBR signalling: the extension rate is the output rate.
        esfi = r.read(4)
        if esfi == 15:
            rate = r.read(24)
        elif esfi < len(SAMPLE_RATES):
            rate = SAMPLE_RATES[esfi]
        else:
            return None
    channels, lfe = _channels_from_config(chan_cfg)
    return CodecInfo(name=_object_type_name(aot), sample_rate=rate,
                     channels=channels, lfe=lfe)


def parse_adts(buf: bytes):
    """Scan for an ADTS frame header and parse it."""
    limit = len(buf) - 7
    i = 0
    while i <= limit:
        if buf[i] == 0xFF and (buf[i + 1] & 0xF6) == 0xF0:
            profile = (buf[i + 2] >> 6) + 1        # MPEG-4 object type
            sfi = (buf[i + 2] >> 2) & 0xF
            chan_cfg = ((buf[i + 2] & 1) << 2) | (buf[i + 3] >> 6)
            if sfi < len(SAMPLE_RATES):
                channels, lfe = _channels_from_config(chan_cfg)
                return CodecInfo(name=_object_type_name(profile),
                                 sample_rate=SAMPLE_RATES[sfi],
                                 channels=channels, lfe=lfe)
        i += 1
    return None


def parse_loas_latm(buf: bytes):
    """Scan for a LOAS AudioSyncStream and parse the LATM StreamMuxConfig."""
    limit = len(buf) - 8
    i = 0
    while i <= limit:
        if buf[i] == 0x56 and (buf[i + 1] & 0xE0) == 0xE0:
            info = _parse_audio_mux_element(buf[i + 3:])
            if info:
                return info
        i += 1
    return None


def _parse_audio_mux_element(b: bytes):
    try:
        r = BitReader(b)
        if r.read(1) == 1:
            return None              # config not in this element; try the next
        audio_mux_version = r.read(1)
        if audio_mux_version == 1 and r.read(1) == 1:
            return None              # audioMuxVersionA != 0: out of scope
        if audio_mux_version == 1:
            _latm_get_value(r)       # taraBufferFullness
        r.skip(1)                    # allStreamsSameTimeFraming
        r.skip(6)                    # numSubFrames
        r.read(4)                    # numProgram
        r.read(3)                    # numLayer
        if audio_mux_version == 1:
            _latm_get_value(r)       # ascLen -- ignored, the ASC is parsed inline
        return parse_asc_bits(r)
    except EOFError:
        return None


def _latm_get_value(r: BitReader) -> int:
    value = 0
    for _ in range(r.read(2) + 1):
        value = (value << 8) | r.read(8)
    return value
