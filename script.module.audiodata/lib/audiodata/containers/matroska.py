"""Native Matroska / WebM (EBML) parser.

Reads the Tracks element for audio track metadata, then -- for codecs whose
container metadata is incomplete (bit depth for DTS, exact rates for
AC-3/TrueHD, ...) -- samples the first frames from the Clusters and hands them
to the codec header parsers.
"""

import struct

from .. import codecs
from ..report import Report, Track

# Element IDs (with marker bits, as stored)
ID_EBML                       = 0x1A45DFA3
ID_DOCTYPE                    = 0x4282
ID_SEGMENT                    = 0x18538067
ID_TRACKS                     = 0x1654AE6B
ID_TRACK_ENTRY                = 0xAE
ID_TRACK_NUMBER               = 0xD7
ID_TRACK_TYPE                 = 0x83
ID_FLAG_DEFAULT               = 0x88
ID_CODEC_ID                   = 0x86
ID_CODEC_PRIVATE              = 0x63A2
ID_NAME                       = 0x536E
ID_LANGUAGE                   = 0x22B59C
ID_LANGUAGE_IETF              = 0x22B59D
ID_AUDIO                      = 0xE1
ID_SAMPLING_FREQUENCY         = 0xB5
ID_OUTPUT_SAMPLING_FREQUENCY  = 0x78B5
ID_CHANNELS                   = 0x9F
ID_BIT_DEPTH                  = 0x6264
ID_CLUSTER                    = 0x1F43B675
ID_TIMESTAMP                  = 0xE7
ID_SIMPLE_BLOCK               = 0xA3
ID_BLOCK_GROUP                = 0xA0
ID_BLOCK                      = 0xA1
ID_VOID                       = 0xEC
ID_CRC32                      = 0xBF
ID_CLUSTER_POSITION           = 0xA7
ID_CLUSTER_PREV_SIZE          = 0xAB
ID_SILENT_TRACKS              = 0x5854

UNKNOWN_SIZE = -1
_MAX_SAMPLE_BYTES = 256 * 1024      # per-track frame sample cap
_ENOUGH_SAMPLE_BYTES = 16 * 1024
_MAX_CLUSTERS = 64
_TRACK_TYPE_AUDIO = 2

# Codecs whose container metadata is incomplete, so their frames are sampled.
_FRAME_SAMPLE_CODECS = ("A_AC3", "A_EAC3", "A_TRUEHD", "A_MLP")


class _Invalid(Exception):
    """Raised on structurally invalid EBML; callers stop where they are."""


class _Ebml:
    """EBML element reader over a seekable source."""

    def __init__(self, source):
        self._source = source
        self.pos = 0

    def read_bytes(self, count: int) -> bytes:
        chunks = []
        want = count
        while want:
            chunk = self._source.read(want)
            if not chunk:
                raise _Invalid("short read")
            chunks.append(bytes(chunk))
            want -= len(chunk)
        self.pos += count
        return b"".join(chunks)

    def read_byte(self) -> int:
        return self.read_bytes(1)[0]

    def seek_to(self, pos: int) -> None:
        self._source.seek(pos)
        self.pos = pos

    def skip(self, count: int) -> None:
        self.seek_to(self.pos + count)

    def read_id(self) -> int:
        """Read an element ID, marker bits kept as conventionally written."""
        first = self.read_byte()
        length = _vint_length(first)
        value = first
        for _ in range(1, length):
            value = (value << 8) | self.read_byte()
        return value

    def read_size(self) -> int:
        """Read an element size, marker stripped; UNKNOWN_SIZE for unknown."""
        first = self.read_byte()
        length = _vint_length(first)
        mask = (0xFF >> length) & 0xFF
        value = first & mask
        all_ones = value == mask
        for _ in range(1, length):
            byte = self.read_byte()
            all_ones = all_ones and byte == 0xFF
            value = (value << 8) | byte
        return UNKNOWN_SIZE if all_ones else value

    def read_header(self):
        return self.read_id(), self.read_size()

    def read_uint(self, size: int) -> int:
        if size > 8:
            raise _Invalid("oversized integer")
        value = 0
        for byte in self.read_bytes(size):
            value = (value << 8) | byte
        return value

    def read_float(self, size: int) -> float:
        if size == 0:
            return 0.0
        if size == 4:
            return struct.unpack(">f", self.read_bytes(4))[0]
        if size == 8:
            return struct.unpack(">d", self.read_bytes(8))[0]
        raise _Invalid("invalid float width")

    def read_string(self, size: int) -> str:
        data = self.read_bytes(min(size, 1024))
        if size > 1024:
            self.skip(size - 1024)
        return data.decode("utf-8", "replace").rstrip("\0")


