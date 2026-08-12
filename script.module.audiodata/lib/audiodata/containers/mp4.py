"""Native ISO BMFF (MP4 / M4A / MOV) parser.

Walks moov -> trak -> mdia -> minf -> stbl -> stsd and reads the audio sample
entries plus their codec configuration boxes (esds, dac3, dec3, ddts, dfLa,
dOps, alac).  The configuration box is where an MP4 states the real parameters:
the sample entry's own rate field is a 16.16 fixed-point value that cannot hold
96 kHz, and its sample size is meaningless for a compressed codec.
"""

import struct

from .. import codecs
from ..bitreader import BitReader
from ..codecinfo import CodecInfo
from ..report import Report, Track

_AC3_RATES = (48000, 44100, 32000)
_ACMOD_CHANNELS = (2, 1, 2, 3, 3, 4, 4, 5)

_PCM_FORMATS = (b"lpcm", b"sowt", b"twos", b"in24", b"in32", b"fl32",
                b"fl64", b"raw ")

_FORMAT_NAMES = {
    b"mp4a": "AAC", b"ac-3": "AC-3", b"sac3": "AC-3", b"ec-3": "E-AC-3",
    b"dtsc": "DTS", b"dtsh": "DTS-HD", b"dtsl": "DTS-HD MA",
    b"dtse": "DTS Express", b"fLaC": "FLAC", b"Opus": "Opus", b"alac": "ALAC",
    b"lpcm": "PCM", b"raw ": "PCM", b"sowt": "PCM (LE)", b"twos": "PCM (BE)",
    b"in24": "PCM 24-bit", b"in32": "PCM 32-bit",
    b"fl32": "PCM (float)", b"fl64": "PCM (float)",
    b"samr": "AMR-NB", b"sawb": "AMR-WB",
}


def _iter_boxes(source, start: int, end: int):
    """Yield ``(kind, body_start, body_end)`` for each box in a range."""
    pos = start
    while pos + 8 <= end:
        source.seek(pos)
        header = source.read(8)
        if header is None or len(header) < 8:
            return
        header = bytes(header)
        size32 = struct.unpack(">I", header[:4])[0]
        kind = header[4:8]
        if size32 == 1:
            big = source.read(8)
            if big is None or len(big) < 8:
                return
            size = struct.unpack(">Q", bytes(big))[0]
            header_len = 16
        elif size32 == 0:
            size = end - pos
            header_len = 8
        else:
            size = size32
            header_len = 8
        if size < header_len:
            return
        yield kind, pos + header_len, min(pos + size, end)
        pos += size


def _read_range(source, start: int, end: int, cap: int) -> bytes:
    length = min(max(end - start, 0), cap)
    if length <= 0:
        return b""
    try:
        source.seek(start)
        data = source.read(length)
    except Exception:
        return b""
    return bytes(data) if data else b""


def _find_box(source, start: int, end: int, kind: bytes):
    for box_kind, body_start, body_end in _iter_boxes(source, start, end):
        if box_kind == kind:
            return body_start, body_end
    return None


def probe(source, file_len: int):
    """Read an ISO BMFF stream and return its Report, or raise ValueError."""
    container = "MP4"
    moov = None
    for kind, body_start, body_end in _iter_boxes(source, 0, file_len):
        if kind == b"ftyp":
            body = _read_range(source, body_start, body_end, 16)
            if len(body) >= 4:
                brand = body[:4].decode("latin-1")
                if brand == "qt  ":
                    container = "QuickTime"
                elif brand == "M4A ":
                    container = "M4A"
        elif kind == b"moov":
            moov = (body_start, body_end)
            break
    if moov is None:
        raise ValueError("no moov box found")

    traks = [(s, e) for kind, s, e in _iter_boxes(source, moov[0], moov[1])
             if kind == b"trak"]

    tracks = []
    for index, (start, end) in enumerate(traks, start=1):
        track = _parse_trak(source, start, end, index)
        if track is not None:
            tracks.append(track)
    return Report(container=container, tracks=tracks)


