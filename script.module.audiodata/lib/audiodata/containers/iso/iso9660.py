"""Minimal read-only ISO9660 walker: enough to reach ``VIDEO_TS`` on a
DVD-Video image and resolve each ``.VOB`` file's byte extent.

DVDs carry an ISO9660 bridge alongside UDF, and VIDEO_TS files are
single-extent, so a plain ISO9660 directory walk suffices -- no UDF needed for
the DVD path.
"""

import struct

SECTOR = 2048
# A DVD directory is a handful of records; cap the walk defensively.
_MAX_RECORDS = 65536


class Iso9660Error(Exception):
    """Raised for a structurally invalid ISO9660 volume."""


def _u16(d: bytes, o: int) -> int:
    return struct.unpack_from("<H", d, o)[0] if o + 2 <= len(d) else 0


def _u32(d: bytes, o: int) -> int:
    return struct.unpack_from("<I", d, o)[0] if o + 4 <= len(d) else 0


class DirRec:
    """A directory entry: its cleaned name, kind, and absolute byte range."""

    __slots__ = ("name", "is_dir", "offset", "size")

    def __init__(self, name: str, is_dir: bool, offset: int, size: int):
        self.name = name
        self.is_dir = is_dir
        self.offset = offset
        self.size = size

    def __repr__(self):
        return f"DirRec(name={self.name!r}, is_dir={self.is_dir}, size={self.size})"


def looks_like_iso9660(image) -> bool:
    """Cheap gate: the Primary Volume Descriptor's CD001 identifier at sector 16."""
    pvd = image.read_at(16 * SECTOR, 6)
    return len(pvd) == 6 and pvd[1:6] == b"CD001" and pvd[0] == 1


class Iso9660:
    """A mounted ISO9660 volume."""

    def __init__(self, image, block_size: int, root: DirRec):
        self._image = image
        self._block_size = block_size
        self._root = root

    @classmethod
    def open(cls, image):
        pvd = image.read_at(16 * SECTOR, SECTOR)
        if not pvd:
            raise Iso9660Error("image too small for an ISO9660 volume descriptor")
        if pvd[1:6] != b"CD001" or pvd[0] != 1:
            raise Iso9660Error("no ISO9660 primary volume descriptor")
        block_size = _u16(pvd, 128) or SECTOR
        # The root directory record lives at PVD offset 156 (34 bytes).
        root_rec = pvd[156:190]
        root = DirRec("", True, _u32(root_rec, 2) * block_size, _u32(root_rec, 10))
        return cls(image, block_size, root)

    def root(self) -> DirRec:
        return self._root

    def read_dir(self, directory: DirRec):
        """List a directory's children.

        The ``.``/``..`` self and parent entries and associated-file records
        are skipped.
        """
        if not directory.is_dir:
            raise Iso9660Error("not a directory")
        buf = self._image.read_at_most(directory.offset, directory.size)
        if len(buf) < directory.size:
            raise Iso9660Error("directory extent outside the image")

        out = []
        p = 0
        while p < len(buf) and len(out) < _MAX_RECORDS:
            length = buf[p]
            if length == 0:
                # Records never span a logical sector; jump to the next one.
                nxt = (p // self._block_size + 1) * self._block_size
                if nxt <= p:
                    break
                p = nxt
                continue
            if p + length > len(buf) or length < 33:
                break
            rec = buf[p:p + length]
            ext_attr = rec[1]
            lba = _u32(rec, 2)
            size = _u32(rec, 10)
            flags = rec[25]
            name_len = rec[32]
            name_bytes = rec[33:33 + name_len]
            if len(name_bytes) == name_len:
                # Skip the '.' (0x00) and '..' (0x01) special entries.
                special = name_len == 1 and name_bytes[0] in (0, 1)
                associated = bool(flags & 0x04)
                if not special and not associated:
                    out.append(DirRec(
                        _clean_name(name_bytes),
                        bool(flags & 0x02),
                        (lba + ext_attr) * self._block_size,
                        size,
                    ))
            p += length
        return out


def _clean_name(raw: bytes) -> str:
    """ISO9660 file names carry a ``;1`` version suffix and are upper-cased;
    strip the version and a trailing dot for display and matching."""
    text = raw.decode("latin-1")
    text = text.split(";")[0]
    return text[:-1] if text.endswith(".") else text
