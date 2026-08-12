"""AC-3 (ATSC A/52) and E-AC-3 syncframe header parsing.

Both are lossy, so neither codes a PCM bit depth and none is reported.
"""

from ..bitreader import BitReader
from ..codecinfo import CodecInfo

SYNC = b"\x0b\x77"

_RATES = (48000, 44100, 32000)
_RATES2 = (24000, 22050, 16000)      # E-AC-3 reduced rates (fscod == 3)
_ACMOD_CHANNELS = (2, 1, 2, 3, 3, 4, 4, 5)


def parse(buf: bytes):
    """Scan ``buf`` for an (E-)AC-3 syncword and parse the first plausible frame."""
    limit = len(buf) - 8
    i = 0
    while i <= limit:
        if buf[i] == 0x0B and buf[i + 1] == 0x77:
            info = _parse_frame(buf[i:])
            if info:
                return info
        i += 1
    return None


def _parse_frame(b: bytes):
    try:
        # In both AC-3 and E-AC-3 the 5-bit bsid field sits at bit offset 40.
        probe = BitReader(b)
        probe.skip(40)
        bsid = probe.read(5)

        r = BitReader(b)
        r.skip(16)                    # syncword

        if bsid <= 10:
            # AC-3: crc1(16) fscod(2) frmsizecod(6) bsid(5) bsmod(3) acmod(3) …
            r.skip(16)
            fscod = r.read(2)
            if fscod == 3:
                return None
            if r.read(6) >= 38:       # frmsizecod
                return None
            r.skip(5 + 3)             # bsid, bsmod
            acmod = r.read(3)
            if acmod & 1 and acmod != 1:
                r.skip(2)             # cmixlev
            if acmod & 4:
                r.skip(2)             # surmixlev
            if acmod == 2:
                r.skip(2)             # dsurmod
            lfeon = r.read(1)
            return CodecInfo(
                name="AC-3",
                sample_rate=_RATES[fscod],
                channels=_ACMOD_CHANNELS[acmod] + lfeon,
                lfe=lfeon == 1,
            )

        if 11 <= bsid <= 16:
            # E-AC-3: strmtyp(2) substreamid(3) frmsiz(11) fscod(2)
            #         [fscod2|numblkscod](2) acmod(3) lfeon(1) bsid(5) …
            if r.read(2) == 3:        # strmtyp
                return None
            r.skip(3 + 11)
            fscod = r.read(2)
            if fscod == 3:
                fscod2 = r.read(2)
                if fscod2 == 3:
                    return None
                rate = _RATES2[fscod2]
            else:
                r.skip(2)             # numblkscod
                rate = _RATES[fscod]
            acmod = r.read(3)
            lfeon = r.read(1)
            return CodecInfo(
                name="E-AC-3",
                sample_rate=rate,
                channels=_ACMOD_CHANNELS[acmod] + lfeon,
                lfe=lfeon == 1,
            )
    except EOFError:
        return None
    return None
