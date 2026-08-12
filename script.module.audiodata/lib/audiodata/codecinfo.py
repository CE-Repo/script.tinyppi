"""What a codec header declares about its own stream.

Kept in its own module so the codec parsers and the container backends can both
depend on it without importing each other.
"""


class CodecInfo:
    """A reading taken from a codec's own bitstream header.

    Every field is optional: a format that codes no bit depth leaves it None,
    and so does a header that was read but did not reach that field.
    """

    __slots__ = ("name", "sample_rate", "bit_depth", "channels", "lfe", "note")

    def __init__(self, name=None, sample_rate=None, bit_depth=None,
                 channels=None, lfe=None, note=None):
        self.name = name
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth
        self.channels = channels
        self.lfe = lfe
        self.note = note

    def __repr__(self):
        fields = ", ".join(
            f"{slot}={getattr(self, slot)!r}"
            for slot in self.__slots__ if getattr(self, slot) is not None
        )
        return f"CodecInfo({fields})"

    def __eq__(self, other):
        if not isinstance(other, CodecInfo):
            return NotImplemented
        return all(getattr(self, s) == getattr(other, s) for s in self.__slots__)
