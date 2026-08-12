"""Audio bitstream header parsers.

Each parser takes a buffer positioned at (or containing) a frame and returns
what the *source* stream declares about itself -- the sample rate and, where
the format codes one, the PCM bit resolution.  These are the values a player
cannot report while it is passing the bitstream through untouched, and the ones
a decoder only reveals after it has decoded: a DTS-HD track carries a 48 kHz
core for compatibility and states its real 96 kHz rate in the extension
substream, which is what makes reading the bitstream worthwhile at all.

Field layouts follow FFmpeg's own parsers (``dca_exss.c``, ``dca_parser.c``,
``mlp_parser.c``, ``ac3_parser.c``) so the numbers line up with what every
other tool reports for the same stream.

Every parser returns ``None`` rather than raising when the buffer does not
hold a header it can trust.  A 32-bit sync word matches random data once every
few gigabytes, so each parser also range-checks what it read: a header that
parses but describes something impossible is treated as a false positive.
"""

from .bitreader import BitReader

# --- DTS -------------------------------------------------------------------

SYNC_DTS_CORE = b"\x7f\xfe\x80\x01"
SYNC_DTS_EXSS = b"\x64\x58\x20\x25"

# Core sample rates by SFREQ index (FFmpeg's ff_dca_core_sample_rates); the
# reserved entries are 0 and reject the header.
_DTS_CORE_RATES = (
    0, 8000, 16000, 32000, 0, 0, 11025, 22050,
    44100, 0, 0, 12000, 24000, 48000, 0, 0,
)

# Extension-substream sample rates by index (FFmpeg's ff_dca_sampling_freqs).
# This is a different, wider table than the core's -- the whole point of
# reading the extension is that it can name a rate the core cannot.
_DTS_EXSS_RATES = (
    8000, 16000, 32000, 64000, 128000, 22050, 44100, 88200,
    176400, 352800, 12000, 24000, 48000, 96000, 192000, 384000,
)


def parse_dts_core(data: bytes) -> dict | None:
    """Return ``{'sample_rate': ...}`` from a DTS core frame header.

    The core is the compatibility layer: on a DTS-HD track its rate is the one
    a player without the extension would play, so it is only used when no
    extension substream is found.
    """
    if not data.startswith(SYNC_DTS_CORE):
        return None

    try:
        reader = BitReader(data, start_bit=32)
        reader.skip(1)                 # FTYPE, frame type
        reader.skip(5)                 # SHORT, deficit sample count
        reader.skip(1)                 # CPF, CRC present
        nblks = reader.read(7)         # NBLKS, blocks in frame
        fsize = reader.read(14)        # FSIZE, primary frame byte size - 1
        reader.skip(6)                 # AMODE, channel arrangement
        sfreq = reader.read(4)         # SFREQ, core sample rate index
    except EOFError:
        return None

    rate = _DTS_CORE_RATES[sfreq]
    # A real core frame carries at least 6 blocks and a sane frame size; the
    # reserved rate indices are 0.  Any of these means we matched noise.
    if not rate or nblks < 5 or fsize < 95:
        return None

    return {"sample_rate": rate}


def parse_dts_exss(data: bytes) -> dict | None:
    """Return ``{'sample_rate': ..., 'bit_depth': ..., 'channels': ...}`` from a
    DTS extension substream header.

    This is the reading that matters: the asset descriptor states the maximum
    sample rate and the PCM bit resolution of the *extension*, i.e. of the
    lossless or high-resolution audio actually stored, rather than of the core
    every DTS decoder can fall back to.

    Only the first asset is read.  The layout follows FFmpeg's
    ``ff_dca_exss_parse`` plus its ``parse_descriptor``.
    """
    if not data.startswith(SYNC_DTS_EXSS):
        return None

    try:
        reader = BitReader(data, start_bit=32)
        reader.skip(8)                        # user defined bits
        exss_index = reader.read(2)           # extension substream index
        long_header = reader.read_bool()      # header size type
        header_bits, size_bits = (12, 20) if long_header else (8, 16)
        header_size = reader.read(header_bits) + 1
        exss_size = reader.read(size_bits) + 1

        static_fields = reader.read_bool()
        if static_fields:
            reader.skip(2)                    # reference clock code
            reader.skip(3)                    # frame duration code
            if reader.read_bool():            # timecode present
                reader.skip(36)
            npresents = reader.read(3) + 1
            nassets = reader.read(3) + 1

            # Active substream mask per presentation, then an active asset
            # mask byte for every substream a presentation switches on.
            masks = [reader.read(exss_index + 1) for _ in range(npresents)]
            for mask in masks:
                for bit in range(exss_index + 1):
                    if mask & (1 << bit):
                        reader.skip(8)

            if reader.read_bool():            # mixing metadata present
                reader.skip(2)                # adjustment level
                spkr_mask_bits = (reader.read(2) + 1) << 2
                nmixconfigs = reader.read(2) + 1
                for _ in range(nmixconfigs):
                    reader.skip(spkr_mask_bits)
        else:
            nassets = 1

        # Encoded size of each asset, then the descriptors themselves.
        for _ in range(nassets):
            reader.skip(20)

        # First asset descriptor.
        reader.skip(9)                        # descriptor byte size - 1
        reader.skip(3)                        # asset index
        if not static_fields:
            # Without the static fields the descriptor carries no rate or
            # resolution, so there is nothing here worth reporting.
            return None

        if reader.read_bool():                # asset type descriptor present
            reader.skip(4)
        if reader.read_bool():                # language descriptor present
            reader.skip(24)
        if reader.read_bool():                # additional textual info present
            text_size = reader.read(10) + 1
            reader.skip(text_size * 8)

        bit_depth = reader.read(5) + 1        # PCM bit resolution
        rate_index = reader.read(4)           # maximum sample rate
        channels = reader.read(8) + 1         # total number of channels
    except EOFError:
        return None

    if header_size < 10 or exss_size < header_size:
        return None
    if bit_depth not in (16, 20, 24, 32) or channels > 32:
        return None

    return {
        "sample_rate": _DTS_EXSS_RATES[rate_index],
        "bit_depth": bit_depth,
        "channels": channels,
    }


