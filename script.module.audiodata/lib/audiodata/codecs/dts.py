"""DTS core substream and DTS extension substream (DTS-HD) header parsing.

The core is the compatibility layer every DTS decoder can play; on a DTS-HD
track it states 48 kHz while the extension substream stores the real rate, so
the extension wins wherever both are present.  Which extension is present also
names the format: the lossless XLL extension makes it DTS-HD MA, XBR makes it
HRA, LBR on its own makes it DTS Express.
"""

from ..bitreader import BitReader
from ..codecinfo import CodecInfo

CORE_SYNC = b"\x7f\xfe\x80\x01"
EXSS_SYNC = b"\x64\x58\x20\x25"
XLL_SYNC  = b"\x41\xa2\x95\x47"   # lossless extension (DTS-HD MA)
XBR_SYNC  = b"\x65\x5e\x31\x5e"   # extended bitrate (DTS-HD HRA)
LBR_SYNC  = b"\x0a\x80\x19\x21"   # low bitrate (DTS Express)

# SFREQ -> Hz (core substream); 0 marks a reserved index.
_CORE_RATES = (
    0, 8000, 16000, 32000, 0, 0, 11025, 22050,
    44100, 0, 0, 12000, 24000, 48000, 0, 0,
)
# nuMaxSampleRate -> Hz (extension substream).  A wider table than the core's:
# naming a rate the core cannot is the point of reading the extension.
_EXSS_RATES = (
    8000, 16000, 32000, 64000, 128000, 22050, 44100, 88200,
    176400, 352800, 12000, 24000, 48000, 96000, 192000, 384000,
)
# AMODE -> channel count (core substream)
_AMODE_CHANNELS = (1, 2, 2, 2, 2, 3, 3, 4, 4, 5, 6, 6, 6, 7, 8, 8)
# PCMR -> source resolution in bits (0 = invalid)
_PCMR_BITS = (16, 16, 20, 20, 0, 24, 24, 0)


def parse(buf: bytes):
    """Return a CodecInfo for the first DTS frame in ``buf``, or None."""
    core_at = buf.find(CORE_SYNC)
    core = _parse_core(buf[core_at:]) if core_at != -1 else None
    exss_at = buf.find(EXSS_SYNC)
    exss = _parse_exss(buf[exss_at:]) if exss_at != -1 else None

    if core is None and exss_at == -1:
        return None

    xll = XLL_SYNC in buf
    xbr = XBR_SYNC in buf
    lbr = LBR_SYNC in buf

    if xll:
        name = "DTS-HD MA"
    elif xbr:
        name = "DTS-HD HRA"
    elif lbr and core is None:
        name = "DTS Express"
    elif exss_at != -1:
        name = "DTS-HD"
    else:
        ext_id = core.get("ext_audio_id") if core else None
        if ext_id in (0, 3):
            name = "DTS-ES"          # XCH / XXCH
        elif ext_id == 2:
            name = "DTS 96/24"       # X96
        else:
            name = "DTS"

    info = CodecInfo(name=name)
    if core:
        info.sample_rate = core["rate"]
        info.bit_depth = core["depth"]
        info.channels = core["channels"] + (1 if core["lfe"] else 0)
        info.lfe = core["lfe"]
    if exss:
        # The extension substream asset header describes the full (max)
        # quality of the track, so it wins over the core values.
        if exss["rate"] is not None:
            info.sample_rate = exss["rate"]
        if exss["depth"] is not None:
            info.bit_depth = exss["depth"]
        channels = exss["channels"]
        if channels is not None and channels >= (info.channels or 0):
            info.channels = channels
            if info.lfe is None:
                # Almost always 5.1 and 7.1 respectively.
                info.lfe = True if channels in (6, 8) else None
    return info


def _parse_core(b: bytes):
    """Parse a core substream header, or return None."""
    try:
        r = BitReader(b)
        r.skip(32)                    # sync
        r.skip(1 + 5)                 # FTYPE, SHORT
        cpf = r.read(1)
        nblks = r.read(7)
        if nblks < 5:
            return None
        fsize = r.read(14)
        if fsize < 95:
            return None
        amode = r.read(6)
        sfreq = r.read(4)
        rate = _CORE_RATES[sfreq]
        if not rate:
            return None
        r.skip(5)                     # RATE
        r.skip(1 + 1 + 1 + 1 + 1)     # MIX, DYNF, TIMEF, AUXF, HDCD
        ext_audio_id = r.read(3)
        ext_audio = r.read(1)
        r.skip(1)                     # ASPF
        lff = r.read(2)
        r.skip(1)                     # HFLAG
        if cpf == 1:
            r.skip(16)                # HCRC
        r.skip(1 + 4 + 2)             # FILTS, VERNUM, CHIST
        pcmr = r.read(3)
    except EOFError:
        return None

    if amode >= 16:
        return None                   # user-defined layouts
    depth = _PCMR_BITS[pcmr] or None

    return {
        "rate": rate,
        "depth": depth,
        "channels": _AMODE_CHANNELS[amode],
        "lfe": lff in (1, 2),
        "ext_audio_id": ext_audio_id if ext_audio == 1 else None,
    }


def _parse_exss(b: bytes):
    """Parse the extension substream header up to the first asset descriptor,
    which carries bit resolution, max sample rate and total channel count."""
    try:
        r = BitReader(b)
        r.skip(32)                    # sync
        r.skip(8)                     # UserDefinedBits
        exss_index = r.read(2)
        header_size_type = r.read(1)
        bits4hdr, bits4fs = (8, 16) if header_size_type == 0 else (12, 20)
        r.skip(bits4hdr)              # nuExtSSHeaderSize
        r.skip(bits4fs)               # nuExtSSFsize
        if r.read(1) == 0:
            return None               # asset metadata absent; nothing to read
        r.skip(2 + 3)                 # nuRefClockCode, nuExSSFrameDurationCode
        if r.read(1) == 1:
            r.skip(36)                # timestamp
        num_presentations = r.read(3) + 1
        num_assets = r.read(3) + 1

        masks = [r.read(exss_index + 1) for _ in range(num_presentations)]
        for mask in masks:
            for bit in range(exss_index + 1):
                if (mask >> bit) & 1:
                    r.skip(8)

        if r.read(1) == 1:            # mixing metadata
            r.skip(2)                 # nuMixMetadataAdjLevel
            bits4mask = (r.read(2) + 1) * 4
            for _ in range(r.read(2) + 1):
                r.skip(bits4mask)

        for _ in range(num_assets):
            r.skip(bits4fs)           # nuAssetFsize

        # First asset descriptor.
        r.skip(9)                     # nuAssetDescriptFsize
        r.skip(3)                     # nuAssetIndex
        if r.read(1) == 1:
            r.skip(4)                 # nuAssetTypeDescriptor
        if r.read(1) == 1:
            r.skip(24)                # language descriptor
        if r.read(1) == 1:
            r.skip((r.read(10) + 1) * 8)   # info text
        bit_res = r.read(5) + 1
        rate_code = r.read(4)
        channels = r.read(6) + 1
    except EOFError:
        return None

    return {
        "rate": _EXSS_RATES[rate_code],
        "depth": bit_res,
        "channels": channels,
    }
