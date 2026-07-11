"""Source audio bit-depth / sample-rate detection.

Scans the first chunk of the playing file for audio bitstream sync patterns
and reads the coded source resolution straight from the stream headers:

* DTS / DTS-HD:  ``PCMR`` (source PCM resolution) and ``SFREQ`` fields of the
                 core frame header -> depth 16 / 20 / 24 and the sample rate.
                 The X96 extension flag doubles the rate (DTS 96/24).  When an
                 extension substream header (DTS-HD / DTS Express) is present,
                 its asset descriptor is authoritative: ``nuBitResolution``
                 and ``nuMaxSampleRate`` describe the full extension (e.g.
                 96/192 kHz XLL), which the compatibility core cannot express.
                 Layout per ETSI TS 102 114 / ffmpeg's dca_exss.c.
* MLP:           quantization word length of the major sync -> 16 / 20 / 24.
* FLAC:          bits-per-sample field of the STREAMINFO block.
* TrueHD:        the bitstream carries no bit-depth field at all; ffprobe
                 hardcodes 24 in mlp_parse.c and MediaInfo reports the same,
                 so a validated TrueHD major sync yields 24 here too.

Sample rates are only emitted for the DTS family: everywhere else Kodi's own
reported rate already is the source rate, but for DTS Kodi parses only the
compatibility core (48 kHz), never the extension substream.

Dolby Digital (AC3 / E-AC3) and other lossy codecs encode no PCM resolution,
so they are intentionally absent.

Scanning raw bytes works container-independently (MKV, MP4, TS / m2ts)
because the audio bitstream is embedded verbatim.  Every sync hit is
validated against known-good field values and each metric is decided by
majority vote across all hits, so chance byte collisions inside video data
cannot flip the result.  One result is reported per codec family; files with
several tracks of the same family but different formats (very rare) resolve
to the values seen most often in the chunk.
"""

_DTS_CORE_SYNC = b"\x7f\xfe\x80\x01"
_DTS_EXSS_SYNC = b"\x64\x58\x20\x25"
_TRUEHD_SYNC   = b"\xf8\x72\x6f\xba"
_MLP_SYNC      = b"\xf8\x72\x6f\xbb"
_FLAC_MARKER   = b"fLaC"

# major_sync_info signature that follows format_sync + format_info in both
# MLP and TrueHD streams; validates that a sync-pattern hit is a real header.
_MAJOR_SYNC_SIGNATURE = b"\xb7\x52"

# DTS core SFREQ code -> sample rate (ETSI TS 102 114; other codes invalid).
_DTS_CORE_RATES = {
    1: 8000, 2: 16000, 3: 32000,
    6: 11025, 7: 22050, 8: 44100,
    11: 12000, 12: 24000, 13: 48000,
}

# DTS core PCMR code -> source PCM resolution (codes 4 and 7 are invalid).
_DTS_PCMR_BITS = {0: 16, 1: 16, 2: 20, 3: 20, 5: 24, 6: 24}

# DTS extension substream nuMaxSampleRate code -> sample rate
# (ff_dca_sampling_freqs; every code is defined).
_DTS_EXSS_RATES = (
    8000, 16000, 32000, 64000, 128000, 22050, 44100, 88200,
    176400, 352800, 12000, 24000, 48000, 96000, 192000, 384000,
)

# MLP quantization word length code -> bits (other codes are reserved).
_MLP_QUANTS = {0: 16, 1: 20, 2: 24}

# Enough validated frame headers for an unambiguous majority vote.
_MAX_HITS = 64


class _BitReader:
    """Big-endian bit reader; raises EOFError past the end of the data."""

    def __init__(self, data: bytes, pos: int):
        self._data = data
        self._bit = pos * 8

    def read(self, count: int) -> int:
        if self._bit + count > len(self._data) * 8:
            raise EOFError
        value = 0
        bit = self._bit
        while count:
            byte = self._data[bit >> 3]
            avail = 8 - (bit & 7)
            take = min(avail, count)
            value = (value << take) | ((byte >> (avail - take)) & ((1 << take) - 1))
            bit += take
            count -= take
        self._bit = bit
        return value

    def skip(self, count: int) -> None:
        if self._bit + count > len(self._data) * 8:
            raise EOFError
        self._bit += count


