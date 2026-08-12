"""audiodata: read what an audio track really is from its own bitstream.

A player reports the audio format it is feeding its sink, not the one the file
carries.  During passthrough that means no PCM bit depth at all, and a DTS-HD
track reports the 48 kHz core every decoder can fall back to rather than the
96 kHz the extension substream actually stores.  This package reads those
numbers out of the stream itself, so an overlay can show the source rather than
the sink.

Public entry point: ``probe(read, budget=...) -> list[dict]``, one entry per
audio track:

    {'codec': str, 'sample_rate': int|None, 'bit_depth': int|None,
     'channels': int|None, 'language': str}

Two ways of getting there, picked from what the stream turns out to be:

* **Matroska** is parsed properly -- its Tracks element gives every audio track
  in declaration order, which is what lets a caller match the track a player
  says is active against the one read here.
* **Anything else** (MPEG-TS/M2TS, MP4, a raw elementary stream) is scanned for
  the codecs' own sync words, yielding one entry per codec family found rather
  than per track.  A caller that matches on codec family still resolves it;
  one that needs track order does not, and should treat the result as the
  best available reading rather than an enumeration.

Reading is sequential and budgeted: ``read(n)`` is called until the budget is
spent or every track has answered, and nothing larger than one chunk is held.
Nothing here raises -- a stream that cannot be read yields ``[]``, which the
caller is expected to treat as "no reading", not as "no audio".

Pure stdlib, no player API, so every parser is testable off the device.
"""

from . import codecs as _codecs
from . import matroska as _matroska

__all__ = ["probe", "DEFAULT_BUDGET"]

# How much of a stream is ever read.  A Matroska file answers within the first
# cluster or two; the scan path needs enough to pass whatever leading structure
# a container puts in front of its first audio frame.  Matched to what the
# binary this replaces was measured to take of a UHD stream.
DEFAULT_BUDGET = 16 * 1024 * 1024

# Chunk size for the scan path.  Overlapped by the longest sync word minus one
# so a header never hides in the seam between two chunks.
_SCAN_CHUNK = 1024 * 1024
_SCAN_OVERLAP = 4096

# How much of the Matroska attempt is retained so the scan can replay it.
_REWIND_LIMIT = 256 * 1024


def probe(read, budget: int = DEFAULT_BUDGET) -> list[dict]:
    """Return the audio tracks a stream declares in its own bitstream.

    ``read(n)`` must return up to ``n`` bytes and ``b''`` at the end of the
    stream; it is only ever called forwards.  Returns ``[]`` when the stream
    holds nothing recognisable.
    """
    try:
        return _probe(read, budget)
    except Exception:
        # A reader that fails midway, a container that lies about its sizes:
        # either way the answer is "no reading", never an exception into a
        # caller that is only trying to label a row on screen.
        return []


def _probe(read, budget: int) -> list[dict]:
    buffered = _Rewindable(read)

    tracks = _matroska.parse(buffered.read, budget)
    if tracks:
        return tracks

    # Not Matroska (or it yielded nothing): scan from the top for sync words.
    buffered.rewind()
    return _scan(buffered.read, budget)


def _scan(read, budget: int) -> list[dict]:
    """Return one entry per codec family whose header is found in the stream."""
    found: dict[str, dict] = {}
    tail = b""
    left = budget

    while left > 0:
        chunk = read(min(_SCAN_CHUNK, left))
        if not chunk:
            break
        left -= len(chunk)

        window = tail + chunk
        for family, reading in _codecs.scan_families(window).items():
            found.setdefault(family, reading)

        # Carry the seam so a header split across two chunks is still seen.
        tail = window[-_SCAN_OVERLAP:]

    return [
        {
            "codec": family,
            "sample_rate": reading.get("sample_rate"),
            "bit_depth": reading.get("bit_depth"),
            "channels": reading.get("channels"),
            "language": "und",
        }
        for family, reading in found.items()
    ]


class _Rewindable:
    """A forward reader that can be replayed once from the start.

    The Matroska attempt has to be able to give up and let the scan start over
    from the top, on a source that cannot seek.  What the first pass read is
    kept until then -- but only up to ``_REWIND_LIMIT``, since a stream that
    turns out to be Matroska is read far past any point worth holding.  Beyond
    that the head is dropped and the scan simply continues forwards from where
    the first pass stopped, which still finds every sync word after it.
    """

    def __init__(self, read):
        self._read = read
        self._log: list[bytes] = []
        self._logged = 0
        self._replay = b""
        self._recording = True

    def read(self, count: int) -> bytes:
        if self._replay:
            out = self._replay[:count]
            self._replay = self._replay[len(out):]
            return out
        data = self._read(count)
        if self._recording and data:
            self._log.append(data)
            self._logged += len(data)
            if self._logged > _REWIND_LIMIT:
                self._log = []
                self._recording = False
        return data

    def rewind(self) -> None:
        """Replay what was retained, then continue reading the source."""
        self._replay = b"".join(self._log)
        self._log = []
        self._recording = False
