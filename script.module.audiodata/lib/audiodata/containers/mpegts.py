"""Native MPEG transport stream parser (188-byte TS, 192-byte M2TS/BDAV,
204-byte TS with FEC).

Finds the PAT and PMT(s), identifies audio elementary streams, collects their
PES payloads and hands them to the codec header parsers.  This is the path a
Blu-ray takes: its M2TS clips carry the DTS-HD and TrueHD tracks whose real
rate and depth only the bitstream states, and the PMT stream type names the
flavour the bitstream scan can miss.
"""

from .. import codecs
from ..report import Report, Track

_PER_PID_CAP = 256 * 1024
_ENOUGH_BYTES = 64 * 1024
_CHUNK = 512 * 1024

# Elementary stream kinds, keyed off the PMT stream type and its descriptors.
AC3, EAC3, DTS, DTS_HD_HRA, DTS_HD_MA, DTS_EXPRESS = (
    "ac3", "eac3", "dts", "dts_hd_hra", "dts_hd_ma", "dts_express")
TRUEHD, AAC, AAC_LATM, MPEG_AUDIO, LPCM_HDMV, OPUS = (
    "truehd", "aac", "aac_latm", "mpeg_audio", "lpcm_hdmv", "opus")

_DTS_KINDS = (DTS, DTS_HD_HRA, DTS_HD_MA, DTS_EXPRESS)

_FALLBACK_NAMES = {
    AC3: "AC-3", EAC3: "E-AC-3", DTS: "DTS", DTS_HD_HRA: "DTS-HD HRA",
    DTS_HD_MA: "DTS-HD MA", DTS_EXPRESS: "DTS Express", TRUEHD: "TrueHD",
    AAC: "AAC", AAC_LATM: "AAC (LATM)", MPEG_AUDIO: "MPEG Audio",
    LPCM_HDMV: "LPCM (Blu-ray)", OPUS: "Opus",
}


class _EsStream:
    __slots__ = ("kind", "language", "buf", "started", "resolved")

    def __init__(self, kind, language):
        self.kind = kind
        self.language = language
        self.buf = bytearray()
        self.started = False
        self.resolved = None


def probe(read, scan_limit: int):
    """Read a transport stream and return its Report, or raise ValueError."""
    head = _read_up_to(read, 65536)

    detected = _detect_packet_size(head)
    if detected is None:
        raise ValueError("no MPEG-TS sync pattern found")
    pkt_size, first = detected
    container = {192: "M2TS (BDAV)", 204: "MPEG-TS (204)"}.get(pkt_size, "MPEG-TS")

    state = {"pat_seen": False, "hdmv": False}
    pmt_pids: list = []
    pmts_parsed: list = []
    streams: dict = {}

    scanned = 0
    carry = bytearray(head)
    tail_padded = False

    while True:
        # `first` points at the 0x47 sync byte, so every stride starts on one;
        # for 192-byte BDAV packets the 4-byte TP_extra_header of the *next*
        # packet trails the slice and is ignored, since only the first 188
        # bytes are used.
        off = first if scanned == 0 else 0
        done = False
        while off + pkt_size <= len(carry):
            packet = carry[off:off + pkt_size]
            off += pkt_size
            if packet[0] != 0x47:
                continue
            _handle_packet(packet, state, pmt_pids, pmts_parsed, streams)
            if (pmts_parsed and len(pmts_parsed) >= len(pmt_pids) and streams
                    and all(s.resolved is not None or len(s.buf) >= _ENOUGH_BYTES
                            for s in streams.values())):
                done = True
                break
        if done:
            break

        del carry[:off]
        scanned += off
        if scanned >= scan_limit:
            break

        chunk = _read_up_to(read, _CHUNK)
        if not chunk:
            # EOF: a 192-byte BDAV stream's final packet lacks the trailing
            # TP_extra_header of a successor -- pad it so it is still parsed.
            if not tail_padded and 188 <= len(carry) < pkt_size:
                carry.extend(b"\xff" * (pkt_size - len(carry)))
                tail_padded = True
                continue
            break
        carry.extend(chunk)

    if not state["pat_seen"]:
        raise ValueError("no PAT found in transport stream")
    if not pmts_parsed:
        raise ValueError("no PMT found in transport stream")

    tracks = []
    for pid in sorted(streams):
        stream = streams[pid]
        info = stream.resolved or _parse_payload(stream.kind, bytes(stream.buf))
        tracks.append(_build_track(pid, stream, info))
    return Report(container=container, tracks=tracks)