def _bits(word: int, start: int, count: int, total: int) -> int:
    """Return ``count`` bits at bit offset ``start`` of a big-endian ``word``
    that is ``total`` bits wide."""
    return (word >> (total - start - count)) & ((1 << count) - 1)


def _parse_dts_core(data: bytes, pos: int) -> dict[str, int] | None:
    """Parse PCMR (depth) and SFREQ (rate) from a DTS core frame header.

    Header layout (bit offsets from the frame start): SYNC 0..31, FTYPE 32,
    SHORT 33..37, CPF 38, NBLKS 39..45, FSIZE 46..59, AMODE 60..65,
    SFREQ 66..69, RATE 70..74, five 1-bit flags 75..79, EXT_AUDIO_ID 80..82,
    EXT_AUDIO 83, ASPF 84, LFF 85..86, HFLAG 87, [HCRC 88..103 when CPF],
    FILTS, VERNUM(4), CHIST(2), PCMR(3).
    """
    raw = data[pos:pos + 15]
    if len(raw) < 15:
        return None
    word = int.from_bytes(raw, "big")

    fsize = _bits(word, 46, 14, 120)
    rate = _DTS_CORE_RATES.get(_bits(word, 66, 4, 120))
    if fsize < 95 or rate is None:
        return None

    # X96 extension (EXT_AUDIO_ID 2): the coded rate is twice the core's
    # (DTS 96/24 discs signal 48 kHz in SFREQ, play at 96 kHz).
    if _bits(word, 83, 1, 120) and _bits(word, 80, 3, 120) == 2:
        rate *= 2

    fields = {"rate": rate}
    cpf = _bits(word, 38, 1, 120)
    depth = _DTS_PCMR_BITS.get(_bits(word, 111 if cpf else 95, 3, 120))
    if depth:
        fields["depth"] = depth
    return fields


def _parse_dts_exss(data: bytes, pos: int) -> dict[str, int] | None:
    """Parse nuBitResolution / nuMaxSampleRate from the first asset descriptor
    of a DTS extension substream header (ETSI TS 102 114; field order as in
    ffmpeg's ff_dca_exss_parse / parse_descriptor)."""
    try:
        reader = _BitReader(data, pos)
        reader.skip(32 + 8)  # sync word, user defined bits
        exss_index = reader.read(2)
        wide = reader.read(1)
        header_size = reader.read(8 + 4 * wide) + 1
        size_nbits = 16 + 4 * wide
        exss_size = reader.read(size_nbits) + 1
        if exss_size < header_size:
            return None

        # Without the static-fields block the descriptor carries no
        # bit resolution / sample rate, so there is nothing to read.
        if not reader.read(1):
            return None
        reader.skip(2 + 3)  # reference clock code, frame duration
        if reader.read(1):
            reader.skip(36)  # timecode
        npresents = reader.read(3) + 1
        nassets = reader.read(3) + 1
        masks = [reader.read(exss_index + 1) for _ in range(npresents)]
        for mask in masks:
            reader.skip(bin(mask).count("1") * 8)  # active asset masks
        if reader.read(1):  # mixing metadata
            reader.skip(2)  # adjustment level
            spkr_mask_nbits = (reader.read(2) + 1) << 2
            nmixoutconfigs = reader.read(2) + 1
            reader.skip(spkr_mask_nbits * nmixoutconfigs)

        offset = header_size
        for _ in range(nassets):
            offset += reader.read(size_nbits) + 1
        if offset > exss_size:
            return None

        # First asset descriptor.
        reader.skip(9 + 3)  # descriptor size, asset index
        if reader.read(1):
            reader.skip(4)  # asset type descriptor
        if reader.read(1):
            reader.skip(24)  # language descriptor
        if reader.read(1):
            reader.skip((reader.read(10) + 1) * 8)  # additional text
        depth = reader.read(5) + 1
        rate = _DTS_EXSS_RATES[reader.read(4)]
        nchannels = reader.read(8) + 1
    except EOFError:
        return None

    if depth not in (16, 20, 24) or nchannels > 32:
        return None
    return {"depth": depth, "rate": rate}