def _parse_trak(source, start: int, end: int, index: int):
    tkhd = _find_box(source, start, end, b"tkhd")
    mdia = _find_box(source, start, end, b"mdia")
    if tkhd is None or mdia is None:
        return None
    hdlr = _find_box(source, mdia[0], mdia[1], b"hdlr")
    if hdlr is None:
        return None
    handler = _read_range(source, hdlr[0], hdlr[1], 12)
    if len(handler) < 12 or handler[8:12] != b"soun":
        return None                       # not an audio track

    tkhd_body = _read_range(source, tkhd[0], tkhd[1], 24)
    track_id = None
    if tkhd_body:
        offset = 20 if tkhd_body[0] == 1 else 12
        if len(tkhd_body) >= offset + 4:
            track_id = struct.unpack_from(">I", tkhd_body, offset)[0]

    language = _parse_language(source, mdia)

    minf = _find_box(source, mdia[0], mdia[1], b"minf")
    if minf is None:
        return None
    stbl = _find_box(source, minf[0], minf[1], b"stbl")
    if stbl is None:
        return None
    stsd_range = _find_box(source, stbl[0], stbl[1], b"stsd")
    if stsd_range is None:
        return None
    stsd = _read_range(source, stsd_range[0], stsd_range[1], 4096)
    if len(stsd) < 16:
        return None

    # stsd: version+flags(4) entry_count(4), then the sample entries.
    entry = stsd[8:]
    entry_size = struct.unpack_from(">I", entry, 0)[0]
    fmt = entry[4:8]
    entry = entry[:min(entry_size, len(entry))]

    track = Track(
        id=str(track_id) if track_id else str(index),
        codec=fmt.decode("latin-1").strip(),
        language=language,
        default=True,
    )

    # AudioSampleEntry: 8 header + 6 reserved + 2 data_ref, then version(2)…
    if len(entry) >= 36:
        version = struct.unpack_from(">H", entry, 16)[0]
        channels = struct.unpack_from(">H", entry, 24)[0]
        sample_size = struct.unpack_from(">H", entry, 26)[0]
        rate = struct.unpack_from(">I", entry, 32)[0] >> 16
        children_off = 36
        if version == 1:
            children_off = 36 + 16
        elif version == 2 and len(entry) >= 72:
            # QuickTime version 2 sample entry
            value = struct.unpack_from(">d", entry, 40)[0]
            if value == value and value not in (float("inf"), float("-inf")) and value > 0:
                rate = round(value)
            channels = struct.unpack_from(">I", entry, 48)[0]
            sample_size = struct.unpack_from(">I", entry, 56)[0]
            children_off = 72
        if rate > 0:
            track.sample_rate = rate
        if channels > 0:
            track.channels = channels

        info = _parse_sample_entry(fmt, entry[children_off:])
        _apply_entry_info(track, fmt, sample_size, info)
    return track


def _parse_language(source, mdia):
    mdhd_range = _find_box(source, mdia[0], mdia[1], b"mdhd")
    if mdhd_range is None:
        return None
    mdhd = _read_range(source, mdhd_range[0], mdhd_range[1], 36)
    if not mdhd:
        return None
    offset = 28 if mdhd[0] == 1 else 20
    if len(mdhd) < offset + 2:
        return None
    packed = struct.unpack_from(">H", mdhd, offset)[0]
    if packed in (0, 0x7FFF):
        return None
    text = "".join(chr(((packed >> (10 - i * 5)) & 0x1F) + 0x60) for i in range(3))
    return text if text.isalpha() and text.islower() else None


def _apply_entry_info(track: Track, fmt: bytes, sample_size: int, info) -> None:
    track.codec = _FORMAT_NAMES.get(fmt, track.codec)

    if fmt in _PCM_FORMATS and sample_size > 0:
        track.bit_depth = {b"in24": 24, b"in32": 32, b"fl32": 32,
                           b"fl64": 64}.get(fmt, sample_size)

    if info:
        if info.name:
            track.codec = info.name
        if info.sample_rate is not None:
            track.sample_rate = info.sample_rate
        if info.bit_depth is not None:
            track.bit_depth = info.bit_depth
        if info.channels is not None:
            track.channels = info.channels
            track.lfe = info.lfe
        track.note = info.note


def _parse_sample_entry(fmt: bytes, children: bytes):
    """Parse the child boxes of an audio sample entry (esds, dac3, ddts, …)."""
    pos = 0
    while pos + 8 <= len(children):
        size = struct.unpack_from(">I", children, pos)[0]
        if size < 8 or pos + size > len(children):
            break
        kind = children[pos + 4:pos + 8]
        body = children[pos + 8:pos + size]

        if kind == b"esds":
            parsed = _parse_esds(body)
        elif kind == b"dac3":
            parsed = _parse_dac3(body)
        elif kind == b"dec3":
            parsed = _parse_dec3(body)
        elif kind == b"ddts":
            parsed = _parse_ddts(body, fmt)
        elif kind == b"dfLa":
            parsed = codecs.flac.parse(body[4:])
        elif kind == b"dOps":
            parsed = _parse_dops(body)
        elif kind == b"alac":
            parsed = codecs.pcm.parse_alac_config(body[4:])
        elif kind == b"wave":
            # QuickTime nests the configuration boxes inside a 'wave' box.
            parsed = _parse_sample_entry(fmt, body)
        else:
            parsed = None

        if parsed:
            return parsed
        pos += size
    return None


