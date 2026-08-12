"""Matroska/WebM track enumeration and audio frame extraction.

Matroska is read rather than scanned because it is the one container that
answers the question the consumer actually asks: which audio tracks are there,
*in order*, so an active track reported by the player can be matched to the one
read out of the bitstream.  Its Tracks element also supplies what the bitstream
does not -- language, and the declared rate and depth for formats that carry no
header of their own (PCM, and FLAC through its private data).

Reading is strictly sequential, in one pass from the start of the stream: the
consumer feeds this from a network share through the player's own VFS, where
seeking backwards is expensive and not always possible.  Tracks sits ahead of
the clusters in every muxer's output, so one pass is enough to enumerate the
tracks and then collect the first frames of each.
"""

import struct

from . import codecs as _codecs

# Element ids, kept with their length marker exactly as they appear.
_ID_EBML                 = 0x1A45DFA3
_ID_SEGMENT              = 0x18538067
_ID_TRACKS               = 0x1654AE6B
_ID_TRACK_ENTRY          = 0xAE
_ID_TRACK_NUMBER         = 0xD7
_ID_TRACK_TYPE           = 0x83
_ID_CODEC_ID             = 0x86
_ID_CODEC_PRIVATE        = 0x63A2
_ID_LANGUAGE             = 0x22B59C
_ID_LANGUAGE_BCP47       = 0x22B59D
_ID_AUDIO                = 0xE1
_ID_SAMPLING_FREQUENCY   = 0xB5
_ID_OUTPUT_SAMPLING_FREQ = 0x78B5
_ID_CHANNELS             = 0x9F
_ID_BIT_DEPTH            = 0x6264
_ID_CLUSTER              = 0x1F43B675
_ID_SIMPLE_BLOCK         = 0xA3
_ID_BLOCK_GROUP          = 0xA0
_ID_BLOCK                = 0xA1

_TRACK_TYPE_AUDIO = 2

# An "unknown size" master element (all value bits set) runs until its parent
# ends; Segment is routinely muxed that way, and Cluster is in streamed output.
_UNKNOWN_SIZE = object()

# Formats whose container header can disagree with what the frames actually
# carry, so their clusters are worth reading: DTS states its 48 kHz core rate
# in the header while the extension substream carries the real one, and
# TrueHD/MLP state theirs only in the bitstream.  Everything else is fully
# described where it sits and its clusters are skipped.
_BITSTREAM_CODECS = ("dts", "truehd", "mlp")

# Matroska codec ids mapped to the plain codec names the consumer matches on.
# Prefix matching, most specific first, so A_PCM/INT/LIT and friends resolve.
_CODEC_NAMES = (
    ("A_TRUEHD", "truehd"),
    ("A_MLP", "mlp"),
    ("A_DTS", "dts"),
    ("A_EAC3", "eac3"),
    ("A_AC3", "ac3"),
    ("A_FLAC", "flac"),
    ("A_ALAC", "alac"),
    ("A_WAVPACK4", "wavpack"),
    ("A_PCM", "pcm"),
    ("A_AAC", "aac"),
    ("A_OPUS", "opus"),
    ("A_VORBIS", "vorbis"),
    ("A_MPEG/L3", "mp3"),
    ("A_MPEG/L2", "mp2"),
    ("A_MPEG/L1", "mp1"),
)


def _codec_name(codec_id: str) -> str:
    """Return the plain codec name for a Matroska CodecID."""
    upper = (codec_id or "").upper()
    for prefix, name in _CODEC_NAMES:
        if upper.startswith(prefix):
            return name
    return (codec_id or "").lower()


class _Reader:
    """Sequential reader with a byte budget over a ``read(n)`` callable.

    ``pos`` counts every byte handed out, which is what the element walk uses
    to know where a master element ends -- EBML sizes cover the children's
    headers as well as their data, so counting consumed bytes is the only
    bookkeeping that stays right for nested elements.
    """

    def __init__(self, read, budget: int):
        self._read = read
        self._left = budget
        self.pos = 0
        self.exhausted = False

    def read(self, count: int) -> bytes:
        """Return exactly ``count`` bytes, or fewer at the end of the budget."""
        if count <= 0:
            return b""
        count = min(count, self._left)
        chunks = []
        want = count
        while want:
            chunk = self._read(want)
            if not chunk:
                self.exhausted = True
                break
            chunks.append(chunk)
            want -= len(chunk)
        data = b"".join(chunks)
        self._left -= len(data)
        self.pos += len(data)
        if self._left <= 0:
            self.exhausted = True
        return data

    def skip(self, count: int) -> None:
        """Discard ``count`` bytes without holding them all in memory."""
        while count > 0:
            chunk = self.read(min(count, 1 << 20))
            if not chunk:
                return
            count -= len(chunk)


