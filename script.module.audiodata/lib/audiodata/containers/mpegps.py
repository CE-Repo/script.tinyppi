"""Native MPEG program stream parser (``.mpg .mpeg .vob .ps``, and the
elementary payload of DVD-Video VOBs inside an ISO).

Walks pack / system / PES layers, collects the payload of each audio stream --
MPEG audio (stream id 0xC0..0xDF) and the DVD ``private_stream_1`` sub-streams
(0xBD: AC-3 0x80..0x87, DTS 0x88..0x8F, LPCM 0xA0..0xA7) -- and hands it to the
codec header parsers.
"""

import struct

from .. import codecs
from ..report import Report, Track

_PER_STREAM_CAP = 256 * 1024
_RESOLVE_AT = 4096
# First-tier read: DVD/PS audio configuration resolves within the first packs,
# so probe a modest head before honouring a larger scan limit.
_FIRST_TIER = 8 * 1024 * 1024

MPEG_AUDIO, AC3, DTS, LPCM = "mpeg_audio", "ac3", "dts", "lpcm"

_FALLBACK_NAMES = {MPEG_AUDIO: "MPEG Audio", AC3: "AC-3", DTS: "DTS",
                   LPCM: "LPCM (DVD)"}


class _PsStream:
    __slots__ = ("kind", "tag", "buf", "resolved")

    def __init__(self, kind, tag):
        self.kind = kind
        # Display byte: the stream id for MPEG audio, the sub-stream id for
        # the private streams.
        self.tag = tag
        self.buf = bytearray()
        self.resolved = None


def probe(read, scan_limit: int):
    """Read a program stream and return its Report, or raise ValueError."""
    cap = max(scan_limit, 4096)

    # Read the first tier and parse; only pull more if nothing resolved.
    data = _read_up_to(read, min(_FIRST_TIER, cap))
    if not data.startswith(b"\x00\x00\x01"):
        raise ValueError("not an MPEG program stream")

    streams: dict = {}
    _parse(data, streams)
    if (not any(s.resolved for s in streams.values())
            and len(data) >= _FIRST_TIER and cap > len(data)):
        data += _read_up_to(read, cap - len(data))
        streams = {}
        _parse(data, streams)

    tracks = []
    for key in sorted(streams):
        stream = streams[key]
        info = stream.resolved or _parse_codec(stream.kind, bytes(stream.buf))
        tracks.append(_build_track(stream, info))
    return Report(container="MPEG-PS", tracks=tracks)


def _read_up_to(read, limit: int) -> bytes:
    chunks = []
    want = limit
    while want:
        chunk = read(want)
        if not chunk:
            break
        chunks.append(bytes(chunk))
        want -= len(chunk)
    return b"".join(chunks)


def _parse(data: bytes, streams: dict) -> None:
    """Single forward pass over the buffered program stream."""
    length = len(data)
    i = 0
    while i + 4 <= length:
        if data[i] != 0 or data[i + 1] != 0 or data[i + 2] != 1:
            i += 1                        # resync to the next start-code prefix
            continue
        start = i
        sid = data[i + 3]
        if sid == 0xBA:
            i = _skip_pack_header(data, i)
        elif sid == 0xB9:
            break                         # MPEG_program_end_code
        elif sid in (0xBB, 0xBC, 0xBE, 0xBF) or 0xF0 <= sid <= 0xFF:
            i = _skip_length_prefixed(data, i)
        elif sid == 0xBD or 0xC0 <= sid <= 0xEF:
            payload, nxt = _pes_payload(data, i)
            if payload:
                _dispatch(sid, payload, streams)
            i = nxt
        else:
            i = _skip_length_prefixed(data, i)
        if i <= start:
            i = start + 1                 # guarantee forward progress


def _skip_pack_header(data: bytes, i: int) -> int:
    """Advance past a pack header (start code 0x000001BA at ``i``)."""
    if i + 4 >= len(data):
        return len(data)
    b = data[i + 4]
    if b & 0xC0 == 0x40:
        # MPEG-2 pack: start code + 10 bytes, then a 3-bit stuffing count.
        stuffing = data[i + 13] & 0x07 if i + 13 < len(data) else 0
        return min(i + 14 + stuffing, len(data))
    if b & 0xF0 == 0x20:
        return min(i + 12, len(data))     # MPEG-1 pack
    return _next_start_code(data, i + 4)


