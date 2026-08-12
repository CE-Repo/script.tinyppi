"""Synthetic bitstream and container builders for the tests.

Each builder writes the field layout the matching parser reads, so a test can
state the values it wants back and assert they survive the round trip.  This
proves the parsers agree with the layouts documented in the source; it does not
prove those layouts match a real encoder's output, which only a real stream can
show.
"""

import struct


class BitWriter:
    """MSB-first bit writer, the mirror of bitreader.BitReader."""

    def __init__(self):
        self._bits = []

    def put(self, count: int, value: int) -> "BitWriter":
        for shift in range(count - 1, -1, -1):
            self._bits.append((value >> shift) & 1)
        return self

    def bytes(self) -> bytes:
        bits = list(self._bits)
        while len(bits) % 8:
            bits.append(0)
        out = bytearray(len(bits) // 8)
        for i, bit in enumerate(bits):
            if bit:
                out[i >> 3] |= 1 << (7 - (i & 7))
        return bytes(out)


# --- DTS --------------------------------------------------------------------

def dts_core(sfreq=13, nblks=15, fsize=2013, amode=9, pcmr=5, lff=1,
             ext_audio=0, ext_audio_id=0, cpf=0):
    """A DTS core frame header (defaults: 48 kHz, 5.1, 24-bit)."""
    w = BitWriter()
    w.put(32, 0x7FFE8001)
    w.put(1, 0)                    # FTYPE
    w.put(5, 0)                    # SHORT
    w.put(1, cpf)
    w.put(7, nblks)
    w.put(14, fsize)
    w.put(6, amode)
    w.put(4, sfreq)
    w.put(5, 0)                    # RATE
    w.put(5, 0)                    # MIX, DYNF, TIMEF, AUXF, HDCD
    w.put(3, ext_audio_id)
    w.put(1, ext_audio)
    w.put(1, 0)                    # ASPF
    w.put(2, lff)
    w.put(1, 0)                    # HFLAG
    if cpf:
        w.put(16, 0)               # HCRC
    w.put(1, 0)                    # FILTS
    w.put(4, 0)                    # VERNUM
    w.put(2, 0)                    # CHIST
    w.put(3, pcmr)
    w.put(32, 0)
    return w.bytes()


def dts_exss(rate_index=13, bit_depth=24, channels=8, exss_index=0,
             header_size=20, exss_size=2048, asset_type=False, language=False,
             text=None, static_fields=True, long_header=False):
    """A DTS extension substream header (defaults: 96 kHz, 24-bit, 8ch).

    ``long_header`` selects the wide header-size-type flavour, which widens
    both the header/frame size fields and the per-asset size field.
    """
    bits4hdr, bits4fs = (12, 20) if long_header else (8, 16)
    w = BitWriter()
    w.put(32, 0x64582025)
    w.put(8, 0)                    # user defined bits
    w.put(2, exss_index)
    w.put(1, 1 if long_header else 0)
    w.put(bits4hdr, header_size - 1)
    w.put(bits4fs, exss_size - 1)
    w.put(1, 1 if static_fields else 0)
    if not static_fields:
        w.put(64, 0)
        return w.bytes()
    w.put(2, 0)                    # reference clock code
    w.put(3, 0)                    # frame duration code
    w.put(1, 0)                    # no timecode
    w.put(3, 0)                    # one audio presentation
    w.put(3, 0)                    # one audio asset
    w.put(exss_index + 1, 1)       # active substream mask
    w.put(8, 0)                    # active asset mask for substream 0
    w.put(1, 0)                    # no mixing metadata
    w.put(bits4fs, 1023)           # asset size, as wide as the header type says
    w.put(9, 63)                   # asset descriptor size
    w.put(3, 0)                    # asset index
    w.put(1, 1 if asset_type else 0)
    if asset_type:
        w.put(4, 0)
    w.put(1, 1 if language else 0)
    if language:
        w.put(24, 0)
    w.put(1, 1 if text is not None else 0)
    if text is not None:
        w.put(10, text - 1)
        w.put(text * 8, 0)
    w.put(5, bit_depth - 1)
    w.put(4, rate_index)
    w.put(6, channels - 1)
    w.put(64, 0)
    return w.bytes()


DTS_XLL_SYNC = b"\x41\xa2\x95\x47"
DTS_XBR_SYNC = b"\x65\x5e\x31\x5e"
DTS_LBR_SYNC = b"\x0a\x80\x19\x21"


# --- TrueHD / MLP -----------------------------------------------------------

def truehd(rate_code=2, ch8=0x1F, ch6=0):
    """A TrueHD major sync header (default rate code 2 = 192 kHz)."""
    w = BitWriter()
    w.put(32, 0xF8726FBA)
    w.put(4, rate_code)
    w.put(4, 0)                    # multichannel type + reserved
    w.put(2, 0)                    # 2ch presentation modifier
    w.put(2, 0)                    # 6ch presentation modifier
    w.put(5, ch6)
    w.put(2, 0)                    # 8ch presentation modifier
    w.put(13, ch8)
    body = bytearray(w.bytes())
    return _with_major_sync_signature(bytes(body))


def mlp(quant_code=2, rate_code=0, assignment=6):
    """An MLP major sync header (defaults: 24-bit, 48 kHz)."""
    w = BitWriter()
    w.put(32, 0xF8726FBB)
    w.put(4, quant_code)
    w.put(4, 0)                    # group 2 quantization
    w.put(4, rate_code)
    w.put(4, 0)                    # group 2 rate
    w.put(11, 0)
    w.put(5, assignment)
    w.put(32, 0)
    return _with_major_sync_signature(w.bytes())


def _with_major_sync_signature(frame: bytes) -> bytes:
    """Place the constant 0xB752 signature at bytes 8..10, where the parser
    requires it before trusting a sync word."""
    out = bytearray(frame)
    while len(out) < 16:
        out.append(0)
    out[8:10] = b"\xb7\x52"
    return bytes(out)


# --- FLAC / AC-3 / MPEG audio / AAC / Xiph / PCM ----------------------------

def flac_streaminfo(sample_rate=96000, bit_depth=24, channels=2, magic=True):
    w = BitWriter()
    w.put(1, 0)                    # not the last metadata block
    w.put(7, 0)                    # block type STREAMINFO
    w.put(24, 34)                  # block length
    w.put(16, 4096)                # min block size
    w.put(16, 4096)                # max block size
    w.put(24, 0)                   # min frame size
    w.put(24, 0)                   # max frame size
    w.put(20, sample_rate)
    w.put(3, channels - 1)
    w.put(5, bit_depth - 1)
    w.put(36, 0)                   # total samples
    w.put(128, 0)                  # md5
    body = w.bytes()
    return (b"fLaC" + body) if magic else body


def ac3(fscod=0, frmsizecod=0, bsid=8, acmod=7, lfeon=1):
    """An AC-3 sync frame header (defaults: 48 kHz, 3/2 + LFE)."""
    w = BitWriter()
    w.put(16, 0x0B77)
    w.put(16, 0)                   # crc1
    w.put(2, fscod)
    w.put(6, frmsizecod)
    w.put(5, bsid)
    w.put(3, 0)                    # bsmod
    w.put(3, acmod)
    if acmod & 1 and acmod != 1:
        w.put(2, 0)                # cmixlev
    if acmod & 4:
        w.put(2, 0)                # surmixlev
    if acmod == 2:
        w.put(2, 0)                # dsurmod
    w.put(1, lfeon)
    w.put(32, 0)
    return w.bytes()


def eac3(fscod=0, fscod2=0, bsid=16, acmod=7, lfeon=1, strmtyp=0):
    """An E-AC-3 sync frame header (default: 48 kHz)."""
    w = BitWriter()
    w.put(16, 0x0B77)
    w.put(2, strmtyp)
    w.put(3, 0)                    # substream id
    w.put(11, 0)                   # frame size
    w.put(2, fscod)
    w.put(2, fscod2)               # fscod2 or numblkscod
    w.put(3, acmod)
    w.put(1, lfeon)
    w.put(5, bsid)
    w.put(32, 0)
    return w.bytes()


def mpeg_audio(version=3, layer=1, bitrate_idx=9, sr_idx=0, mode=0):
    """An MPEG audio frame header (defaults: MPEG-1 Layer III, 44.1 kHz)."""
    b1 = 0xE0 | (version << 3) | (layer << 1)
    b2 = (bitrate_idx << 4) | (sr_idx << 2)
    b3 = mode << 6
    return bytes([0xFF, b1, b2, b3]) + bytes(4)


def adts(profile_minus_one=1, sfi=3, chan_cfg=6):
    """An ADTS frame header (defaults: AAC-LC, 48 kHz, 5.1)."""
    b2 = (profile_minus_one << 6) | (sfi << 2) | ((chan_cfg >> 2) & 1)
    b3 = (chan_cfg & 3) << 6
    return bytes([0xFF, 0xF1, b2, b3]) + bytes(8)


def asc(aot=2, sfi=3, chan_cfg=6, ext_sfi=None):
    """An AudioSpecificConfig (defaults: AAC-LC, 48 kHz, 5.1)."""
    w = BitWriter()
    w.put(5, aot)
    w.put(4, sfi)
    w.put(4, chan_cfg)
    if aot in (5, 29):
        w.put(4, ext_sfi if ext_sfi is not None else sfi)
    w.put(16, 0)
    return w.bytes()


def opus_head(channels=6, input_rate=48000):
    return (b"OpusHead" + bytes([1, channels]) + struct.pack("<H", 312)
            + struct.pack("<I", input_rate) + bytes([0, 0, 0]))


def vorbis_id(channels=2, rate=44100):
    return (b"\x01vorbis" + struct.pack("<I", 0) + bytes([channels])
            + struct.pack("<I", rate) + bytes(16))


def hdmv_lpcm(channel_assignment=9, sampling_frequency=4, bits=3):
    """A Blu-ray LPCM audio data header (defaults: 5.1, 96 kHz, 24-bit)."""
    return bytes([0, 0, (channel_assignment << 4) | sampling_frequency,
                  bits << 6]) + bytes(16)


def dvd_lpcm(quant=2, fs=1, channels=6):
    """A DVD-Video LPCM audio header (defaults: 24-bit, 96 kHz, 6ch)."""
    return bytes([1, 0, 0, 0, (quant << 6) | (fs << 4) | (channels - 1), 0])


def waveformatex(tag=1, channels=2, rate=48000, bits=24, extensible_sub=None):
    body = struct.pack("<HHIIHH", tag, channels, rate, rate * channels * bits // 8,
                       channels * bits // 8, bits)
    if extensible_sub is not None:
        body += struct.pack("<H", 22) + struct.pack("<H", bits)
        body += struct.pack("<I", 0) + struct.pack("<H", extensible_sub) + bytes(14)
    return body


def alac_config(depth=24, channels=2, rate=96000):
    body = bytearray(24)
    body[5] = depth
    body[9] = channels
    struct.pack_into(">I", body, 20, rate)
    return bytes(body)


# --- Matroska ---------------------------------------------------------------

def vint(value: int, length: int = 0) -> bytes:
    if not length:
        length = 1
        while value >= (1 << (7 * length)) - 1:
            length += 1
    return ((1 << (7 * length)) | value).to_bytes(length, "big")


def element(element_id: int, payload: bytes) -> bytes:
    id_len = max(1, (element_id.bit_length() + 7) // 8)
    return element_id.to_bytes(id_len, "big") + vint(len(payload)) + payload


def uint(value: int) -> bytes:
    return value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")


def f64(value: float) -> bytes:
    return struct.pack(">d", value)


def track_entry(number, codec_id, language="und", rate=48000.0, channels=6,
                bit_depth=None, private=None, name=None, default=True,
                track_type=2):
    audio = element(0xB5, f64(rate)) + element(0x9F, uint(channels))
    if bit_depth:
        audio += element(0x6264, uint(bit_depth))
    body = (element(0xD7, uint(number))
            + element(0x83, uint(track_type))
            + element(0x88, uint(1 if default else 0))
            + element(0x86, codec_id.encode())
            + element(0x22B59C, language.encode()))
    if name:
        body += element(0x536E, name.encode())
    body += element(0xE1, audio)
    if private is not None:
        body += element(0x63A2, private)
    return element(0xAE, body)


def simple_block(track_number: int, frame: bytes, lacing: int = 0) -> bytes:
    flags = (lacing & 3) << 1
    return element(0xA3, vint(track_number, 1) + b"\x00\x00"
                   + bytes([flags]) + frame)


def matroska(entries, blocks=(), doctype="matroska"):
    header = element(0x1A45DFA3, element(0x4282, doctype.encode()))
    tracks = element(0x1654AE6B, b"".join(entries))
    cluster = element(0x1F43B675, element(0xE7, uint(0)) + b"".join(blocks))
    return header + element(0x18538067, tracks + cluster)


# --- MPEG-TS ----------------------------------------------------------------

def _crc_placeholder() -> bytes:
    return bytes(4)


def ts_packet(pid: int, payload: bytes, pusi: bool = False, bdav: bool = False,
              continuity: int = 0) -> bytes:
    header = bytes([
        0x47,
        (0x40 if pusi else 0) | ((pid >> 8) & 0x1F),
        pid & 0xFF,
        0x10 | (continuity & 0x0F),
    ])
    body = payload[:184]
    packet = header + body + b"\xff" * (184 - len(body))
    return (bytes(4) + packet) if bdav else packet


def pat(pmt_pid: int, program: int = 1) -> bytes:
    body = (bytes([0x00, 0x01]) + b"\x00" * 6
            + struct.pack(">HH", program, 0xE000 | pmt_pid) + _crc_placeholder())
    section_length = len(body) - 3
    section = bytearray(body)
    section[1] = 0xB0 | ((section_length >> 8) & 0x0F)
    section[2] = section_length & 0xFF
    return b"\x00" + bytes(section)


def pmt(streams, pcr_pid: int = 0x1011, hdmv: bool = False) -> bytes:
    """streams: list of (stream_type, pid, descriptor bytes)."""
    prog_desc = b""
    if hdmv:
        prog_desc = bytes([0x05, 0x04]) + b"HDMV"
    body = bytearray(bytes([0x02, 0x00, 0x00]) + b"\x00" * 5
                     + struct.pack(">H", 0xE000 | pcr_pid)
                     + struct.pack(">H", 0xF000 | len(prog_desc)) + prog_desc)
    for stream_type, pid, desc in streams:
        body += bytes([stream_type]) + struct.pack(">H", 0xE000 | pid)
        body += struct.pack(">H", 0xF000 | len(desc)) + desc
    body += _crc_placeholder()
    section_length = len(body) - 3
    body[1] = 0xB0 | ((section_length >> 8) & 0x0F)
    body[2] = section_length & 0xFF
    return b"\x00" + bytes(body)


def pes(payload: bytes, stream_id: int = 0xBD) -> bytes:
    return (b"\x00\x00\x01" + bytes([stream_id])
            + struct.pack(">H", len(payload) + 3) + b"\x80\x00\x00" + payload)


def transport_stream(streams, frames, bdav=False, repeats=4, hdmv=False):
    """Build a transport stream carrying a PAT, a PMT and PES payloads.

    ``streams`` is the PMT table; ``frames`` maps pid -> elementary bytes.
    """
    pmt_pid = 0x0100
    out = bytearray()
    for _ in range(repeats):
        out += ts_packet(0, pat(pmt_pid), pusi=True, bdav=bdav)
        out += ts_packet(pmt_pid, pmt(streams, hdmv=hdmv), pusi=True, bdav=bdav)
        for _stream_type, pid, _desc in streams:
            frame = frames.get(pid)
            if frame:
                out += ts_packet(pid, pes(frame), pusi=True, bdav=bdav)
    return bytes(out)


# --- MPEG-PS ----------------------------------------------------------------

def ps_pack_header() -> bytes:
    return b"\x00\x00\x01\xba" + bytes([0x44]) + bytes(8) + bytes([0xF8])


def ps_pes(stream_id: int, payload: bytes) -> bytes:
    body = b"\x80\x00\x00" + payload
    return b"\x00\x00\x01" + bytes([stream_id]) + struct.pack(">H", len(body)) + body


def program_stream(packets) -> bytes:
    out = bytearray(ps_pack_header())
    for stream_id, payload in packets:
        out += ps_pes(stream_id, payload)
    out += b"\x00\x00\x01\xb9"
    return bytes(out)


# --- MP4 --------------------------------------------------------------------

def box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind + payload


def mp4_audio_sample_entry(fmt: bytes, channels=6, sample_size=16, rate=48000,
                           children=b"") -> bytes:
    body = (bytes(6) + struct.pack(">H", 1)          # reserved + data ref index
            + struct.pack(">HH", 0, 0)               # version, revision
            + struct.pack(">I", 0)                   # vendor
            + struct.pack(">HH", channels, sample_size)
            + struct.pack(">HH", 0, 0)               # compression id, packet size
            + struct.pack(">I", rate << 16))
    return box(fmt, body + children)


def mp4_file(fmt: bytes, children=b"", language="eng", brand=b"isom",
             channels=6, sample_size=16, rate=48000) -> bytes:
    entry = mp4_audio_sample_entry(fmt, channels, sample_size, rate, children)
    stsd = box(b"stsd", bytes(4) + struct.pack(">I", 1) + entry)
    stbl = box(b"stbl", stsd)
    minf = box(b"minf", stbl)
    packed = 0
    for i, ch in enumerate(language):
        packed |= (ord(ch) - 0x60) << (10 - i * 5)
    mdhd = box(b"mdhd", bytes(4) + bytes(16) + struct.pack(">H", packed) + bytes(2))
    hdlr = box(b"hdlr", bytes(8) + b"soun" + bytes(12))
    mdia = box(b"mdia", mdhd + hdlr + minf)
    tkhd = box(b"tkhd", bytes(4) + bytes(8) + struct.pack(">I", 1) + bytes(80))
    trak = box(b"trak", tkhd + mdia)
    moov = box(b"moov", trak)
    ftyp = box(b"ftyp", brand + struct.pack(">I", 512) + brand)
    return ftyp + moov


# --- AVI --------------------------------------------------------------------

def riff_chunk(chunk_id: bytes, payload: bytes) -> bytes:
    pad = b"\x00" if len(payload) & 1 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + pad


def avi_file(fmt: bytes, name=None) -> bytes:
    strh = riff_chunk(b"strh", b"auds" + bytes(52))
    strf = riff_chunk(b"strf", fmt)
    body = b"strl" + strh + strf
    if name:
        body += riff_chunk(b"strn", name.encode() + b"\x00")
    strl = riff_chunk(b"LIST", body)
    hdrl = riff_chunk(b"LIST", b"hdrl" + strl)
    movi = riff_chunk(b"LIST", b"movi")
    payload = b"AVI " + hdrl + movi
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


# --- WAV / Ogg --------------------------------------------------------------

def wav_file(fmt: bytes) -> bytes:
    body = b"WAVE" + riff_chunk(b"fmt ", fmt) + riff_chunk(b"data", bytes(16))
    return b"RIFF" + struct.pack("<I", len(body)) + body


def ogg_file(payload: bytes) -> bytes:
    return b"OggS" + bytes(22) + bytes([1, len(payload) & 0xFF]) + payload
