"""Container detection and dispatch, plus probers for the simple formats
(FLAC, WAV, Ogg and raw elementary streams).

The format is sniffed from the head of the stream rather than from a file
name, so a Kodi VFS URL, a pipe and a plain path all resolve the same way.
"""

from .. import codecs
from ..report import Report, Track
from . import avi, mp4, matroska, mpegps, mpegts
from . import iso  # noqa: E402  imported last: it builds on mpegts/mpegps

__all__ = ["avi", "iso", "matroska", "mp4", "mpegps", "mpegts",
           "probe_source", "sniffs_as_ts", "looks_like_ts"]

_HEAD_BYTES = 64 * 1024
_ELEMENTARY_BYTES = 1024 * 1024

_MP4_BRANDS = (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip")

# Extension gives the priority order for a raw elementary stream; the magic
# scan does the real work.
_ELEMENTARY_CANDIDATES = {
    "ac3": ("ac3",), "eac3": ("ac3",), "ec3": ("ac3",),
    "dts": ("dts",), "dtshd": ("dts",), "dtsma": ("dts",), "dtshr": ("dts",),
    "thd": ("truehd",), "truehd": ("truehd",), "mlp": ("truehd",),
    "aac": ("aac", "latm"), "adts": ("aac", "latm"),
    "latm": ("latm", "aac"), "loas": ("latm", "aac"),
    "mp3": ("mpeg",), "mp2": ("mpeg",), "mp1": ("mpeg",), "mpa": ("mpeg",),
}
_ELEMENTARY_DEFAULT = ("ac3", "dts", "truehd", "aac", "mpeg")


def probe_source(source, file_len: int, scan_limit: int, deep: bool,
                 extension: str = ""):
    """Sniff ``source`` and dispatch to the backend that fits it.

    ``source`` is a seekable file-like object; ``extension`` only orders the
    candidates for a raw elementary stream, where there is no magic to sniff.
    """
    source.seek(0)
    magic = _read_up_to(source.read, 16)

    if magic.startswith(b"\x1a\x45\xdf\xa3"):
        source.seek(0)
        return matroska.probe(source, file_len, deep)

    if len(magic) >= 12 and magic[4:8] in _MP4_BRANDS:
        return mp4.probe(source, file_len)

    if magic.startswith(b"fLaC") or (magic.startswith(b"ID3")
                                     and _is_flac_after_id3(source)):
        return _probe_flac(source)

    if magic.startswith(b"RIFF") and len(magic) >= 12:
        if magic[8:12] == b"WAVE":
            return _probe_wav(source)
        if magic[8:12] == b"AVI ":
            source.seek(0)
            return avi.probe(source.read, file_len)

    if magic.startswith(b"OggS"):
        return _probe_ogg(source)

    # MPEG program stream (DVD VOB / .mpg / .mpeg): pack-header start code.
    if magic.startswith(b"\x00\x00\x01\xba"):
        source.seek(0)
        return mpegps.probe(source.read, scan_limit)

    # MPEG-TS detection needs a larger window (a sync-pattern check).
    source.seek(0)
    head = _read_up_to(source.read, 4096)
    if looks_like_ts(head):
        source.seek(0)
        return mpegts.probe(source.read, scan_limit)

    return _probe_elementary(source, extension)


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


def sniffs_as_ts(head: bytes) -> bool:
    """Whether a sniff block dispatches to the MPEG-TS backend.

    Mirrors the gate in ``probe_source`` so a caller sizing a head budget
    agrees with the backend the dispatcher will actually pick: TS metadata
    rides deeper into the stream than a container header, so it earns a
    larger budget.
    """
    if (head.startswith(b"\x1a\x45\xdf\xa3")
            or (len(head) >= 12 and head[4:8] in _MP4_BRANDS)
            or head.startswith(b"fLaC")
            or head.startswith(b"ID3")
            or (head.startswith(b"RIFF") and len(head) >= 12 and head[8:12] == b"WAVE")
            or head.startswith(b"OggS")):
        return False
    return looks_like_ts(head)


def looks_like_ts(head: bytes) -> bool:
    """Whether a head block carries a repeating transport-stream sync pattern."""
    for size in (188, 192, 204):
        for start in range(min(size, len(head))):
            if len(head) < start + size * 4 + 1:
                break
            if all(head[start + i * size] == 0x47 for i in range(5)):
                return True
    return False


def _synchsafe(b: bytes) -> int:
    value = 0
    for byte in b:
        value = (value << 7) | (byte & 0x7F)
    return value


def _is_flac_after_id3(source) -> bool:
    """Whether a FLAC stream follows an ID3 tag at the head of the source."""
    try:
        source.seek(0)
        header = _read_up_to(source.read, 10)
        if len(header) < 10:
            return False
        source.seek(10 + _synchsafe(header[6:10]))
        return _read_up_to(source.read, 4) == b"fLaC"
    except Exception:
        return False
    finally:
        try:
            source.seek(0)
        except Exception:
            pass


def _single_track_report(container: str, info) -> Report:
    return Report(container=container, tracks=[Track(
        id="1",
        codec=info.name or container,
        sample_rate=info.sample_rate,
        bit_depth=info.bit_depth,
        channels=info.channels,
        lfe=info.lfe,
        note=info.note,
        default=True,
    )])


def _probe_flac(source) -> Report:
    source.seek(0)
    head = _read_up_to(source.read, _HEAD_BYTES)
    start = 10 + _synchsafe(head[6:10]) if head.startswith(b"ID3") else 0
    info = codecs.flac.parse(head[start:])
    if info is None:
        raise ValueError("invalid FLAC STREAMINFO")
    return _single_track_report("FLAC", info)


def _probe_wav(source) -> Report:
    import struct

    source.seek(0)
    head = _read_up_to(source.read, _HEAD_BYTES)
    pos = 12
    while pos + 8 <= len(head):
        chunk_id = head[pos:pos + 4]
        length = struct.unpack_from("<I", head, pos + 4)[0]
        if chunk_id == b"fmt ":
            info = codecs.pcm.parse_waveformatex(head[pos + 8:pos + 8 + length])
            if info is None:
                raise ValueError("invalid WAV fmt chunk")
            extensible = head[pos + 8:pos + 10] == b"\xfe\xff"
            return _single_track_report(
                "WAV (extensible)" if extensible else "WAV", info)
        pos += 8 + length + (length & 1)
    raise ValueError("no fmt chunk found in WAV file")


def _probe_ogg(source) -> Report:
    source.seek(0)
    head = _read_up_to(source.read, _HEAD_BYTES)
    info = codecs.xiph.parse_opus_head(head) or codecs.xiph.parse_vorbis(head)
    if info is None:
        # Ogg FLAC: "\x7fFLAC" + version + header count, then the native stream.
        at = head.find(b"\x7fFLAC")
        if at != -1:
            info = codecs.flac.parse(head[at + 9:])
    if info is None:
        raise ValueError("unsupported Ogg stream (no Opus/Vorbis/FLAC header found)")
    return _single_track_report("Ogg", info)


def _probe_elementary(source, extension: str) -> Report:
    source.seek(0)
    buf = _read_up_to(source.read, _ELEMENTARY_BYTES)
    start = min(10 + _synchsafe(buf[6:10]), len(buf)) if buf.startswith(b"ID3") else 0
    data = buf[start:]

    candidates = _ELEMENTARY_CANDIDATES.get(extension.lower().lstrip("."),
                                            _ELEMENTARY_DEFAULT)
    for candidate in candidates:
        info = {
            "ac3": codecs.ac3.parse,
            "dts": codecs.dts.parse,
            "truehd": codecs.truehd.parse,
            "aac": codecs.aac.parse_adts,
            "latm": codecs.aac.parse_loas_latm,
            "mpeg": codecs.mpeg_audio.parse,
        }[candidate](data)
        if info:
            name = info.name or "audio"
            report = _single_track_report(f"{name} elementary stream", info)
            report.tracks[0].codec = name
            return report
    raise ValueError("unrecognized file format")
