"""Random access over a disc image, and a bounded reader for one clip inside it.

audioprobe works from an mmap of the whole image.  A Kodi VFS handle cannot be
mapped, and a Blu-ray ISO runs to tens of gigabytes, so the same walks are
driven here by reading the ranges they ask for as they ask for them.  Every
read is bounded and nothing larger than the requested range is held.
"""


class Image:
    """A seekable source addressed by absolute byte offset."""

    __slots__ = ("_source", "size")

    def __init__(self, source, size: int):
        self._source = source
        self.size = size

    def read_at(self, offset: int, length: int) -> bytes:
        """Return exactly ``length`` bytes at ``offset``, or b'' if unreadable.

        Short reads yield b'' rather than a partial buffer: every caller is
        parsing a fixed-layout descriptor, where half a structure is not a
        smaller structure but a wrong one.
        """
        if offset < 0 or length <= 0:
            return b""
        if self.size and offset + length > self.size:
            return b""
        try:
            self._source.seek(offset)
        except Exception:
            return b""
        chunks = []
        want = length
        while want:
            try:
                chunk = self._source.read(want)
            except Exception:
                return b""
            if not chunk:
                break
            chunks.append(bytes(chunk))
            want -= len(chunk)
        data = b"".join(chunks)
        return data if len(data) == length else b""

    def read_at_most(self, offset: int, length: int) -> bytes:
        """Return up to ``length`` bytes at ``offset``; a short read is fine."""
        if offset < 0 or length <= 0:
            return b""
        if self.size:
            length = min(length, max(self.size - offset, 0))
            if length <= 0:
                return b""
        try:
            self._source.seek(offset)
        except Exception:
            return b""
        chunks = []
        want = length
        while want:
            try:
                chunk = self._source.read(want)
            except Exception:
                break
            if not chunk:
                break
            chunks.append(bytes(chunk))
            want -= len(chunk)
        return b"".join(chunks)

    def range_reader(self, offset: int, length: int):
        """Return a sequential ``read(n)`` bounded to one byte range.

        This is what hands a located clip to the transport- or program-stream
        backend: they read forwards from the start of a stream, and the range
        makes the clip inside the image look exactly like one.
        """
        state = {"pos": offset, "left": length}

        def read(count: int) -> bytes:
            if count <= 0 or state["left"] <= 0:
                return b""
            take = min(count, state["left"])
            data = self.read_at_most(state["pos"], take)
            state["pos"] += len(data)
            state["left"] -= len(data)
            return data

        return read
