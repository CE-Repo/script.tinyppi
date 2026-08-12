"""Read-only UDF walker over a disc image: just enough of ECMA-167 / UDF 2.50
to find ``BDMV/PLAYLIST`` and ``BDMV/STREAM``, list their entries, and resolve
a file's byte extents.

Handles both the plain type-1 partition map (UDF 1.02/2.01 images) and UDF
2.50's Metadata Partition -- BD-ROM's shape, where file entries and directories
live in a metadata *file* whose extents remap onto the physical partition.

UDF is little-endian (explicit LE reads, never native), and every
descriptor-declared count is clamped or bounded: a corrupt image must yield an
error, never a runaway loop.
"""

import struct

# ISO images address descriptors in 2048-byte sectors; UDF requires the logical
# block size to match (enforced against the LVD in open()).
SECTOR = 2048

# Volume Recognition Sequence scan window (sectors 16..).  Bridge images put
# ISO9660 CD001 descriptors ahead of the BEA01/NSR sequence, so a window is
# scanned rather than requiring NSR at a fixed sector.
_VRS_SCAN_SECTORS = 64

_MAX_VDS_SECTORS = 1024
_MAX_FIDS_PER_DIR = 65536
_MAX_EXTENTS_PER_FILE = 65536
_MAX_AED_HOPS = 64
_MAX_ICB_INDIRECTIONS = 4
# Directory data / small-file gather cap (BDMV directories and playlists are
# KiB-scale; anything larger is corrupt or not ours to read).
MAX_GATHER = 8 << 20


class UdfError(Exception):
    """Raised for a structurally invalid or unsupported UDF volume."""


def _u16(d: bytes, o: int) -> int:
    return struct.unpack_from("<H", d, o)[0] if o + 2 <= len(d) else 0


def _u32(d: bytes, o: int) -> int:
    return struct.unpack_from("<I", d, o)[0] if o + 4 <= len(d) else 0


def _u64(d: bytes, o: int) -> int:
    return struct.unpack_from("<Q", d, o)[0] if o + 8 <= len(d) else 0


def _tag_id(d: bytes, off: int = 0):
    """Verify a 16-byte descriptor tag and return its identifier, or None.

    The checksum byte 4 is the sum of the other 15 header bytes, which is what
    separates a real descriptor from any 16 bytes that happen to sit there.
    """
    tag = d[off:off + 16]
    if len(tag) < 16:
        return None
    total = 0
    for i, byte in enumerate(tag):
        if i != 4:
            total = (total + byte) & 0xFF
    if total != tag[4] or (tag[0] == 0 and tag[1] == 0):
        return None
    return _u16(tag, 0)


class _LongAd:
    """long_ad / short_ad, normalised; ``raw_len`` keeps the extent-type bits."""

    __slots__ = ("raw_len", "lbn", "prn")

    def __init__(self, raw_len=0, lbn=0, prn=0):
        self.raw_len = raw_len
        self.lbn = lbn
        self.prn = prn

    @classmethod
    def parse_long(cls, d: bytes, o: int):
        return cls(_u32(d, o), _u32(d, o + 4), _u16(d, o + 8))

    @classmethod
    def parse_short(cls, d: bytes, o: int, host_prn: int):
        return cls(_u32(d, o), _u32(d, o + 4), host_prn)

    @property
    def length(self) -> int:
        return self.raw_len & 0x3FFFFFFF

    @property
    def extent_type(self) -> int:
        """0 recorded, 1 allocated-unrecorded, 2 unallocated, 3 continuation."""
        return self.raw_len >> 30


class Entry:
    """A directory child as listed by ``read_dir``; opaque beyond name and kind.

    Hand it back to the volume for sizes, extents and content.
    """

    __slots__ = ("name", "is_dir", "icb")

    def __init__(self, name: str, is_dir: bool, icb: _LongAd):
        self.name = name
        self.is_dir = is_dir
        self.icb = icb

    def __repr__(self):
        return f"Entry(name={self.name!r}, is_dir={self.is_dir})"


