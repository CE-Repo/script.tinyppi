"""Synthetic bitstream builders for the tests.

Each builder writes the field layout the matching parser reads, so a test can
state the values it wants back and assert they survive the round trip.  This
proves the parsers agree with the layouts documented in codecs.py; it does not
prove those layouts match a real encoder's output, which only a real stream
can show.
"""

import struct


class BitWriter:
    """MSB-first bit writer, the mirror of bitreader.BitReader."""

    def __init__(self):
        self._bits: list[int] = []

    def write(self, value: int, count: int) -> "BitWriter":
        for shift in range(count - 1, -1, -1):
            self._bits.append((value >> shift) & 1)
        return self

    def bytes(self) -> bytes:
        bits = list(self._bits)
        while len(bits) % 8:
            bits.append(0)
        out = bytearray()
        for index in range(0, len(bits), 8):
            byte = 0
            for bit in bits[index:index + 8]:
                byte = (byte << 1) | bit
            out.append(byte)
        return bytes(out)


def dts_exss(sample_rate_index=13, bit_depth=24, channels=8,
             exss_index=0, header_size=20, exss_size=2048,
             asset_type=False, language=False, text=None):
    """Build a DTS extension substream header (default: 96 kHz, 24-bit, 8ch)."""
    w = BitWriter()
    w.write(0x64582025, 32)          # sync
    w.write(0, 8)                    # user defined bits
    w.write(exss_index, 2)
    w.write(0, 1)                    # short header size type
    w.write(header_size - 1, 8)
    w.write(exss_size - 1, 16)

    w.write(1, 1)                    # static fields present
    w.write(0, 2)                    # reference clock code
    w.write(0, 3)                    # frame duration code
    w.write(0, 1)                    # no timecode
    w.write(0, 3)                    # one audio presentation
    w.write(0, 3)                    # one audio asset
    w.write(1, exss_index + 1)       # active substream mask
    w.write(0, 8)                    # active asset mask for substream 0
    w.write(0, 1)                    # no mixing metadata

    w.write(1023, 20)                # asset size

    w.write(63, 9)                   # asset descriptor size
    w.write(0, 3)                    # asset index
    w.write(1 if asset_type else 0, 1)
    if asset_type:
        w.write(0, 4)
    w.write(1 if language else 0, 1)
    if language:
        w.write(0, 24)
    w.write(1 if text is not None else 0, 1)
    if text is not None:
        w.write(text - 1, 10)
        w.write(0, text * 8)
    w.write(bit_depth - 1, 5)
    w.write(sample_rate_index, 4)
    w.write(channels - 1, 8)
    w.write(0, 64)                   # trailing descriptor bytes
    return w.bytes()


def dts_core(sfreq_index=13, nblks=15, fsize=2013):
    """Build a DTS core frame header (default: 48 kHz)."""
    w = BitWriter()
    w.write(0x7FFE8001, 32)
    w.write(0, 1)                    # frame type
    w.write(0, 5)                    # deficit sample count
    w.write(0, 1)                    # CRC present
    w.write(nblks, 7)
    w.write(fsize, 14)
    w.write(0, 6)                    # channel arrangement
    w.write(sfreq_index, 4)
    w.write(0, 32)
    return w.bytes()


def truehd(rate_code=2):
    """Build a TrueHD major sync header (default rate code 2 = 192 kHz)."""
    w = BitWriter()
    w.write(0xF8726FBA, 32)
    w.write(rate_code, 4)
    w.write(0, 4)
    w.write(0, 32)
    return w.bytes()


def mlp(quant_code=2, rate_code=0):
    """Build an MLP major sync header (default 24-bit, 48 kHz)."""
    w = BitWriter()
    w.write(0xF8726FBB, 32)
    w.write(quant_code, 4)
    w.write(0, 4)
    w.write(rate_code, 4)
    w.write(0, 4)
    w.write(0, 32)
    return w.bytes()


