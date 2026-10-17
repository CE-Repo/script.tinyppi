# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The shapes the dashboard sends: snapshots, delta frames and the history.

Written by web/snapshot.py, web/session.py, web/player.py and web/vs10.py,
diffed by web/delta.py and read by js/core.js.  Readings Kodi or the page
hand over unchecked stay ``object`` (a track index from JSON-RPC, say).
"""

from typing import Literal, NotRequired, TypedDict

# --- Player ----------------------------------------------------------------


class Track(TypedDict):
    """One entry of a track picker."""

    index: object
    label: str


class Controls(TypedDict, total=False):
    """Tracks, volume, mute and chapters (``player_controls``).

    Empty while the page may not control the player.
    """

    audio: list[Track]
    subtitle: list[Track]
    audio_current: object
    subtitle_current: object
    subtitle_on: bool
    volume: object
    muted: bool
    chapters: int


class Chapter(TypedDict):
    """One chapter of the playing file, placed on the progress bar."""

    # Kodi's one-based number, which ``chapter_goto`` takes.
    index: int
    # Where it starts: seconds, a percentage of the length, and a clock
    # written the way the position is.
    start: int
    at: float
    time: str
    # The file's name for it; empty when the file names none.
    name: str


class VS10Option(TypedDict):
    mode: str
    label: str


class VS10State(TypedDict):
    """The VS10 buttons for the source and the current output."""

    options: list[VS10Option]
    output: str


# --- Readings --------------------------------------------------------------


class L1(TypedDict):
    min: float | None
    max: float | None
    avg: float | None


class FrameSize(TypedDict):
    """The coded frame, the reference of the L5 offsets."""

    w: int
    h: int


class Metrics(TypedDict, total=False):
    """The numeric readings the page charts; empty while nothing plays."""

    l1: L1
    bars: list[float] | None
    frame: FrameSize | None
    aspect: float | None
    fps_in: float | None
    fps_drop: float | None
    fps_out: float | None
    progress: float | None
    cpu: float | None
    cpu_temp: float | None
    memory: float | None
    cache: float | None


class GroupRow(TypedDict):
    """One row of a card, as the overlay prints it."""

    id: str
    label: str
    value: str
    detail: str


class Group(TypedDict):
    """One card and its rows."""

    id: str
    title: str
    rows: list[GroupRow]


class MetadataRow(TypedDict):
    """One row of the DV metadata view: a value, or a table row's cells."""

    kind: str
    name: str
    value: NotRequired[str]
    cells: NotRequired[list[str]]


class Media(TypedDict):
    """The now-playing card's details; empty for non-library files."""

    year: str
    genre: str
    show: str
    season: str
    episode: str


# --- The title's history ----------------------------------------------------

# One event of the history: when and where, its kind, and what changed (a
# switch: ``from`` and ``to``) or what was measured (a warning: ``value``).
Event = TypedDict("Event", {
    "t": float,
    "pos": str,
    "kind": str,
    "from": NotRequired[object],
    "to": NotRequired[object],
    "value": NotRequired[float],
})

# What an event adds to its time, place and kind.
EventDetail = TypedDict("EventDetail", {
    "from": NotRequired[object],
    "to": NotRequired[object],
    "value": NotRequired[float],
})


class SessionSummary(TypedDict):
    """The counters every snapshot carries; a new ``seq`` means new events."""

    seq: int
    switches: int
    warnings: int


class LastTitle(TypedDict, total=False):
    """The finished title's figures for the idle page; empty when none."""

    title: str
    position: str
    ago: int
    switches: int
    warnings: int
    peak: float | None
    events: int


class History(TypedDict):
    """The chart samples (one list per series) and the events."""

    now: float
    step: float
    t: list[float]
    max: list[float | None]
    avg: list[float | None]
    events: list[Event]
    seq: int
    switches: int


# --- Snapshots -------------------------------------------------------------


class IdleSnapshot(TypedDict):
    """A snapshot while nothing plays.

    The producer's placeholder before its first pass has only ``seq``,
    ``playing``, ``groups``, ``metrics`` and ``library``.
    """

    seq: int
    playing: Literal[False]
    groups: list[Group]
    metrics: Metrics
    metadata: NotRequired[list[MetadataRow]]
    vs10: NotRequired[VS10State]
    session: NotRequired[SessionSummary]
    last: NotRequired[LastTitle]
    # Added by the producer and the routes (see Snapshot).
    library: NotRequired[int]
    control: NotRequired[bool]
    streams_full: NotRequired[bool]


class PlayingSnapshot(TypedDict):
    """A snapshot of the playing title."""

    seq: int
    playing: Literal[True]
    paused: bool
    title: str
    filename: str
    hdr_type: str
    effective: str
    output_type: str
    time: str
    duration: str
    finish: str
    metrics: Metrics
    groups: list[Group]
    metadata: list[MetadataRow]
    vs10: VS10State
    art: dict[str, str]
    media: Media
    controls: Controls
    # The chapters, sent whether or not control is allowed (they are a
    # reading), and the one the position is in: its index, 0 for none.
    chapters: list[Chapter]
    chapter: int
    session: SessionSummary
    # Added by the producer and the routes (see Snapshot).
    library: NotRequired[int]
    control: NotRequired[bool]
    streams_full: NotRequired[bool]


# What the stream and /api/state send.  The producer adds the library
# revision; the routes add whether control is allowed and, for /api/state,
# whether a stream would be refused.
Snapshot = IdleSnapshot | PlayingSnapshot


# --- Delta frames ----------------------------------------------------------

class RowsDelta(TypedDict):
    """Changed rows of a list whose shape held (see web/delta.py)."""

    rows: list[list[object]]


# What changed since the last frame: plain fields set or removed, and each
# long list either whole or by row.
DeltaFrame = TypedDict("DeltaFrame", {
    "seq": int,
    "set": NotRequired[dict[str, object]],
    "del": NotRequired[list[str]],
    "groups": NotRequired[list[Group] | RowsDelta],
    "metadata": NotRequired[list[MetadataRow] | RowsDelta],
})