def _vint_length(first: int) -> int:
    """Return the encoded length of a VINT from its lead byte."""
    if first == 0:
        raise _Invalid("invalid VINT lead byte")
    length = 1
    mask = 0x80
    while not first & mask:
        mask >>= 1
        length += 1
    return length


class _MkvTrack:
    __slots__ = ("number", "track_type", "codec_id", "codec_private",
                 "language", "language_ietf", "name", "default",
                 "sampling_frequency", "output_sampling_frequency",
                 "channels", "bit_depth")

    def __init__(self):
        self.number = 0
        self.track_type = 0
        self.codec_id = ""
        self.codec_private = b""
        self.language = None
        self.language_ietf = None
        self.name = None
        self.default = True          # FlagDefault defaults to 1
        self.sampling_frequency = None
        self.output_sampling_frequency = None
        self.channels = None
        self.bit_depth = None


def probe(source, file_len: int, deep: bool = True):
    """Read a Matroska stream and return its Report, or raise ValueError."""
    e = _Ebml(source)
    container = "Matroska"

    try:
        if e.read_id() != ID_EBML:
            raise ValueError("not a Matroska file")
        size = e.read_size()
        if size != UNKNOWN_SIZE:
            end = e.pos + size
            while e.pos < end:
                try:
                    cid, csize = e.read_header()
                except _Invalid:
                    break
                if csize == UNKNOWN_SIZE:
                    break
                if cid == ID_DOCTYPE:
                    if e.read_string(csize) == "webm":
                        container = "WebM"
                else:
                    e.skip(csize)
            e.seek_to(end)

        if e.read_id() != ID_SEGMENT:
            raise ValueError("no Segment element found")
        seg_size = e.read_size()
        seg_end = file_len if seg_size == UNKNOWN_SIZE else min(e.pos + seg_size, file_len)
    except _Invalid as exc:
        raise ValueError(f"invalid EBML data: {exc}") from None

    tracks: list = []
    tracks_seen = False
    samples: dict = {}
    needed: list = []
    clusters_scanned = 0

    while e.pos < seg_end:
        try:
            element_id, size = e.read_header()
        except _Invalid:
            break

        if element_id == ID_TRACKS:
            if size == UNKNOWN_SIZE:
                raise ValueError("Tracks element with unknown size")
            end = e.pos + size
            try:
                while e.pos < end:
                    cid, csize = e.read_header()
                    if cid == ID_TRACK_ENTRY and csize != UNKNOWN_SIZE:
                        entry_end = e.pos + csize
                        try:
                            tracks.append(_parse_track_entry(e, entry_end))
                        except _Invalid:
                            e.seek_to(entry_end)
                    elif csize != UNKNOWN_SIZE:
                        e.skip(csize)
                    else:
                        break
            except _Invalid:
                pass
            tracks_seen = True
            needed = [t.number for t in tracks
                      if t.track_type == _TRACK_TYPE_AUDIO
                      and _wants_frame_sample(t.codec_id)]
            if not deep or not needed:
                break
            continue

        if element_id == ID_CLUSTER:
            if not tracks_seen or not needed or clusters_scanned >= _MAX_CLUSTERS:
                break
            clusters_scanned += 1
            unknown = size == UNKNOWN_SIZE
            cluster_end = seg_end if unknown else e.pos + size
            try:
                _scan_cluster(e, cluster_end, unknown, samples, needed)
            except _Invalid:
                break
            if not needed:
                break
            continue

        if size == UNKNOWN_SIZE:
            break
        try:
            e.skip(size)
        except _Invalid:
            break

    if not tracks_seen:
        raise ValueError("no Tracks element found")

    return Report(
        container=container,
        tracks=[_build_track(t, samples.get(t.number))
                for t in tracks if t.track_type == _TRACK_TYPE_AUDIO],
    )


