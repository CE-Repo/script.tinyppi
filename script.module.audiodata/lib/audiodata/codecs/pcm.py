"""PCM variants: Blu-ray (HDMV) and DVD LPCM headers, WAVEFORMATEX, ALAC.

These are the formats that carry a real bit depth and no compression, so their
headers are the only place the depth exists at all -- a player passing them
through reports whatever its sink is set to.
"""

import struct

from ..codecinfo import CodecInfo


def parse_hdmv_lpcm(payload: bytes):
    """Parse the 4-byte HDMV LPCM audio data header that starts every PES
    packet of a Blu-ray LPCM stream (stream_type 0x80)."""
    if len(payload) < 4:
        return None
    channel_assignment = payload[2] >> 4
    sampling_frequency = payload[2] & 0xF
    bits_per_sample = payload[3] >> 6

    rate = {1: 48000, 4: 96000, 5: 192000}.get(sampling_frequency)
    depth = {1: 16, 2: 20, 3: 24}.get(bits_per_sample)
    channels = {1: 1, 3: 2, 4: 3, 5: 3, 6: 4, 7: 4, 8: 5,
                9: 6, 10: 7, 11: 8}.get(channel_assignment)
    if rate is None or depth is None or channels is None:
        return None

    return CodecInfo(
        name="LPCM (Blu-ray)",
        sample_rate=rate,
        bit_depth=depth,
        channels=channels,
        lfe=channel_assignment in (9, 11),
    )


def parse_dvd_lpcm(hdr: bytes):
    """Parse the DVD-Video LPCM audio header that follows the sub-stream id in
    each ``private_stream_1`` PES packet of an LPCM stream (sub-stream id
    0xA0..0xA7).  ``hdr`` is the bytes after the sub-stream id."""
    if len(hdr) < 5:
        return None
    # hdr[0]    number of audio frame headers
    # hdr[1:3]  first access unit pointer
    # hdr[3]    emphasis / mute / reserved / frame number
    # hdr[4]    quantization(2) | sampling frequency(2) | reserved(1) | channels-1(3)
    quant = hdr[4] >> 6
    fs = (hdr[4] >> 4) & 0x3
    channels = (hdr[4] & 0x7) + 1

    depth = {0: 16, 1: 20, 2: 24}.get(quant)
    rate = {0: 48000, 1: 96000}.get(fs)   # DVD-Video LPCM is 48 or 96 kHz only
    if depth is None or rate is None:
        return None

    return CodecInfo(name="LPCM (DVD)", sample_rate=rate, bit_depth=depth,
                     channels=channels, lfe=False)


_WAVE_TAGS = {
    0x0001: ("PCM", True),
    0x0003: ("PCM (float)", True),
    0x0006: ("A-law", False),
    0x0007: ("µ-law", False),
    0x0050: ("MP2", False),
    0x0055: ("MP3", False),
    0x00FF: ("AAC", False),
    0x2000: ("AC-3", False),
    0x2001: ("DTS", False),
    0x0161: ("WMA", False),
    0x0162: ("WMA Pro", False),
    0x0164: ("WMA Lossless", False),
}


def parse_waveformatex(b: bytes):
    """Parse a WAVEFORMATEX structure (a WAV ``fmt `` chunk, a Matroska
    A_MS/ACM CodecPrivate), including WAVE_FORMAT_EXTENSIBLE."""
    if b is None or len(b) < 16:
        return None

    def u16(offset):
        return struct.unpack_from("<H", b, offset)[0]

    tag = u16(0)
    channels = u16(2)
    rate = struct.unpack_from("<I", b, 4)[0]
    bits = u16(14)

    if tag == 0xFFFE and len(b) >= 26:
        # WAVE_FORMAT_EXTENSIBLE: wValidBitsPerSample + SubFormat GUID
        valid_bits = u16(20)
        if valid_bits > 0:
            bits = valid_bits
        tag = u16(24)                 # first two bytes of the SubFormat GUID

    name, is_pcm = _WAVE_TAGS.get(tag, ("PCM/ACM", False))
    if rate == 0 or channels == 0:
        return None

    return CodecInfo(
        name=name,
        sample_rate=rate,
        bit_depth=bits if (is_pcm and bits > 0) else None,
        channels=channels,
    )


def parse_alac_config(b: bytes):
    """Parse an ALACSpecificConfig (Matroska CodecPrivate, MP4 ``alac`` box)."""
    if b is None or len(b) < 24:
        return None
    depth = b[5]
    channels = b[9]
    rate = struct.unpack_from(">I", b, 20)[0]
    if depth not in (16, 20, 24, 32) or rate == 0 or not 0 < channels <= 8:
        return None
    return CodecInfo(name="ALAC", sample_rate=rate, bit_depth=depth,
                     channels=channels)