def _read_up_to(read, count: int) -> bytes:
    """Read up to ``count`` bytes, stopping early only at the end of the stream."""
    chunks = []
    want = count
    while want:
        chunk = read(want)
        if not chunk:
            break
        chunks.append(chunk)
        want -= len(chunk)
    return b"".join(bytes(c) for c in chunks)


def _detect_packet_size(buf: bytes):
    """Return ``(packet size, offset of the first sync byte)``, or None.

    For 192-byte BDAV packets the offset points at the 0x47 sync byte, i.e. 4
    bytes into the packet; the TP_extra_header of every subsequent packet is
    then carried at the end of the previous slice, which is harmless because
    only the first 188 bytes are read.
    """
    for size in (188, 192, 204):
        scan = min(size + 8, len(buf))
        for start in range(scan):
            if len(buf) < start + size * 4 + 1:
                break
            if all(buf[start + i * size] == 0x47 for i in range(5)):
                return size, start
    return None


def _handle_packet(p, state, pmt_pids, pmts_parsed, streams):
    if len(p) < 188:
        return
    pusi = bool(p[1] & 0x40)
    pid = ((p[1] & 0x1F) << 8) | p[2]
    afc = (p[3] >> 4) & 3
    if not afc & 1:
        return                                    # no payload
    off = 4
    if afc & 2:
        off += 1 + p[4]                           # adaptation field
        if off >= 188:
            return
    payload = bytes(p[off:188])

    if pid == 0:
        if pusi and not state["pat_seen"]:
            pids = _parse_pat(payload)
            if pids:
                pmt_pids[:] = pids
                state["pat_seen"] = True
        return

    if pid in pmt_pids and pid not in pmts_parsed:
        if pusi and _parse_pmt(payload, state, streams):
            pmts_parsed.append(pid)
        return

    stream = streams.get(pid)
    if stream is None:
        return

    _append_pes(stream, payload, pusi)
    if stream.resolved is None and stream.started and len(stream.buf) >= 4096:
        info = _parse_payload(stream.kind, bytes(stream.buf))
        if info:
            # For DTS keep collecting a little longer so the extension
            # substreams (XLL/XBR/LBR) can be classified reliably.
            want_more = stream.kind in _DTS_KINDS and len(stream.buf) < 32 * 1024
            if not want_more:
                stream.resolved = info


def _section(payload: bytes):
    """Skip the pointer field to the start of a PSI section."""
    if not payload:
        return None
    return payload[1 + payload[0]:]


def _parse_pat(payload: bytes):
    s = _section(payload)
    if not s or s[0] != 0x00 or len(s) < 8:
        return None
    section_length = ((s[1] & 0x0F) << 8) | s[2]
    end = min(3 + section_length, len(s))
    pids = []
    i = 8
    while i + 4 <= max(end - 4, 0):
        program = (s[i] << 8) | s[i + 1]
        pid = ((s[i + 2] & 0x1F) << 8) | s[i + 3]
        if program != 0:
            pids.append(pid)
        i += 4
    return pids or None


def _parse_pmt(payload: bytes, state, streams) -> bool:
    s = _section(payload)
    if not s or s[0] != 0x02 or len(s) < 12:
        return False
    section_length = ((s[1] & 0x0F) << 8) | s[2]
    end = max(min(3 + section_length, len(s)) - 4, 0)      # minus CRC
    program_info_len = ((s[10] & 0x0F) << 8) | s[11]
    prog_desc = s[12:12 + program_info_len]
    if b"HDMV" in _registration_ids(prog_desc):
        state["hdmv"] = True

    i = 12 + program_info_len
    while i + 5 <= end:
        stream_type = s[i]
        pid = ((s[i + 1] & 0x1F) << 8) | s[i + 2]
        es_info_len = ((s[i + 3] & 0x0F) << 8) | s[i + 4]
        desc = s[i + 5:min(i + 5 + es_info_len, end)]
        i += 5 + es_info_len
        kind = _classify(stream_type, desc, state["hdmv"])
        if kind and pid not in streams:
            streams[pid] = _EsStream(kind, _iso639_language(desc))
    return True


def _iter_descriptors(descriptors: bytes):
    """Yield ``(tag, body)`` for each descriptor in a descriptor loop."""
    i = 0
    while i + 2 <= len(descriptors):
        tag = descriptors[i]
        length = descriptors[i + 1]
        yield tag, descriptors[i + 2:i + 2 + length]
        i += 2 + length


def _registration_ids(descriptors: bytes):
    return [body[:4] for tag, body in _iter_descriptors(descriptors)
            if tag == 0x05 and len(body) >= 4]


