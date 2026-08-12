"""Result model: one Track per audio stream, gathered into a Report."""


class Track:
    """One audio track as the container and its bitstream describe it."""

    __slots__ = ("id", "codec", "sample_rate", "bit_depth", "channels",
                 "lfe", "language", "title", "default", "note")

    def __init__(self, id="", codec="", sample_rate=None, bit_depth=None,
                 channels=None, lfe=None, language=None, title=None,
                 default=False, note=None):
        self.id = id
        self.codec = codec
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth
        self.channels = channels
        # Whether an LFE channel is known to be present; drives "5.1"-style
        # layout naming, which cannot be derived from a channel count alone.
        self.lfe = lfe
        self.language = language
        self.title = title
        self.default = default
        self.note = note

    def layout(self):
        """Return a ``5.1``-style layout string, or None when unknown."""
        if self.channels is None:
            return None
        if self.lfe is True and self.channels >= 2:
            return f"{self.channels - 1}.1"
        if self.lfe is False:
            return f"{self.channels}.0"
        return None

    def as_dict(self) -> dict:
        """Return the track as a plain dict, for callers crossing a JSON edge."""
        return {
            "id": self.id,
            "codec": self.codec,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "lfe": self.lfe,
            "layout": self.layout(),
            "language": self.language,
            "title": self.title,
            "default": self.default,
            "note": self.note,
        }

    def __repr__(self):
        return (f"Track(id={self.id!r}, codec={self.codec!r}, "
                f"sample_rate={self.sample_rate!r}, bit_depth={self.bit_depth!r}, "
                f"channels={self.channels!r}, language={self.language!r})")


class Report:
    """Everything read from one source."""

    __slots__ = ("container", "tracks", "error", "truncated")

    def __init__(self, container="", tracks=None, error=None, truncated=False):
        self.container = container
        self.tracks = tracks if tracks is not None else []
        self.error = error
        # Set when the source was cut short by the read budget: the tracks
        # reported come from the prefix that was read, so a track whose first
        # frames sit beyond the cut may be missing or lack a sampled depth.
        self.truncated = truncated

    def as_dict(self) -> dict:
        return {
            "container": self.container,
            "tracks": [t.as_dict() for t in self.tracks],
            "error": self.error,
            "truncated": self.truncated,
        }

    def __repr__(self):
        return (f"Report(container={self.container!r}, "
                f"tracks={len(self.tracks)}, error={self.error!r})")