class _Fe:
    __slots__ = ("block", "efe", "host_prn")

    def __init__(self, block, efe, host_prn):
        self.block = block
        self.efe = efe
        self.host_prn = host_prn


def is_udf_iso(image) -> bool:
    """Volume Recognition Sequence check: an NSR02/NSR03 descriptor in the
    sector-16 window marks an ECMA-167 (UDF) volume.  The cheap gate the ISO
    dispatcher uses before committing to the UDF path."""
    for sector in range(16, _VRS_SCAN_SECTORS):
        ident = image.read_at(sector * SECTOR + 1, 5)
        if not ident:
            return False
        if ident in (b"NSR02", b"NSR03"):
            return True
    return False


class UdfVolume:
    """A mounted UDF volume: partition maps plus the file set descriptor."""

    def __init__(self, image):
        self._image = image
        self._parts = []          # list of ("physical", start) / ("metadata", extents)
        self._fsd_icb = _LongAd()

    # --- block addressing --------------------------------------------------

    def _slice(self, offset: int, length: int) -> bytes:
        data = self._image.read_at(offset, length)
        if not data:
            raise UdfError(f"extent [{offset}, {offset + length}) outside the image")
        return data

    def _resolve(self, prn: int, lbn: int) -> int:
        if prn >= len(self._parts):
            raise UdfError(f"unknown partition reference {prn}")
        kind, value = self._parts[prn]
        if kind == "physical":
            return (value + lbn) * SECTOR
        for first, abs_byte, blocks in value:
            if first <= lbn < first + blocks:
                return abs_byte + (lbn - first) * SECTOR
        raise UdfError(f"logical block {lbn} outside the metadata partition")

    # --- mounting ----------------------------------------------------------

    @classmethod
    def open(cls, image):
        if not is_udf_iso(image):
            raise UdfError("not a UDF volume (no NSR descriptor in the "
                           "volume recognition sequence)")
        vol = cls(image)
        sectors = image.size // SECTOR if image.size else 0

        # Anchor Volume Descriptor Pointer: sector 256 primarily; the spec's
        # alternate anchors rescue an image with a damaged head.
        vds = None
        for anchor in (256, max(sectors - 257, 0), max(sectors - 1, 0)):
            if anchor < 256:
                continue
            block = image.read_at(anchor * SECTOR, SECTOR)
            if block and _tag_id(block) == 2:
                vds = (_u32(block, 20), _u32(block, 16))
                break
        if vds is None:
            raise UdfError("no anchor volume descriptor")
        vds_loc, vds_len = vds

        # Volume Descriptor Sequence: the Partition Descriptor(s) and the
        # Logical Volume Descriptor; stop at the Terminating Descriptor.
        pds = []                  # (partition number, start sector)
        lvd = None
        for i in range(min(vds_len // SECTOR, _MAX_VDS_SECTORS)):
            sector = image.read_at((vds_loc + i) * SECTOR, SECTOR)
            if not sector:
                break
            tag = _tag_id(sector)
            if tag == 5:
                pds.append((_u16(sector, 22), _u32(sector, 188)))
            elif tag == 6:
                lvd = sector
            elif tag == 8 or tag is None:
                break
        if lvd is None:
            raise UdfError("no logical volume descriptor")
        if _u32(lvd, 212) != SECTOR:
            raise UdfError(f"unsupported UDF logical block size {_u32(lvd, 212)}")
        vol._fsd_icb = _LongAd.parse_long(lvd, 248)

        vol._read_partition_maps(lvd, pds)
        return vol

    def _read_partition_maps(self, lvd: bytes, pds) -> None:
        """Read the partition maps in table order; long_ad partition reference
        numbers index that order.  Metadata maps resolve in a second pass: the
        metadata file's own File Entry lives in the physical partition."""
        map_count = min(_u32(lvd, 268), 64)
        map_end = min(440 + _u32(lvd, 264), len(lvd))
        meta_pending = []         # (part index, phys num, file loc, mirror loc)
        p = 440
        for _ in range(map_count):
            if p + 2 > map_end:
                break
            typ, length = lvd[p], lvd[p + 1]
            if length < 2 or p + length > map_end:
                break
            if typ == 1 and length >= 6:
                num = _u16(lvd, p + 4)
                start = next((s for n, s in pds if n == num), None)
                if start is None:
                    raise UdfError(f"partition map names unknown partition {num}")
                self._parts.append(("physical", start))
            elif typ == 2 and length >= 64 and lvd[p + 5:p + 28] == b"*UDF Metadata Partition":
                meta_pending.append((len(self._parts), _u16(lvd, p + 38),
                                     _u32(lvd, p + 40), _u32(lvd, p + 44)))
                self._parts.append(("metadata", []))
            elif typ == 2:
                name = lvd[p + 5:p + 28].decode("latin-1").rstrip()
                raise UdfError(f"unsupported UDF partition map type '{name}'")
            else:
                raise UdfError(f"unsupported UDF partition map type {typ}")
            p += length

        for idx, phys_num, file_loc, mirror_loc in meta_pending:
            host_prn = None
            for i, (kind, value) in enumerate(self._parts):
                if kind == "physical" and any(n == phys_num and s == value
                                              for n, s in pds):
                    host_prn = i
                    break
            if host_prn is None:
                raise UdfError(f"metadata partition names unknown partition {phys_num}")
            try:
                extents = self._metadata_file_extents(host_prn, file_loc)
            except UdfError:
                extents = self._metadata_file_extents(host_prn, mirror_loc)
            self._parts[idx] = ("metadata", extents)

    def _metadata_file_extents(self, host_prn: int, lbn: int):
        """The metadata file's recorded extents as ``(first_meta_block,
        abs_byte, blocks)``: the metadata partition's block-remap table."""
        fe = self._file_entry(_LongAd(1, lbn, host_prn))
        inline, extents = self._body(fe)
        if inline is not None:
            raise UdfError("inline metadata file")
        out = []
        next_block = 0
        for abs_byte, length in extents:
            blocks = length // SECTOR
            out.append((next_block, abs_byte, blocks))
            next_block += blocks
        if not out:
            raise UdfError("empty metadata file")
        return out

    # --- file entries ------------------------------------------------------

    def _file_entry(self, icb: _LongAd) -> _Fe:
        """Read a File Entry / Extended File Entry block, following a bounded
        chain of Indirect Entries (strategy-4096 volumes)."""
        for _ in range(_MAX_ICB_INDIRECTIONS):
            block = self._slice(self._resolve(icb.prn, icb.lbn), SECTOR)
            tag = _tag_id(block)
            if tag == 261:
                return _Fe(block, False, icb.prn)
            if tag == 266:
                return _Fe(block, True, icb.prn)
            if tag == 259:
                icb = _LongAd.parse_long(block, 36)
                continue
            raise UdfError(f"expected a file entry, found tag {tag}")
        raise UdfError("indirect ICB chain too deep")

    def _body(self, fe: _Fe):
        """Return ``(inline bytes, extents)``; exactly one is not None/empty.

        Extents are absolute ``(offset, len)`` byte ranges in file order and
        uncoalesced -- adjacency is the caller's concern.
        """
        if fe.efe:
            l_ea_off, l_ad_off, area_base = 208, 212, 216
        else:
            l_ea_off, l_ad_off, area_base = 168, 172, 176
        l_ea = _u32(fe.block, l_ea_off)
        l_ad = _u32(fe.block, l_ad_off)
        start = area_base + l_ea
        area = fe.block[start:start + l_ad]
        if len(area) != l_ad:
            raise UdfError("allocation descriptors outside the file entry")

        ad_form = _u16(fe.block, 34) & 7          # icb_tag flags
        if ad_form == 3:
            return area, []
        if ad_form == 0:
            ad_size = 8                            # short_ad
        elif ad_form == 1:
            ad_size = 16                           # long_ad
        else:
            raise UdfError(f"unsupported allocation descriptor form {ad_form}")

        out = []
        host_prn = fe.host_prn
        for _ in range(_MAX_AED_HOPS):
            p = 0
            continued = False
            while p + ad_size <= len(area):
                if len(out) >= _MAX_EXTENTS_PER_FILE:
                    raise UdfError("too many extents")
                if ad_size == 8:
                    ad = _LongAd.parse_short(area, p, host_prn)
                else:
                    ad = _LongAd.parse_long(area, p)
                p += ad_size
                if ad.length == 0:
                    return None, out
                if ad.extent_type == 0:
                    out.append((self._resolve(ad.prn, ad.lbn), ad.length))
                elif ad.extent_type == 3:
                    # Continuation: an Allocation Extent Descriptor block.
                    block = self._slice(self._resolve(ad.prn, ad.lbn), SECTOR)
                    if _tag_id(block) != 258:
                        raise UdfError("bad allocation extent descriptor")
                    length = min(_u32(block, 20), len(block) - 24)
                    area = block[24:24 + length]
                    host_prn = ad.prn
                    continued = True
                    break
                else:
                    raise UdfError("unrecorded extent in file body")
            if not continued:
                break
        return None, out

    def _gather(self, fe: _Fe, cap: int) -> bytes:
        """Gather a body into a buffer (directory data, playlist files)."""
        info_len = _u64(fe.block, 56)
        take = min(info_len, cap)
        inline, extents = self._body(fe)
        if inline is not None:
            return inline[:take] if take < len(inline) else inline
        out = bytearray()
        for offset, length in extents:
            if len(out) >= take:
                break
            want = min(take - len(out), length)
            out.extend(self._slice(offset, want))
        return bytes(out)

    # --- public walk -------------------------------------------------------

    def root(self) -> Entry:
        """The root directory as a synthetic entry for ``read_dir``."""
        fsd = self._slice(self._resolve(self._fsd_icb.prn, self._fsd_icb.lbn), SECTOR)
        if _tag_id(fsd) != 256:
            raise UdfError("no file set descriptor")
        return Entry("", True, _LongAd.parse_long(fsd, 400))

    def read_dir(self, directory: Entry):
        """List a directory's children (deleted and parent entries skipped)."""
        if not directory.is_dir:
            raise UdfError("not a directory")
        buf = self._gather(self._file_entry(directory.icb), MAX_GATHER)
        out = []
        p = 0
        while p + 38 <= len(buf) and len(out) < _MAX_FIDS_PER_DIR:
            if _tag_id(buf, p) != 257:
                break
            chars = buf[p + 18]
            l_fi = buf[p + 19]
            l_iu = _u16(buf, p + 36)
            total = (38 + l_iu + l_fi + 3) & ~3
            name_start = p + 38 + l_iu
            name_bytes = buf[name_start:name_start + l_fi]
            if len(name_bytes) != l_fi:
                break
            # Skip parent (bit 3) and deleted (bit 2) entries.
            if not chars & 0x0C and l_fi > 0:
                out.append(Entry(_decode_ostaname(name_bytes),
                                 bool(chars & 0x02),
                                 _LongAd.parse_long(buf, p + 20)))
            p += total
        return out

    def info_len(self, entry: Entry) -> int:
        """The file's recorded size (File Entry information_length)."""
        return _u64(self._file_entry(entry.icb).block, 56)

    def extents(self, entry: Entry):
        """Absolute ``(offset, len)`` byte extents in file order, uncoalesced."""
        inline, extents = self._body(self._file_entry(entry.icb))
        if inline is not None:
            raise UdfError("file data is embedded in its file entry")
        return extents

    def read_small(self, entry: Entry, cap: int) -> bytes:
        """Read a small file whole, size-capped: playlists."""
        return self._gather(self._file_entry(entry.icb), cap)


def _decode_ostaname(d: bytes) -> str:
    """OSTA compressed unicode: byte 0 is the compression id, 8 = one byte per
    character (latin-1), 16 = UTF-16BE pairs."""
    if not d:
        return ""
    if d[0] == 8:
        return d[1:].decode("latin-1")
    if d[0] == 16:
        body = d[1:]
        if len(body) % 2:
            body = body[:-1]
        return body.decode("utf-16-be", "replace")
    return ""