def _read_vint(reader: _Reader, keep_marker: bool):
    """Read an EBML variable-length integer.

    Element ids keep their length marker -- that is what makes an id the id it
    is -- while sizes have it stripped.  Returns None at the end of the stream
    or on a malformed lead byte, and ``_UNKNOWN_SIZE`` for the all-ones size.
    """
    first = reader.read(1)
    if not first:
        return None
    byte = first[0]
    if byte == 0:
        return None                      # no valid EBML lead byte starts at 0

    length = 1
    mask = 0x80
    while not (byte & mask):
        mask >>= 1
        length += 1
        if length > 8:
            return None

    rest = reader.read(length - 1)
    if len(rest) != length - 1:
        return None

    value = byte if keep_marker else (byte & (mask - 1))
    for extra in rest:
        value = (value << 8) | extra

    if not keep_marker and value == (1 << (7 * length)) - 1:
        return _UNKNOWN_SIZE
    return value


def _read_element(reader: _Reader):
    """Read the next element header, returning ``(id, size)`` or None."""
    element_id = _read_vint(reader, keep_marker=True)
    if element_id is None:
        return None
    element_size = _read_vint(reader, keep_marker=False)
    if element_size is None:
        return None
    return element_id, element_size


def _to_uint(data: bytes) -> int:
    """Decode an EBML unsigned integer of any width."""
    value = 0
    for byte in data:
        value = (value << 8) | byte
    return value


def _to_float(data: bytes):
    """Decode an EBML float (4 or 8 bytes; an empty value means 0.0)."""
    if len(data) == 4:
        return struct.unpack(">f", data)[0]
    if len(data) == 8:
        return struct.unpack(">d", data)[0]
    if not data:
        return 0.0
    return None


def _to_str(data: bytes) -> str:
    """Decode an EBML string, dropping its NUL padding."""
    return data.split(b"\x00")[0].decode("utf-8", "replace")


def _parse_audio(reader: _Reader, size: int) -> dict:
    """Read a TrackEntry's Audio element into the fields it declares."""
    out: dict = {}
    end = reader.pos + size
    while reader.pos < end and not reader.exhausted:
        element = _read_element(reader)
        if element is None:
            break
        element_id, element_size = element
        if element_size is _UNKNOWN_SIZE:
            break
        data = reader.read(element_size)

        if element_id == _ID_SAMPLING_FREQUENCY:
            out["sample_rate"] = _to_float(data)
        elif element_id == _ID_OUTPUT_SAMPLING_FREQ:
            out["output_sample_rate"] = _to_float(data)
        elif element_id == _ID_CHANNELS:
            out["channels"] = _to_uint(data)
        elif element_id == _ID_BIT_DEPTH:
            out["bit_depth"] = _to_uint(data)
    return out


def _parse_track_entry(reader: _Reader, size: int) -> dict | None:
    """Read one TrackEntry, returning it only when it describes an audio track."""
    track: dict = {}
    end = reader.pos + size
    while reader.pos < end and not reader.exhausted:
        element = _read_element(reader)
        if element is None:
            return None
        element_id, element_size = element
        if element_size is _UNKNOWN_SIZE:
            return None

        if element_id == _ID_AUDIO:
            track["audio"] = _parse_audio(reader, element_size)
            continue

        data = reader.read(element_size)
        if element_id == _ID_TRACK_NUMBER:
            track["number"] = _to_uint(data)
        elif element_id == _ID_TRACK_TYPE:
            track["type"] = _to_uint(data)
        elif element_id == _ID_CODEC_ID:
            track["codec_id"] = _to_str(data)
        elif element_id == _ID_CODEC_PRIVATE:
            track["private"] = data
        elif element_id in (_ID_LANGUAGE, _ID_LANGUAGE_BCP47):
            track.setdefault("language", _to_str(data))

    # The stream ran out inside this entry, so every field in it is a guess --
    # a language cut to one letter, a codec id cut to nothing.  Half an entry
    # is worse than none: it would be reported as a real track with empty
    # values and take the place of the track it was meant to describe.
    if reader.pos < end:
        return None
    if track.get("type") != _TRACK_TYPE_AUDIO:
        return None
    if not track.get("codec_id"):
        return None
    return track


