# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Remember the widest picture of the playing title.

An IMAX film switches between its regular framing (2.39:1, say) and taller
IMAX scenes (1.78:1 or 1.90:1).  Which of the two is on screen can only be
told against the other, so the service follows the aspect ratio all through
playback and publishes the widest one seen as a Home-window property.
``info.properties`` lights the IMAX mark while the picture is taller than
that.

It has to run whether or not a view is open: the overlay is usually opened
in the middle of a film and must know the regular framing by then.
"""

import xbmc
from core.utils import PROP_WIDEST_ASPECT, first_float, home_window
from info.dvinfo import get_l5_offsets
from info.properties import STANDARD_ARS, get_AspectRatioVar

# Seconds between two passes (the bar scanner's thread keeps this pace).
FOLLOW_INTERVAL = 0.5

# Passes in a row a ratio has to last before it counts, so a stray reading
# during a fade or a studio logo does not become the film's regular framing.
# A standard film ratio counts after one second; an odd one, which a stray
# reading usually is, only after three.
SETTLE_PASSES     = 2
ODD_SETTLE_PASSES = 6


class WidestRatio:
    """The widest aspect ratio that lasted, for one title."""

    def __init__(self) -> None:
        self.widest: float | None = None
        self._last: float | None = None
        self._held = 0

    def reset(self) -> None:
        """Forget everything (a new title)."""
        self.widest = None
        self._last = None
        self._held = 0

    def note(self, ratio: float | None) -> None:
        """Take in the ratio of one pass (None: unknown)."""
        if ratio != self._last:
            self._last = ratio
            self._held = 1
            return
        self._held += 1
        if ratio is None or self._held < self._passes_needed(ratio):
            return
        if self.widest is None or ratio > self.widest:
            self.widest = ratio

    @staticmethod
    def _passes_needed(ratio: float) -> int:
        """Return how long *ratio* has to last before it counts."""
        return SETTLE_PASSES if ratio in STANDARD_ARS else ODD_SETTLE_PASSES


class FramingWatch:
    """Follow the playing title's aspect ratio and publish the widest."""

    def __init__(self) -> None:
        self._ratios = WidestRatio()
        self._source = ""
        # None: not known, so the first pass clears an earlier session's.
        self._published: str | None = None

    def follow(self) -> None:
        """Run one pass."""
        if not xbmc.getCondVisibility("Player.HasVideo"):
            self.clear()
            return
        source = xbmc.getInfoLabel("Player.FilenameAndPath")
        if source != self._source:
            self.clear()
            self._source = source

        self._ratios.note(first_float(get_AspectRatioVar(get_l5_offsets())))
        widest = self._ratios.widest
        self._publish(f"{widest:.2f}" if widest is not None else "")

    def clear(self) -> None:
        """Forget the title and withdraw the property."""
        self._ratios.reset()
        self._source = ""
        self._publish("")

    def _publish(self, value: str) -> None:
        """Write the property when it changes."""
        if value == self._published:
            return
        self._published = value
        home_window().setProperty(PROP_WIDEST_ASPECT, value)
