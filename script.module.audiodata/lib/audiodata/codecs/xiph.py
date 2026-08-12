"""Opus and Vorbis identification headers."""

import struct

from ..codecinfo import CodecInfo


def parse_opus_head(data: bytes):
    """Parse an OpusHead structure (Matroska CodecPrivate, Ogg first packet)."""
    if data is None:
        return None
    pos = data.find(b"OpusHead")
    if pos == -1:
        return None
    b = data[pos:]
    if len(b) < 19:
        return None

    channels = b[9]
    input_rate = struct.unpack_from("<I", b, 12)[0]
    note = None
    if input_rate not in (0, 48000):
        note = f"original input rate {input_rate} Hz"

    return CodecInfo(
        name="Opus",
        sample_rate=48000,           # Opus always decodes at 48 kHz
        channels=channels or None,
        note=note,
    )


def parse_vorbis(data: bytes):
    """Parse a Vorbis identification header (packet type 1)."""
    if data is None:
        return None
    pos = data.find(b"\x01vorbis")
    if pos == -1:
        return None
    b = data[pos:]
    if len(b) < 16:
        return None

    channels = b[11]
    rate = struct.unpack_from("<I", b, 12)[0]
    if rate == 0:
        return None

    return CodecInfo(name="Vorbis", sample_rate=rate,
                     channels=channels or None)
