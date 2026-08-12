"""Native AVI (RIFF) parser.

Walks the ``hdrl`` header list to each stream's ``strl``, and for every audio
stream (``strh`` with fccType ``auds``) reads the ``strf`` chunk -- a
WAVEFORMATEX -- for codec, sample rate, bit depth and channels.  The huge
``movi`` payload is never touched: everything needed sits in the front header.
"""

import struct

from .. import codecs
from ..report import Report, Track

# The hdrl header list lives at the front of the file; cap the head read so a
# file with an implausibly large header cannot pull in the whole movi.
_HEAD_BYTES = 4 * 1024 * 1024


def probe(read, file_len: int = 0):
    """Read an AVI stream and return its Report, or raise ValueError."""
    head = _read_up_to(read, _HEAD_BYTES)
    if len(head) < 12 or head[0:4] != b"RIFF" or head[8:12] != b"AVI ":
        raise ValueError("not an AVI file")

    hdrl = _find_list(head, 12, len(head), b"hdrl")
    if hdrl is None:
        raise ValueError("no hdrl header list found in AVI")
    hdrl_start, hdrl_end = hdrl

    tracks = []
    index = 0
    pos = hdrl_start
    while True:
        chunk = _chunk_at(head, pos, hdrl_end)
        if chunk is None:
            break
        chunk_id, size, body = chunk
        if chunk_id == b"LIST" and head[body:body + 4] == b"strl":
            index += 1
            track = _parse_strl(head, body + 4, min(body + size, hdrl_end), index)
            if track is not None:
                tracks.append(track)
        nxt = _advance(pos, size, hdrl_end)
        if nxt <= pos:
            break                          # malformed size that did not advance
        pos = nxt

    return Report(container="AVI", tracks=tracks)


def _read_up_to(read, count: int) -> bytes:
    chunks = []
    want = count
    while want:
        chunk = read(want)
        if not chunk:
            break
        chunks.append(bytes(chunk))
        want -= len(chunk)
    return b"".join(chunks)


def _parse_strl(buf: bytes, start: int, end: int, index: int):
    """One stream list: ``strh`` names the stream type, ``strf`` is the format
    (WAVEFORMATEX for audio) and an optional ``strn`` carries a display name."""
    is_audio = False
    fmt = None
    title = None

    pos = start
    while True:
        chunk = _chunk_at(buf, pos, end)
        if chunk is None:
            break
        chunk_id, size, body = chunk
        data = buf[body:min(body + size, end)]
        if chunk_id == b"strh":
            if len(data) >= 4 and data[0:4] == b"auds":
                is_audio = True
        elif chunk_id == b"strf":
            fmt = codecs.pcm.parse_waveformatex(data)
        elif chunk_id == b"strn":
            text = data.split(b"\0")[0].decode("latin-1").strip()
            if text:
                title = text
        nxt = _advance(pos, size, end)
        if nxt <= pos:
            break
        pos = nxt

    if not is_audio:
        return None

    track = Track(id=f"stream {index}", codec="audio", title=title)
    if fmt:
        track.codec = fmt.name or "audio"
        track.sample_rate = fmt.sample_rate
        track.bit_depth = fmt.bit_depth
        track.channels = fmt.channels
        track.lfe = fmt.lfe
    else:
        track.note = "audio stream with no readable strf format"
    return track


def _find_list(buf: bytes, start: int, end: int, want: bytes):
    """Find the first ``LIST`` of the given type, returning its content range."""
    pos = start
    while True:
        chunk = _chunk_at(buf, pos, end)
        if chunk is None:
            return None
        chunk_id, size, body = chunk
        if chunk_id == b"LIST" and buf[body:body + 4] == want:
            return body + 4, min(body + size, end)
        nxt = _advance(pos, size, end)
        if nxt <= pos:
            return None
        pos = nxt


def _chunk_at(buf: bytes, pos: int, end: int):
    """Return ``(id, declared body size, body start)`` for the chunk at ``pos``."""
    if pos + 8 > end:
        return None
    chunk_id = buf[pos:pos + 4]
    size = struct.unpack_from("<I", buf, pos + 4)[0]
    body = pos + 8
    if body > end:
        return None
    return chunk_id, size, body


def _advance(pos: int, size: int, end: int) -> int:
    """Advance past a chunk: header + body + RIFF's even-alignment pad byte."""
    return min(pos + 8 + size + (size & 1), end)