def parse_dts(data: bytes) -> dict | None:
    """Return what a DTS buffer declares, preferring the extension substream.

    A DTS-HD frame is a core frame followed by its extension substream (or, for
    a substream-only stream, the extension alone).  The extension is
    authoritative wherever it exists, so it is looked for first and the core is
    only consulted for a plain DTS track.
    """
    exss_at = data.find(SYNC_DTS_EXSS)
    while exss_at != -1:
        parsed = parse_dts_exss(data[exss_at:])
        if parsed:
            return parsed
        exss_at = data.find(SYNC_DTS_EXSS, exss_at + 4)

    core_at = data.find(SYNC_DTS_CORE)
    while core_at != -1:
        parsed = parse_dts_core(data[core_at:])
        if parsed:
            return parsed
        core_at = data.find(SYNC_DTS_CORE, core_at + 4)

    return None


# --- TrueHD / MLP ----------------------------------------------------------

SYNC_TRUEHD = b"\xf8\x72\x6f\xba"
SYNC_MLP    = b"\xf8\x72\x6f\xbb"

# MLP quantization codes to bit depths (FFmpeg's ff_mlp_quant_to_bits).
_MLP_QUANT_BITS = (16, 20, 24, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def _mlp_sample_rate(code: int) -> int:
    """Decode an MLP/TrueHD sample-rate code (FFmpeg's ``ff_mlp_samplerate``)."""
    if code == 0xF:
        return 0
    return (44100 if code & 8 else 48000) << (code & 7)


def parse_truehd(data: bytes) -> dict | None:
    """Return ``{'sample_rate': ..., 'bit_depth': ...}`` from a TrueHD or MLP
    major sync header.

    TrueHD does not code a bit depth anywhere in its sync header -- FFmpeg
    hardcodes 24 for the same reason -- so that is what is reported for it.
    MLP does carry one, per substream group, and its first group is used.
    """
    if data.startswith(SYNC_TRUEHD):
        stream_type = 0xBA
    elif data.startswith(SYNC_MLP):
        stream_type = 0xBB
    else:
        return None

    try:
        reader = BitReader(data, start_bit=32)
        if stream_type == 0xBB:
            bit_depth = _MLP_QUANT_BITS[reader.read(4)]
            reader.skip(4)                    # group 2 quantization
            rate = _mlp_sample_rate(reader.read(4))
        else:
            bit_depth = 24                    # not conveyed by the bitstream
            rate = _mlp_sample_rate(reader.read(4))
    except EOFError:
        return None

    if not rate or not bit_depth:
        return None

    return {"sample_rate": rate, "bit_depth": bit_depth}


# --- FLAC ------------------------------------------------------------------

MAGIC_FLAC = b"fLaC"


def parse_flac_streaminfo(data: bytes) -> dict | None:
    """Return ``{'sample_rate': ..., 'bit_depth': ..., 'channels': ...}`` from a
    FLAC STREAMINFO block, with or without the leading ``fLaC`` magic.

    In Matroska this arrives as the track's private data rather than in the
    frames, which is why it is parsed from a standalone buffer.
    """
    if data.startswith(MAGIC_FLAC):
        data = data[4:]
    if len(data) < 38:
        return None

    block_type = data[0] & 0x7F
    if block_type != 0:                       # STREAMINFO
        return None

    try:
        reader = BitReader(data, start_bit=32)  # skip the metadata block header
        reader.skip(16 + 16 + 24 + 24)        # block and frame size bounds
        rate = reader.read(20)
        channels = reader.read(3) + 1
        bit_depth = reader.read(5) + 1
    except EOFError:
        return None

    if not rate or rate > 655350:
        return None

    return {"sample_rate": rate, "bit_depth": bit_depth, "channels": channels}


# --- AC-3 / E-AC-3 ---------------------------------------------------------

SYNC_AC3 = b"\x0b\x77"

_AC3_RATES      = (48000, 44100, 32000, 0)
_EAC3_RATES_HALF = (24000, 22050, 16000, 0)


def parse_ac3(data: bytes) -> dict | None:
    """Return ``{'sample_rate': ...}`` from an AC-3 or E-AC-3 sync frame.

    Both are lossy, so neither codes a PCM bit depth and none is reported.
    Included because a stream can carry nothing else, and a rate read from the
    bitstream still beats guessing.
    """
    if not data.startswith(SYNC_AC3):
        return None

    try:
        reader = BitReader(data, start_bit=16)
        bsid_reader = BitReader(data, start_bit=40)
        bsid = bsid_reader.read(5)

        if bsid <= 10:                        # AC-3
            reader.skip(16)                   # crc1
            rate = _AC3_RATES[reader.read(2)]
            # frmsizecod indexes a 38-entry table; beyond that the header is
            # not one.  Worth checking because the sync word is only 16 bits
            # wide and turns up in ordinary data on its own.
            if reader.read(6) > 37:
                return None
        elif bsid <= 16:                      # E-AC-3
            reader.skip(2)                    # stream type
            reader.skip(3)                    # substream id
            reader.skip(11)                   # frame size code
            fscod = reader.read(2)
            if fscod == 3:
                rate = _EAC3_RATES_HALF[reader.read(2)]
            else:
                rate = _AC3_RATES[fscod]
        else:
            return None
    except EOFError:
        return None

    return {"sample_rate": rate} if rate else None


# --- Dispatch --------------------------------------------------------------

# Codec family -> (sync words, parser).  The family names match what the
# consumer normalises the player's own codec names to.  Order matters: a frame
# is offered to each in turn and the first that validates wins, so the formats
# with a 32-bit sync word are tried before the one with a 16-bit one.
_FAMILY_PARSERS = (
    ("dts",    (SYNC_DTS_EXSS, SYNC_DTS_CORE), parse_dts),
    ("truehd", (SYNC_TRUEHD,),                 parse_truehd),
    ("mlp",    (SYNC_MLP,),                    parse_truehd),
    ("ac3",    (SYNC_AC3,),                    parse_ac3),
)

# Families the blind scan looks for.  AC-3 is deliberately absent: its sync
# word is 16 bits, which turns up roughly every 64 KiB of arbitrary data, and
# no amount of range-checking the rest of the header makes that reliable when
# there is no track boundary to anchor it to.  Nothing is lost by leaving it
# out -- AC-3 and E-AC-3 are lossy, so they code no PCM bit depth, and their
# sample rate is whatever the container already says it is.  The formats that
# are scanned for are exactly the ones whose container header can be wrong.
_SCANNED_FAMILIES = ("dts", "truehd", "mlp")


def parse_frame(data: bytes) -> dict | None:
    """Return what the first recognised header in ``data`` declares, or None."""
    for _family, syncs, parser in _FAMILY_PARSERS:
        for sync in syncs:
            at = data.find(sync)
            while at != -1:
                parsed = parser(data[at:])
                if parsed:
                    return parsed
                at = data.find(sync, at + len(sync))
    return None


def scan_families(data: bytes) -> dict[str, dict]:
    """Return ``{family: reading}`` for every codec family found in ``data``.

    Used for containers whose track table is not parsed: a stream is scanned
    for the sync words themselves, which finds the headers wherever the
    container happened to put them.  The first header of a family that both
    parses and range-checks wins, so a false positive on random data has to
    survive the parser's own plausibility checks to get through -- which is why
    only the 32-bit-sync families are scanned at all (see _SCANNED_FAMILIES).
    """
    found: dict[str, dict] = {}
    for family, syncs, parser in _FAMILY_PARSERS:
        if family not in _SCANNED_FAMILIES:
            continue
        for sync in syncs:
            if family in found:
                break
            at = data.find(sync)
            while at != -1:
                parsed = parser(data[at:])
                if parsed:
                    found[family] = parsed
                    break
                at = data.find(sync, at + len(sync))
    return found
