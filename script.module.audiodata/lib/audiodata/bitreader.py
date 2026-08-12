"""MSB-first bit reader over a bytes buffer.

The audio bitstream headers this package parses are all defined as MSB-first
bit fields with no byte alignment between them, so they are read through this
rather than with struct unpacks.  Reading past the end raises ``EOFError``: a
truncated header is a header that cannot be trusted, and the callers turn that
into "no reading" rather than into a half-filled result.
"""


class BitReader:
    """Sequential MSB-first bit reader.  ``pos`` is counted in bits."""

    __slots__ = ("_data", "_pos", "_end")

    def __init__(self, data: bytes, start_bit: int = 0):
        self._data = data
        self._pos = start_bit
        self._end = len(data) * 8

    @property
    def pos(self) -> int:
        """Current read position in bits from the start of the buffer."""
        return self._pos

    def remaining(self) -> int:
        """Bits left in the buffer."""
        return self._end - self._pos

    def read(self, count: int) -> int:
        """Return the next ``count`` bits as an unsigned integer."""
        if count < 0:
            raise ValueError("bit count must not be negative")
        if self._pos + count > self._end:
            raise EOFError("bit reader ran past the end of the buffer")

        value = 0
        pos = self._pos
        left = count
        while left:
            byte_index = pos >> 3
            bit_offset = pos & 7
            take = min(8 - bit_offset, left)
            byte = self._data[byte_index]
            # Drop the bits already consumed on the left, then the ones this
            # read does not reach on the right.
            chunk = (byte >> (8 - bit_offset - take)) & ((1 << take) - 1)
            value = (value << take) | chunk
            pos += take
            left -= take

        self._pos = pos
        return value

    def read_bool(self) -> bool:
        """Return the next bit as a flag."""
        return bool(self.read(1))

    def skip(self, count: int) -> None:
        """Advance past ``count`` bits."""
        if self._pos + count > self._end:
            raise EOFError("bit reader ran past the end of the buffer")
        self._pos += count