def _read_descriptor(b: bytes):
    """Read an MPEG-4 descriptor: a tag byte plus an expandable length."""
    if not b:
        return None
    tag = b[0]
    length = 0
    i = 1
    for _ in range(4):
        if i >= len(b):
            return None
        byte = b[i]
        i += 1
        length = (length << 7) | (byte & 0x7F)
        if not byte & 0x80:
            break
    return tag, b[i:min(i + length, len(b))]


def _parse_esds(body: bytes):
    # body: version+flags(4), then a descriptor tree
    descriptor = _read_descriptor(body[4:])
    if not descriptor or descriptor[0] != 0x03:
        return None
    es = descriptor[1]
    if len(es) < 3:
        return None
    # ES_Descriptor: ES_ID(2), flags(1), optional fields, then the
    # DecoderConfigDescriptor.
    offset = 3
    flags = es[2]
    if flags & 0x80:
        offset += 2                       # dependsOn_ES_ID
    if flags & 0x40:
        if offset >= len(es):
            return None
        offset += 1 + es[offset]          # URL
    if flags & 0x20:
        offset += 2                       # OCR_ES_ID

    descriptor = _read_descriptor(es[offset:])
    if not descriptor or descriptor[0] != 0x04:
        return None
    dcd = descriptor[1]
    if not dcd:
        return None
    oti = dcd[0]

    if oti in (0x40, 0x66, 0x67, 0x68):
        # MPEG-4 / MPEG-2 AAC: the DecSpecificInfo holds the ASC.
        inner = _read_descriptor(dcd[13:])
        if inner and inner[0] == 0x05:
            return codecs.aac.parse_asc(inner[1])
        return CodecInfo(name="AAC")
    return {
        0x69: CodecInfo(name="MP3"), 0x6B: CodecInfo(name="MP3"),
        0xA9: CodecInfo(name="DTS"), 0xA5: CodecInfo(name="AC-3"),
        0xA6: CodecInfo(name="E-AC-3"),
    }.get(oti)


def _parse_dac3(body: bytes):
    try:
        r = BitReader(body)
        fscod = r.read(2)
        r.skip(5 + 3)                     # bsid, bsmod
        acmod = r.read(3)
        lfeon = r.read(1)
    except EOFError:
        return None
    return CodecInfo(
        name="AC-3",
        sample_rate=_AC3_RATES[fscod] if fscod < len(_AC3_RATES) else None,
        channels=_ACMOD_CHANNELS[acmod] + lfeon,
        lfe=lfeon == 1,
    )


def _parse_dec3(body: bytes):
    try:
        r = BitReader(body)
        r.skip(13 + 3)                    # data_rate, num_ind_sub
        fscod = r.read(2)
        r.skip(5 + 1 + 1 + 3)             # bsid, reserved, asvc, bsmod
        acmod = r.read(3)
        lfeon = r.read(1)
    except EOFError:
        return None
    return CodecInfo(
        name="E-AC-3",
        sample_rate=_AC3_RATES[fscod] if fscod < len(_AC3_RATES) else None,
        channels=_ACMOD_CHANNELS[acmod] + lfeon,
        lfe=lfeon == 1,
    )


def _parse_ddts(body: bytes, fmt: bytes):
    if len(body) < 13:
        return None
    rate = struct.unpack_from(">I", body, 0)[0]
    depth = body[12]
    name = {b"dtsh": "DTS-HD", b"dtsl": "DTS-HD MA",
            b"dtse": "DTS Express"}.get(fmt, "DTS")
    return CodecInfo(name=name, sample_rate=rate or None, bit_depth=depth or None)


def _parse_dops(body: bytes):
    # dOps: version(1), channel count(1), pre-skip(2), input rate(4) …
    if len(body) < 2:
        return None
    channels = body[1]
    return CodecInfo(name="Opus", sample_rate=48000, channels=channels or None)
