"""Minimal Blu-ray MPLS (MoviePlaylist) parser: just enough to rank playlists
by duration and name their clips.

Reads the header and each PlayItem's fixed-offset fields (clip id, codec id,
IN/OUT times), advancing by the item's own length field; STN tables, sub-paths
and multi-angle blocks are skipped whole, never parsed.  MPLS is big-endian,
unlike UDF -- the two readers stay separate for that reason.
"""

import struct

# A real playlist holds a handful of PlayItems (seamless branching tops out in
# the dozens; decoys in the hundreds); anything past this is corrupt.
_MAX_PLAY_ITEMS = 4096


class MplsError(Exception):
    """Raised for anything that is not a playlist we can read."""


def _u16(d: bytes, o: int) -> int:
    return struct.unpack_from(">H", d, o)[0] if o + 2 <= len(d) else 0


def _u32(d: bytes, o: int) -> int:
    return struct.unpack_from(">I", d, o)[0] if o + 4 <= len(d) else 0


class PlayItem:
    """One PlayItem's segment: which clip it plays and the 45 kHz edit window."""

    __slots__ = ("clip_id", "in_45k", "out_45k")

    def __init__(self, clip_id: str, in_45k: int, out_45k: int):
        self.clip_id = clip_id
        self.in_45k = in_45k
        self.out_45k = out_45k

    def key(self):
        return self.clip_id, self.in_45k, self.out_45k

    def __eq__(self, other):
        return isinstance(other, PlayItem) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def __repr__(self):
        return f"PlayItem({self.clip_id!r}, {self.in_45k}, {self.out_45k})"


class Playlist:
    """The PlayItems a playlist plays, in order."""

    __slots__ = ("items",)

    def __init__(self, items=None):
        self.items = items if items is not None else []

    def duration_secs_deduped(self) -> float:
        """Total edit duration over *distinct* segments.

        Obfuscation decoys loop one segment hundreds of times; deduping by
        (clip, in, out) collapses each loop to a single contribution, so a
        decoy cannot out-rank the real feature on duration.
        """
        seen = set()
        ticks = 0
        for item in self.items:
            key = item.key()
            if key in seen:
                continue
            seen.add(key)
            ticks += max(item.out_45k - item.in_45k, 0)
        return ticks / 45000.0

    def distinct_clips(self):
        """Distinct clip ids in playback order (first appearance wins)."""
        out = []
        for item in self.items:
            if item.clip_id not in out:
                out.append(item.clip_id)
        return out

    def item_keys(self):
        """The PlayItem sequence, for collapsing identical playlists."""
        return tuple(item.key() for item in self.items)


def parse(data: bytes) -> Playlist:
    """Parse an MPLS playlist, or raise MplsError."""
    if len(data) < 16 or data[0:4] != b"MPLS":
        raise MplsError("not an MPLS playlist")
    version = data[4:8]
    if version not in (b"0100", b"0200", b"0300"):
        raise MplsError(f"unsupported MPLS version {version.decode('latin-1')}")

    pl_start = _u32(data, 8)
    # PlayList block: u32 length, 2 reserved, u16 item count, u16 sub-path count.
    if pl_start < 16 or pl_start + 10 > len(data):
        raise MplsError("PlayList block offset out of range")
    item_count = min(_u16(data, pl_start + 6), _MAX_PLAY_ITEMS)

    items = []
    p = pl_start + 10
    for _ in range(item_count):
        # PlayItem: u16 length (bytes after the field), clip id at +2 (5 ASCII),
        # codec id at +7 ("M2TS"), flags and STC id, IN/OUT 45 kHz u32 at
        # +14/+18.  Everything past OUT is skipped by the length.
        length = _u16(data, p)
        end = p + 2 + length
        if length < 20 or end > len(data):
            break                      # truncated tail: keep what was parsed
        clip_id = data[p + 2:p + 7]
        codec_id = data[p + 7:p + 11]
        if codec_id == b"M2TS" and all(0x21 <= b <= 0x7E for b in clip_id):
            items.append(PlayItem(clip_id.decode("latin-1"),
                                  _u32(data, p + 14), _u32(data, p + 18)))
        p = end
    return Playlist(items)