def flac_streaminfo(sample_rate=96000, bit_depth=24, channels=2, magic=True):
    """Build a FLAC STREAMINFO metadata block."""
    w = BitWriter()
    w.write(0, 1)                    # not the last metadata block
    w.write(0, 7)                    # block type STREAMINFO
    w.write(34, 24)                  # block length
    w.write(4096, 16)                # min block size
    w.write(4096, 16)                # max block size
    w.write(0, 24)                   # min frame size
    w.write(0, 24)                   # max frame size
    w.write(sample_rate, 20)
    w.write(channels - 1, 3)
    w.write(bit_depth - 1, 5)
    w.write(0, 36)                   # total samples
    w.write(0, 128)                  # md5
    body = w.bytes()
    return (b"fLaC" + body) if magic else body


def ac3(fscod=0, bsid=8):
    """Build an AC-3 sync frame header (default 48 kHz)."""
    w = BitWriter()
    w.write(0x0B77, 16)
    w.write(0, 16)                   # crc1
    w.write(fscod, 2)
    w.write(0, 6)                    # frame size code
    w.write(bsid, 5)
    w.write(0, 32)
    return w.bytes()


def eac3(fscod=0, fscod2=0, bsid=16):
    """Build an E-AC-3 sync frame header (default 48 kHz)."""
    w = BitWriter()
    w.write(0x0B77, 16)
    w.write(0, 2)                    # stream type
    w.write(0, 3)                    # substream id
    w.write(0, 11)                   # frame size
    w.write(fscod, 2)
    if fscod == 3:
        w.write(fscod2, 2)
    else:
        w.write(0, 2)                # numblkscod
    w.write(0, 3)                    # acmod
    w.write(0, 1)                    # lfeon
    w.write(bsid, 5)
    w.write(0, 32)
    body = bytearray(w.bytes())
    # bsid lives at a fixed bit offset from the sync word, which the parser
    # reads directly; place it there regardless of the fields written above.
    return _with_bsid(bytes(body), bsid)


def _with_bsid(frame: bytes, bsid: int) -> bytes:
    """Overwrite the 5 bits at bit offset 40, where both AC-3 flavours put bsid."""
    out = bytearray(frame)
    out[5] = ((bsid & 0x1F) << 3) | (out[5] & 0x07)
    return bytes(out)


# --- Matroska --------------------------------------------------------------

def vint(value: int, length: int = 0) -> bytes:
    """Encode an EBML size as a variable-length integer."""
    if not length:
        length = 1
        while value >= (1 << (7 * length)) - 1:
            length += 1
    marker = 1 << (7 * length)
    return (marker | value).to_bytes(length, "big")


def element(element_id: int, payload: bytes) -> bytes:
    """Encode one EBML element from its id and already-encoded payload."""
    id_len = max(1, (element_id.bit_length() + 7) // 8)
    return element_id.to_bytes(id_len, "big") + vint(len(payload)) + payload


def uint(value: int) -> bytes:
    """Encode an EBML unsigned integer."""
    return value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")


def f64(value: float) -> bytes:
    """Encode an EBML 64-bit float."""
    return struct.pack(">d", value)


def track_entry(number, codec_id, language="und", rate=48000.0, channels=6,
                bit_depth=None, private=None):
    """Build one audio TrackEntry."""
    audio = element(0xB5, f64(rate)) + element(0x9F, uint(channels))
    if bit_depth:
        audio += element(0x6264, uint(bit_depth))
    body = (
        element(0xD7, uint(number))
        + element(0x83, uint(2))                     # TrackType audio
        + element(0x86, codec_id.encode())
        + element(0x22B59C, language.encode())
        + element(0xE1, audio)
    )
    if private is not None:
        body += element(0x63A2, private)
    return element(0xAE, body)


def simple_block(track_number: int, frame: bytes) -> bytes:
    """Build a SimpleBlock carrying one frame for a track."""
    return element(0xA3, vint(track_number, 1) + b"\x00\x00" + b"\x80" + frame)


def matroska(entries, blocks=()):
    """Build a minimal Matroska stream from track entries and cluster blocks."""
    header = element(0x1A45DFA3, element(0x4286, uint(1)))
    tracks = element(0x1654AE6B, b"".join(entries))
    cluster = element(0x1F43B675, element(0xE7, uint(0)) + b"".join(blocks))
    return header + element(0x18538067, tracks + cluster)