def _parse_track_entry(e: _Ebml, end: int) -> _MkvTrack:
    t = _MkvTrack()
    while e.pos < end:
        element_id, size = e.read_header()
        if size == UNKNOWN_SIZE:
            raise _Invalid("unknown size inside TrackEntry")
        if element_id == ID_TRACK_NUMBER:
            t.number = e.read_uint(size)
        elif element_id == ID_TRACK_TYPE:
            t.track_type = e.read_uint(size)
        elif element_id == ID_FLAG_DEFAULT:
            t.default = e.read_uint(size) == 1
        elif element_id == ID_CODEC_ID:
            t.codec_id = e.read_string(size)
        elif element_id == ID_CODEC_PRIVATE:
            take = min(size, 65536)
            t.codec_private = e.read_bytes(take)
            if size > take:
                e.skip(size - take)
        elif element_id == ID_NAME:
            t.name = e.read_string(size)
        elif element_id == ID_LANGUAGE:
            t.language = e.read_string(size)
        elif element_id == ID_LANGUAGE_IETF:
            t.language_ietf = e.read_string(size)
        elif element_id == ID_AUDIO:
            aend = e.pos + size
            while e.pos < aend:
                aid, asize = e.read_header()
                if asize == UNKNOWN_SIZE:
                    raise _Invalid("unknown size inside Audio")
                if aid == ID_SAMPLING_FREQUENCY:
                    t.sampling_frequency = e.read_float(asize)
                elif aid == ID_OUTPUT_SAMPLING_FREQUENCY:
                    t.output_sampling_frequency = e.read_float(asize)
                elif aid == ID_CHANNELS:
                    t.channels = e.read_uint(asize)
                elif aid == ID_BIT_DEPTH:
                    t.bit_depth = e.read_uint(asize)
                else:
                    e.skip(asize)
        else:
            e.skip(size)
    return t


def _wants_frame_sample(codec_id: str) -> bool:
    """Which codecs benefit from sampling actual frames out of the clusters?"""
    return (codec_id in _FRAME_SAMPLE_CODECS
            or codec_id.startswith("A_DTS")
            or codec_id.startswith("A_MPEG/"))


def _scan_cluster(e: _Ebml, cluster_end: int, unknown_size: bool,
                  samples: dict, needed: list) -> None:
    while e.pos < cluster_end:
        start = e.pos
        try:
            element_id, size = e.read_header()
        except _Invalid:
            return

        if element_id in (ID_SIMPLE_BLOCK, ID_BLOCK):
            if size == UNKNOWN_SIZE:
                raise _Invalid("unknown size on a block")
            _collect_block(e, size, samples, needed)
        elif element_id == ID_BLOCK_GROUP:
            if size == UNKNOWN_SIZE:
                raise _Invalid("unknown size on a block group")
            gend = e.pos + size
            while e.pos < gend:
                gid, gsize = e.read_header()
                if gsize == UNKNOWN_SIZE:
                    raise _Invalid("unknown size inside a block group")
                if gid == ID_BLOCK:
                    _collect_block(e, gsize, samples, needed)
                else:
                    e.skip(gsize)
        elif element_id in (ID_TIMESTAMP, ID_VOID, ID_CRC32, ID_CLUSTER_POSITION,
                            ID_CLUSTER_PREV_SIZE, ID_SILENT_TRACKS):
            if size == UNKNOWN_SIZE:
                raise _Invalid("unknown size on a cluster child")
            e.skip(size)
        else:
            # An unknown-size cluster ends at the next element that does not
            # belong inside one (e.g. the next Cluster ID).
            if unknown_size:
                e.seek_to(start)
                return
            if size == UNKNOWN_SIZE:
                raise _Invalid("unknown size inside a cluster")
            e.skip(size)

        if not needed:
            if not unknown_size:
                e.seek_to(cluster_end)
            return


def _collect_block(e: _Ebml, size: int, samples: dict, needed: list) -> None:
    take = min(size, 128 * 1024)
    data = e.read_bytes(take)
    if size > take:
        e.skip(size - take)
    header = _parse_block_header(data)
    if header is None:
        return
    track, payload_start = header
    if track not in needed:
        return
    buf = samples.setdefault(track, bytearray())
    buf.extend(data[payload_start:])
    if len(buf) >= _ENOUGH_SAMPLE_BYTES or len(buf) >= _MAX_SAMPLE_BYTES:
        needed.remove(track)


def _parse_block_header(data: bytes):
    """Return ``(track number, offset of the first payload byte)``.

    The offset is past any lacing headers, so the codec parsers see frame data
    rather than the frame-size table in front of it.
    """
    if not data:
        return None
    try:
        length = _vint_length(data[0])
    except _Invalid:
        return None
    if len(data) < length + 3:
        return None

    track = data[0] & ((0xFF >> length) & 0xFF)
    for byte in data[1:length]:
        track = (track << 8) | byte

    flags = data[length + 2]
    pos = length + 3
    lacing = (flags >> 1) & 3
    if lacing:
        if pos >= len(data):
            return None
        frames_minus_one = data[pos]
        pos += 1
        if lacing == 1:
            # Xiph: n-1 sizes, each a run of 0xFF bytes plus a terminator.
            for _ in range(frames_minus_one):
                while True:
                    if pos >= len(data):
                        return None
                    byte = data[pos]
                    pos += 1
                    if byte != 255:
                        break
        elif lacing == 3 and frames_minus_one > 0:
            # EBML: the first size as a VINT, then n-2 signed VINT deltas.
            for _ in range(frames_minus_one):
                if pos >= len(data):
                    return None
                try:
                    pos += _vint_length(data[pos])
                except _Invalid:
                    return None
        # Fixed-size lacing (2) carries no size table.
    if pos > len(data):
        return None
    return track, pos