def _skip_length_prefixed(data: bytes, i: int) -> int:
    """Advance past a length-prefixed packet (0x000001 xx len16 body)."""
    if i + 6 > len(data):
        return len(data)
    return min(i + 6 + struct.unpack_from(">H", data, i + 4)[0], len(data))


def _pes_payload(data: bytes, i: int):
    """Return ``(payload, offset of the next packet)`` for a PES packet."""
    if i + 6 > len(data):
        return None, len(data)
    packet_len = struct.unpack_from(">H", data, i + 4)[0]
    if packet_len == 0:
        pkt_end = _next_start_code(data, i + 6)
    else:
        pkt_end = min(i + 6 + packet_len, len(data))
    body = data[i + 6:pkt_end]
    payload = body[_pes_header_len(body):]
    return (payload or None), pkt_end


def _pes_header_len(body: bytes) -> int:
    """Bytes of PES header before the payload, for MPEG-2 and MPEG-1 framing."""
    if len(body) >= 3 and body[0] & 0xC0 == 0x80:
        # MPEG-2 PES: '10' marker, flags, then PES_header_data_length.
        return 3 + body[2]
    # MPEG-1 PES: up to 16 stuffing bytes, optional STD buffer, then PTS/DTS.
    j = 0
    while j < 16 and j < len(body) and body[j] == 0xFF:
        j += 1
    if j < len(body) and body[j] & 0xC0 == 0x40:
        j += 2                            # STD buffer scale/size
    if j >= len(body):
        return j
    marker = body[j] & 0xF0
    if marker == 0x20:
        return j + 5                      # PTS only
    if marker == 0x30:
        return j + 10                     # PTS + DTS
    if body[j] == 0x0F:
        return j + 1
    return j


def _dispatch(sid: int, payload: bytes, streams: dict) -> None:
    if 0xC0 <= sid <= 0xDF:
        _append(streams, sid, MPEG_AUDIO, sid, payload)
        return
    if sid != 0xBD or not payload:
        return                            # video or extended: ignored

    sub = payload[0]
    if 0x80 <= sub <= 0x87:
        # AC-3 carries a 4-byte private header (sub id + frame info).
        _append(streams, 0x100 | sub, AC3, sub, payload[min(4, len(payload)):])
    elif 0x88 <= sub <= 0x8F:
        _append(streams, 0x100 | sub, DTS, sub, payload[min(4, len(payload)):])
    elif 0xA0 <= sub <= 0xA7:
        # LPCM: the parameters sit in the header after the sub id.
        key = 0x100 | sub
        entry = streams.get(key)
        if entry is None:
            entry = streams[key] = _PsStream(LPCM, sub)
        if entry.resolved is None:
            entry.resolved = codecs.pcm.parse_dvd_lpcm(payload[min(1, len(payload)):])
    # Subpicture (0x20..0x3F) and everything else: not audio.


def _append(streams: dict, key: int, kind, tag: int, data: bytes) -> None:
    entry = streams.get(key)
    if entry is None:
        entry = streams[key] = _PsStream(kind, tag)
    if len(entry.buf) < _PER_STREAM_CAP:
        entry.buf.extend(data)
    if entry.resolved is None and len(entry.buf) >= _RESOLVE_AT:
        # Give DTS a larger window so extension substreams classify reliably.
        want_more = kind == DTS and len(entry.buf) < 32 * 1024
        if not want_more:
            entry.resolved = _parse_codec(kind, bytes(entry.buf))


def _next_start_code(data: bytes, start: int) -> int:
    """Scan forward for the next 0x000001 start-code prefix."""
    found = data.find(b"\x00\x00\x01", start)
    return found if found != -1 else len(data)


def _parse_codec(kind, buf: bytes):
    if not buf:
        return None
    if kind == MPEG_AUDIO:
        return codecs.mpeg_audio.parse(buf)
    if kind == AC3:
        return codecs.ac3.parse(buf)
    if kind == DTS:
        return codecs.dts.parse(buf)
    return None                           # LPCM resolves from its header


def _build_track(stream, info) -> Track:
    track = Track(id=f"0x{stream.tag:02X}", codec=_FALLBACK_NAMES[stream.kind])
    if info is None:
        track.note = "no payload captured in scan window"
        return track
    if info.name:
        track.codec = info.name
    track.sample_rate = info.sample_rate
    track.bit_depth = info.bit_depth
    track.channels = info.channels
    track.lfe = info.lfe
    track.note = info.note
    return track
