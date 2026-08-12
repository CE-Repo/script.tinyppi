"""Native codec bitstream header parsers.

Every parser takes a byte buffer -- typically the first frames of an
elementary stream -- and extracts sample rate, bit depth where the codec
defines one, channel count and a display name from the sync headers.

A parser returns ``None`` rather than raising when the buffer holds no header
it can trust.  Sync words are only 16 to 32 bits wide and turn up in ordinary
data on their own, so each parser also range-checks what it read: a header that
parses but describes something impossible is a false positive, not a reading.
"""

from ..codecinfo import CodecInfo
from . import aac, ac3, dts, flac, mpeg_audio, pcm, truehd, xiph

__all__ = ["CodecInfo", "aac", "ac3", "dts", "flac", "mpeg_audio", "pcm",
           "truehd", "xiph"]