def _build_track(t: _MkvTrack, sample) -> Track:
    sample = bytes(sample) if sample else b""
    private = t.codec_private

    codec_id = t.codec_id
    if codec_id in ("A_AC3", "A_EAC3"):
        parsed = codecs.ac3.parse(sample)
    elif codec_id in ("A_TRUEHD", "A_MLP"):
        parsed = codecs.truehd.parse(sample)
    elif codec_id == "A_FLAC":
        parsed = codecs.flac.parse(private)
    elif codec_id == "A_OPUS":
        parsed = codecs.xiph.parse_opus_head(private)
    elif codec_id == "A_VORBIS":
        parsed = codecs.xiph.parse_vorbis(private)
    elif codec_id == "A_MS/ACM":
        parsed = codecs.pcm.parse_waveformatex(private)
    elif codec_id == "A_ALAC":
        parsed = codecs.pcm.parse_alac_config(private)
    elif codec_id.startswith("A_DTS"):
        parsed = codecs.dts.parse(sample)
    elif codec_id.startswith("A_AAC"):
        parsed = codecs.aac.parse_asc(private) if private else None
    elif codec_id.startswith("A_MPEG/"):
        parsed = codecs.mpeg_audio.parse(sample)
    else:
        parsed = None

    container_rate = t.output_sampling_frequency or t.sampling_frequency
    container_rate = round(container_rate) if container_rate else None
    if not container_rate:
        container_rate = None

    track = Track(
        id=str(t.number),
        codec=_codec_display_name(codec_id),
        sample_rate=container_rate,
        bit_depth=t.bit_depth or None,
        channels=t.channels or None,
        language=t.language_ietf or t.language,
        title=t.name,
        default=t.default,
    )

    if parsed:
        if parsed.name:
            track.codec = parsed.name
        if parsed.sample_rate is not None:
            track.sample_rate = parsed.sample_rate
        if parsed.bit_depth is not None:
            track.bit_depth = parsed.bit_depth
        if parsed.channels is not None:
            track.channels = parsed.channels
            track.lfe = parsed.lfe
        track.note = parsed.note
    elif _wants_frame_sample(codec_id) and not sample:
        track.note = "container metadata only"

    # PCM float is at least 32-bit even if BitDepth is missing.
    if codec_id == "A_PCM/FLOAT/IEEE" and track.bit_depth is None:
        track.bit_depth = 32
    # Old-style SBR signalling without CodecPrivate: the output rate is doubled.
    if "/SBR" in codec_id and t.output_sampling_frequency is None:
        if track.sample_rate and track.sample_rate <= 24000:
            track.sample_rate *= 2
    return track


_CODEC_DISPLAY_NAMES = {
    "A_AC3": "AC-3", "A_EAC3": "E-AC-3", "A_TRUEHD": "TrueHD", "A_MLP": "MLP",
    "A_DTS": "DTS", "A_DTS/LOSSLESS": "DTS-HD MA", "A_DTS/EXPRESS": "DTS Express",
    "A_FLAC": "FLAC", "A_OPUS": "Opus", "A_VORBIS": "Vorbis", "A_ALAC": "ALAC",
    "A_WAVPACK4": "WavPack", "A_TTA1": "TTA",
    "A_MPEG/L3": "MP3", "A_MPEG/L2": "MP2", "A_MPEG/L1": "MP1",
    "A_PCM/INT/LIT": "PCM", "A_PCM/INT/BIG": "PCM (BE)",
    "A_PCM/FLOAT/IEEE": "PCM (float)", "A_MS/ACM": "ACM",
}


def _codec_display_name(codec_id: str) -> str:
    name = _CODEC_DISPLAY_NAMES.get(codec_id)
    if name:
        return name
    if codec_id.startswith("A_AAC"):
        if "/SBR" in codec_id:
            return "HE-AAC"
        if "/LC" in codec_id:
            return "AAC-LC"
        if "/MAIN" in codec_id:
            return "AAC Main"
        return "AAC"
    return codec_id[2:] if codec_id.startswith("A_") else codec_id
