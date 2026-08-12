"""Dolby TrueHD / MLP major sync header parsing."""

from ..bitreader import BitReader
from ..codecinfo import CodecInfo

# Channel counts contributed by each bit of the TrueHD (FBA) 13-bit
# 8ch presentation channel assignment field.
_THD_GROUP8_COUNTS = (2, 1, 1, 2, 2, 2, 2, 1, 1, 2, 2, 1, 1)
# ... and of the 5-bit 6ch presentation channel assignment field.
_THD_GROUP6_COUNTS = (2, 1, 1, 2, 2)
_MLP_QUANT_BITS = (16, 20, 24)
# MLP (FBB) 5-bit channel assignment -> channel count.
_MLP_CHANNELS = (1, 2, 3, 4, 3, 4, 5, 3, 4, 5, 4, 5, 6, 4, 5, 4, 5, 6, 5, 5, 6)


def _sample_rate(ratebits: int):
    """Decode a major sync rate code, rejecting reserved and out-of-range ones."""
    if ratebits == 0xF:
        return None
    base = 44100 if ratebits & 8 else 48000
    rate = base << (ratebits & 7)
    return rate if rate <= 192000 else None


def parse(buf: bytes):
    """Scan for an MLP/TrueHD major sync and parse the first valid one.

    The 32-bit sync is followed by the 32-bit format_info and then the constant
    0xB752 signature; requiring that too is what keeps the scan from locking
    onto four bytes of ordinary audio data.
    """
    limit = len(buf) - 12
    i = 0
    while i <= limit:
        if (buf[i] == 0xF8 and buf[i + 1] == 0x72 and buf[i + 2] == 0x6F
                and buf[i + 3] in (0xBA, 0xBB)
                and buf[i + 8] == 0xB7 and buf[i + 9] == 0x52):
            info = _parse_major_sync(buf[i:])
            if info:
                return info
        i += 1
    return None


def _parse_major_sync(b: bytes):
    truehd = b[3] == 0xBA
    try:
        r = BitReader(b)
        r.skip(32)                    # format_sync

        if truehd:
            rate = _sample_rate(r.read(4))
            if rate is None:
                return None
            r.skip(4)                 # 6ch/8ch multichannel type + reserved
            r.skip(2 + 2)             # 2ch / 6ch presentation channel modifiers
            ch6 = r.read(5)
            r.skip(2)                 # 8ch presentation channel modifier
            ch8 = r.read(13)
        else:
            quant1 = r.read(4)
            r.skip(4)                 # group 2 quantization
            rate = _sample_rate(r.read(4))
            if rate is None:
                return None
            r.skip(4)                 # group 2 rate
            r.skip(11)
            assignment = r.read(5)
    except EOFError:
        return None

    if not truehd:
        return CodecInfo(
            name="MLP",
            sample_rate=rate,
            bit_depth=_MLP_QUANT_BITS[quant1] if quant1 < len(_MLP_QUANT_BITS) else None,
            channels=_MLP_CHANNELS[assignment] if assignment < len(_MLP_CHANNELS) else None,
        )

    assignment, counts = (ch8, _THD_GROUP8_COUNTS) if ch8 else (ch6, _THD_GROUP6_COUNTS)
    channels = sum(
        count for bit, count in enumerate(counts) if (assignment >> bit) & 1
    )
    lfe = bool((assignment >> 2) & 1)
    return CodecInfo(
        name="TrueHD",
        sample_rate=rate,
        # TrueHD carries a 24-bit PCM pipeline; the format has no per-stream
        # word length field.
        bit_depth=24,
        channels=channels or None,
        lfe=lfe if channels else None,
    )
