"""MPEG-1/2/2.5 audio (MP1/MP2/MP3) frame header parsing."""

from ..codecinfo import CodecInfo

_RATES_V1 = (44100, 48000, 32000)


def parse(buf: bytes):
    """Scan for an MPEG audio frame header and parse it."""
    limit = len(buf) - 4
    i = 0
    while i <= limit:
        if buf[i] == 0xFF and (buf[i + 1] & 0xE0) == 0xE0:
            info = _parse_header(buf[i:i + 4])
            if info:
                return info
        i += 1
    return None


def _parse_header(b: bytes):
    version = (b[1] >> 3) & 3        # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
    layer = (b[1] >> 1) & 3          # 3 = I, 2 = II, 1 = III
    if version == 1 or layer == 0:
        return None
    if ((b[2] >> 4) & 0xF) == 0xF:   # bitrate index
        return None
    sr_idx = (b[2] >> 2) & 3
    if sr_idx == 3:
        return None
    if version == 3:
        rate = _RATES_V1[sr_idx]
    elif version == 2:
        rate = _RATES_V1[sr_idx] // 2
    elif version == 0:
        rate = _RATES_V1[sr_idx] // 4
    else:
        return None
    mode = (b[3] >> 6) & 3
    name = {3: "MP1", 2: "MP2", 1: "MP3"}[layer]
    return CodecInfo(name=name, sample_rate=rate,
                     channels=1 if mode == 3 else 2, lfe=False)