def _parse_tracks(reader: _Reader, size: int) -> list[dict]:
    """Read the Tracks element into its audio tracks, in declaration order."""
    tracks = []
    end = reader.pos + size
    while reader.pos < end and not reader.exhausted:
        element = _read_element(reader)
        if element is None:
            break
        element_id, element_size = element
        if element_size is _UNKNOWN_SIZE:
            break

        if element_id == _ID_TRACK_ENTRY:
            track = _parse_track_entry(reader, element_size)
            if track is not None:
                tracks.append(track)
        else:
            reader.skip(element_size)
    return tracks


def _block_frame_offset(payload: bytes):
    """Return ``(track number, offset of the frame data)`` for a block payload."""
    if not payload:
        return None
    byte = payload[0]
    if byte == 0:
        return None
    length = 1
    mask = 0x80
    while not (byte & mask):
        mask >>= 1
        length += 1
        if length > 8:
            return None
    if len(payload) < length + 3:
        return None

    number = byte & (mask - 1)
    for extra in payload[1:length]:
        number = (number << 8) | extra
    # Track number VINT, 16-bit timecode, 8-bit flags, then the frame data.
    # Any lacing headers are left in front of it on purpose: the codec parsers
    # search for their own sync word, so a few bytes of lacing change nothing.
    return number, length + 3


def parse(read, budget: int):
    """Return the audio tracks of a Matroska stream, or None if it is not one.

    ``read(n)`` supplies bytes sequentially and ``budget`` caps how many are
    ever pulled, so a stream whose clusters never yield a readable frame still
    terminates.  Each track carries what Tracks declared and, once one of its
    frames has been read, what its bitstream declares -- the bitstream wins,
    since disagreeing with the container is the reason for reading it.
    """
    reader = _Reader(read, budget)

    element = _read_element(reader)
    if element is None or element[0] != _ID_EBML:
        return None                      # not Matroska; the caller falls back
    if element[1] is _UNKNOWN_SIZE:
        return None
    reader.skip(element[1])

    tracks: list[dict] = []
    by_number: dict[int, dict] = {}
    pending: set = set()

    while not reader.exhausted:
        element = _read_element(reader)
        if element is None:
            break
        element_id, element_size = element

        # Master elements we walk into: their children follow inline, so the
        # size is simply not consumed.
        if element_id in (_ID_SEGMENT, _ID_CLUSTER, _ID_BLOCK_GROUP):
            continue
        if element_size is _UNKNOWN_SIZE:
            continue

        if element_id == _ID_TRACKS:
            tracks = _parse_tracks(reader, element_size)
            by_number = {t["number"]: t for t in tracks if "number" in t}
            pending = {
                number for number, track in by_number.items()
                if _codec_name(track.get("codec_id")) in _BITSTREAM_CODECS
            }
            if not pending:
                break                    # nothing left that the frames could add
            continue

        if element_id in (_ID_SIMPLE_BLOCK, _ID_BLOCK) and pending:
            payload = reader.read(element_size)
            header = _block_frame_offset(payload)
            if header is None:
                continue
            number, offset = header
            if number in pending:
                parsed = _codecs.parse_frame(payload[offset:])
                if parsed:
                    by_number[number]["bitstream"] = parsed
                    pending.discard(number)
                    if not pending:
                        break
            continue

        reader.skip(element_size)

    if not tracks:
        return None
    return [_finish(track) for track in tracks]


def _finish(track: dict) -> dict:
    """Flatten one parsed track into the result shape."""
    audio = track.get("audio") or {}
    bitstream = track.get("bitstream") or {}
    codec = _codec_name(track.get("codec_id"))

    rate = bitstream.get("sample_rate")
    if not rate:
        rate = audio.get("output_sample_rate") or audio.get("sample_rate")
    bit_depth = bitstream.get("bit_depth") or audio.get("bit_depth")
    channels = audio.get("channels") or bitstream.get("channels")

    # FLAC states everything in its private data, which is the STREAMINFO block
    # the container would otherwise only paraphrase.
    if codec == "flac" and track.get("private"):
        flac = _codecs.parse_flac_streaminfo(track["private"])
        if flac:
            rate = flac["sample_rate"]
            bit_depth = flac["bit_depth"]
            channels = channels or flac["channels"]

    return {
        "codec": codec,
        "sample_rate": int(rate) if rate else None,
        "bit_depth": bit_depth or None,
        "channels": channels or None,
        "language": track.get("language") or "und",
    }