def _parse_mlp(data: bytes, pos: int) -> dict[str, int] | None:
    """Parse the group-1 quantization word length of an MLP major sync."""
    if data[pos + 8:pos + 10] != _MAJOR_SYNC_SIGNATURE:
        return None
    depth = _MLP_QUANTS.get(data[pos + 4] >> 4)
    return {"depth": depth} if depth else None


def _parse_truehd(data: bytes, pos: int) -> dict[str, int] | None:
    """Validate a TrueHD major sync; the depth itself is not coded in the
    bitstream (see the module docstring), so a real sync yields 24."""
    if data[pos + 8:pos + 10] != _MAJOR_SYNC_SIGNATURE:
        return None
    return {"depth": 24}


def _parse_flac(data: bytes, pos: int) -> dict[str, int] | None:
    """Parse bits-per-sample from the STREAMINFO block after a fLaC marker.

    STREAMINFO is required to be the first metadata block (type 0, 34 bytes),
    which also validates the marker hit.
    """
    header = data[pos + 4:pos + 8]
    if len(header) < 4 or (header[0] & 0x7F) != 0:
        return None
    if int.from_bytes(header[1:4], "big") != 34:
        return None

    stream_info = data[pos + 8:pos + 8 + 34]
    if len(stream_info) < 34:
        return None

    sample_rate = (
        (stream_info[10] << 12)
        | (stream_info[11] << 4)
        | (stream_info[12] >> 4)
    )
    bps = (((stream_info[12] & 0x1) << 4) | (stream_info[13] >> 4)) + 1
    if not 8000 <= sample_rate <= 384000:
        return None
    if not 4 <= bps <= 32:
        return None
    return {"depth": bps}


def _scan(data: bytes, sync: bytes, parser) -> dict[str, int]:
    """Return the majority value per metric across all validated ``sync`` hits."""
    votes: dict[str, dict[int, int]] = {}
    hits = 0
    pos = data.find(sync)
    while pos != -1 and hits < _MAX_HITS:
        fields = parser(data, pos)
        if fields:
            hits += 1
            for metric, value in fields.items():
                metric_votes = votes.setdefault(metric, {})
                metric_votes[value] = metric_votes.get(value, 0) + 1
        pos = data.find(sync, pos + 1)

    return {
        metric: max(metric_votes, key=metric_votes.get)
        for metric, metric_votes in votes.items()
    }


def scan_audio_streams(data: bytes) -> dict[str, dict[str, int]]:
    """Return the detected source metrics per codec family, e.g.
    ``{"dts": {"depth": 24, "rate": 96000}, "flac": {"depth": 16}}``."""
    streams: dict[str, dict[str, int]] = {}
    for family, sync, parser in (
        ("dts", _DTS_CORE_SYNC, _parse_dts_core),
        ("dts_exss", _DTS_EXSS_SYNC, _parse_dts_exss),
        ("truehd", _TRUEHD_SYNC, _parse_truehd),
        ("mlp", _MLP_SYNC, _parse_mlp),
        ("flac", _FLAC_MARKER, _parse_flac),
    ):
        result = _scan(data, sync, parser)
        if result:
            streams[family] = result

    # The extension substream's asset descriptor is authoritative for the
    # DTS family: it describes the full extension (e.g. 96/192 kHz XLL),
    # which the compatibility core header cannot express.
    exss = streams.pop("dts_exss", None)
    if exss:
        merged = streams.get("dts", {})
        merged.update(exss)
        streams["dts"] = merged
    return streams
