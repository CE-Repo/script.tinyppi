"""FLAC STREAMINFO parsing."""

from ..codecinfo import CodecInfo


def parse(data: bytes):
    """Parse FLAC stream info from ``data``.

    The buffer may start with the ``fLaC`` marker (native files, an MP4 dfLa
    payload, a Matroska CodecPrivate) or directly with a metadata block header.
    Metadata blocks are walked until STREAMINFO (type 0) is found.
    """
    if data is None:
        return None
    pos = 4 if data[:4] == b"fLaC" else 0
    while True:
        if pos + 4 > len(data):
            return None
        block_type = data[pos] & 0x7F
        last = bool(data[pos] & 0x80)
        length = (data[pos + 1] << 16) | (data[pos + 2] << 8) | data[pos + 3]
        pos += 4
        if block_type == 0:
            block = data[pos:pos + max(length, 18)]
            return _parse_streaminfo(block)
        if last:
            return None
        pos += length


def _parse_streaminfo(b: bytes):
    if len(b) < 18:
        return None
    # bytes 10..13: sample rate (20 bits), channels-1 (3 bits), bps-1 (5 bits)
    rate = (b[10] << 12) | (b[11] << 4) | (b[12] >> 4)
    channels = ((b[12] >> 1) & 0x7) + 1
    bps = (((b[12] & 1) << 4) | (b[13] >> 4)) + 1
    if rate == 0:
        return None
    return CodecInfo(name="FLAC", sample_rate=rate, bit_depth=bps,
                     channels=channels)