def _iso639_language(descriptors: bytes):
    for tag, body in _iter_descriptors(descriptors):
        if tag == 0x0A and len(body) >= 3:
            lang = "".join(chr(b) for b in body[:3] if chr(b).isalpha())
            if len(lang) == 3:
                return lang.lower()
    return None


def _classify(stream_type: int, descriptors: bytes, hdmv: bool):
    """Map a PMT stream type plus its descriptors to an elementary stream kind."""
    regs = _registration_ids(descriptors)
    tags = {tag for tag, _body in _iter_descriptors(descriptors)}

    if stream_type in (0x03, 0x04):
        return MPEG_AUDIO
    if stream_type == 0x0F:
        return AAC
    if stream_type == 0x11:
        return AAC_LATM
    if stream_type == 0x06:
        # DVB private data: identified by its descriptors.
        if 0x6A in tags or b"AC-3" in regs:
            return AC3
        if 0x7A in tags:
            return EAC3
        if 0x7B in tags or any(r in (b"DTS1", b"DTS2", b"DTS3") for r in regs):
            return DTS
        if 0x7C in tags:
            return AAC
        if b"Opus" in regs:
            return OPUS
        return None
    if stream_type == 0x80:
        return LPCM_HDMV if hdmv else AC3          # ATSC uses 0x80 for AC-3
    return {
        0x81: AC3, 0x82: DTS, 0x83: TRUEHD, 0x84: EAC3, 0x87: EAC3,
        0xA1: EAC3, 0x85: DTS_HD_HRA, 0x86: DTS_HD_MA, 0xA2: DTS_EXPRESS,
    }.get(stream_type)


def _append_pes(stream, payload: bytes, pusi: bool) -> None:
    if len(stream.buf) >= _PER_PID_CAP:
        return
    if pusi:
        # PES header: 00 00 01 stream_id len(2) flags(2) hdrlen(1)
        if len(payload) < 9 or payload[0] != 0 or payload[1] != 0 or payload[2] != 1:
            return
        stream_id = payload[3]
        audio_like = (0xC0 <= stream_id <= 0xDF or stream_id == 0xBD
                      or stream_id == 0xFD)
        if not audio_like:
            return
        if payload[6] & 0xC0 != 0x80:
            return                                # not an MPEG-2 PES header
        data_start = 9 + payload[8]
        if data_start <= len(payload):
            stream.started = True
            stream.buf.extend(payload[data_start:])
    elif stream.started:
        stream.buf.extend(payload)


def _parse_payload(kind, buf: bytes):
    if not buf:
        return None
    if kind in (AC3, EAC3):
        return codecs.ac3.parse(buf)
    if kind in _DTS_KINDS:
        return codecs.dts.parse(buf)
    if kind == TRUEHD:
        info = codecs.truehd.parse(buf)
        if info:
            return info
        # The Blu-ray TrueHD PID interleaves an AC-3 compatibility stream;
        # fall back to it when no major sync was captured.
        info = codecs.ac3.parse(buf)
        if info:
            info.name = "TrueHD"
            info.bit_depth = None
            info.note = "parameters from embedded AC-3 core"
        return info
    if kind == AAC:
        return codecs.aac.parse_adts(buf)
    if kind == AAC_LATM:
        return codecs.aac.parse_loas_latm(buf)
    if kind == MPEG_AUDIO:
        return codecs.mpeg_audio.parse(buf)
    if kind == LPCM_HDMV:
        return codecs.pcm.parse_hdmv_lpcm(buf)
    return None                                   # DVB Opus carries no OpusHead


def _build_track(pid: int, stream, info) -> Track:
    track = Track(
        id=f"PID {pid} (0x{pid:04X})",
        codec=_FALLBACK_NAMES[stream.kind],
        language=stream.language,
    )
    if info is None:
        track.note = "no payload captured in scan window"
        return track

    if info.name:
        # The PMT stream type is authoritative for the DTS flavour; the
        # bitstream scan may miss the extension syncs inside its window.
        keep_pmt_name = (
            stream.kind in (DTS_HD_MA, DTS_HD_HRA, DTS_EXPRESS)
            and info.name.startswith("DTS")
            and "MA" not in info.name and "HRA" not in info.name
        )
        if not keep_pmt_name:
            track.codec = info.name
    track.sample_rate = info.sample_rate
    track.bit_depth = info.bit_depth
    track.channels = info.channels
    track.lfe = info.lfe
    track.note = info.note
    return track
