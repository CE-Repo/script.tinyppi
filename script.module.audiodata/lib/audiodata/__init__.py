"""audiodata: read what an audio track really is from its own bitstream.

A player reports the audio format it is feeding its sink, not the one the file
carries.  During passthrough that means no PCM bit depth at all, and a DTS-HD
track reports the 48 kHz core every decoder can fall back to rather than the
96 kHz its extension substream actually stores.  This package reads those
numbers out of the stream itself, so an overlay can show the source rather than
the sink.

Containers are parsed natively -- Matroska/WebM, MPEG-TS and BDAV M2TS, MP4/MOV,
AVI, MPEG program streams, FLAC, WAV and Ogg -- down to the audio track table,
and the codec sync headers are parsed from the frames those tables point at.
Blu-ray and DVD-Video disc images are walked to their main feature first.

Public entry points:

    probe(source, ...) -> Report          full result model
    probe_tracks(source, ...) -> [dict]   the same, as plain dicts

``source`` is a seekable file-like object (anything with ``read`` and
``seek``), a ``bytes`` buffer, or a filesystem path.  Neither entry point
raises: a source that cannot be read yields an empty result carrying the
reason, which callers should read as "no reading", not as "no audio".

Pure stdlib, no binaries and no native libraries, so every parser is testable
off the device.
"""

import io
import os

from . import containers
from .codecinfo import CodecInfo
from .report import Report, Track

__all__ = ["probe", "probe_tracks", "parse_playlist", "Report", "Track",
           "CodecInfo", "DEFAULT_SCAN_LIMIT"]

# How far into a transport or program stream the audio PES is followed.  Audio
# metadata rides much deeper into those than a container header does, which is
# what this budget is for; a Matroska or MP4 file answers long before it.
DEFAULT_SCAN_LIMIT = 64 * 1024 * 1024


def probe(source, scan_limit: int = DEFAULT_SCAN_LIMIT, deep: bool = True,
          extension: str = "") -> Report:
    """Read a source and return its Report.

    ``deep`` samples frames out of the container for the codecs whose header
    the container states incompletely; turning it off keeps only what the
    container itself declares.  ``extension`` (e.g. ``"dts"``) only orders the
    candidates for a raw elementary stream, which carries no magic to sniff.
    """
    try:
        return _probe(source, scan_limit, deep, extension)
    except Exception as exc:
        # A reader that fails midway, a container that lies about its sizes:
        # either way the answer is "no reading", never an exception into a
        # caller that is only trying to label a row on screen.
        return Report(error=str(exc) or exc.__class__.__name__)


def probe_tracks(source, **kwargs) -> list:
    """Return just the audio tracks, as plain dicts.  Empty on any failure."""
    return [track.as_dict() for track in probe(source, **kwargs).tracks]


def parse_playlist(data):
    """Parse a Blu-ray ``.mpls`` playlist, or return None.

    Exposed because a caller reading a disc through a player's own filesystem
    layer -- rather than from an image this package can walk -- still has to
    map the title the viewer picked onto the clip that carries it.  The result
    carries the PlayItems in order, plus ``distinct_clips()`` and
    ``duration_secs_deduped()`` for ranking them.
    """
    try:
        return containers.iso.mpls.parse(bytes(data))
    except Exception:
        return None


def _probe(source, scan_limit: int, deep: bool, extension: str) -> Report:
    close_after = False

    if isinstance(source, (bytes, bytearray, memoryview)):
        handle, length = io.BytesIO(bytes(source)), len(source)
    elif isinstance(source, str):
        handle = open(source, "rb")       # noqa: SIM115 - closed in the finally
        close_after = True
        length = os.fstat(handle.fileno()).st_size
        extension = extension or os.path.splitext(source)[1]
    else:
        handle = source
        length = _source_length(handle)

    try:
        # A disc image is dispatched by absolute byte range: the main feature
        # sits far from any front magic, so it needs random access rather than
        # the sniff-and-stream path every other container takes.
        image = containers.iso.Image(handle, length)
        if containers.iso.looks_like_iso(image):
            return containers.iso.probe(image, length, scan_limit, deep)
        return containers.probe_source(handle, length, scan_limit, deep,
                                       extension)
    finally:
        if close_after:
            handle.close()


def _source_length(handle) -> int:
    """Return the byte length of a source, however it reports one."""
    for attr in ("size", "getSize"):
        method = getattr(handle, attr, None)
        if callable(method):
            try:
                value = method()
                if value:
                    return int(value)
            except Exception:
                pass
    try:
        pos = handle.tell() if hasattr(handle, "tell") else 0
        handle.seek(0, os.SEEK_END)
        end = handle.tell() if hasattr(handle, "tell") else 0
        handle.seek(pos)
        if end:
            return int(end)
    except Exception:
        pass
    # Unknown: a length only bounds the container walks, so an optimistic
    # ceiling is better than a zero that would stop them before they start.
    return 1 << 62
