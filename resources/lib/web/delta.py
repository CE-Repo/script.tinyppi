# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Delta frames: what the event stream sends after the first snapshot.

A browser gets one full snapshot on connect, then only changes.  Most rows
stay fixed for a whole title while the clock and a few figures move five
times a second, so a delta is a few dozen bytes instead of tens of KB, which
matters for a phone's battery.  ``snapshot_delta`` is used by the stream
loop in web/routes.py; js/core.js applies the frames.

The two long lists are diffed by row while their shape (cards, row ids and
labels) is unchanged; otherwise the whole list is sent.  Other keys are
compared and sent whole.
"""

from collections.abc import Callable, Mapping

from web.payloads import DeltaFrame, Group, MetadataRow, RowsDelta, Snapshot

_DELTA_LISTS = ("groups", "metadata")


def _group_shape(groups: list[Group]) -> tuple[object, ...]:
    """Return the cards and their rows' ids and labels."""
    return tuple(
        (group.get("id"), group.get("title"),
         tuple((row.get("id"), row.get("label")) for row in group.get("rows", ())))
        for group in groups
    )


def _group_rows_delta(previous: list[Group], current: list[Group]) -> list[list[object]] | None:
    """Return changed rows as ``[id, value, detail]``, or None for all."""
    if _group_shape(previous) != _group_shape(current):
        return None
    changed: list[list[object]] = []
    for was, now in zip(previous, current, strict=True):
        for old_row, new_row in zip(was.get("rows", ()), now.get("rows", ()), strict=True):
            if (old_row.get("value") != new_row.get("value")
                    or old_row.get("detail") != new_row.get("detail")):
                changed.append([new_row.get("id"), new_row.get("value"),
                                new_row.get("detail")])
    return changed


def _metadata_shape(rows: list[MetadataRow]) -> tuple[object, ...]:
    """Return each metadata row's kind, name and cell count (-1 for a value).

    The cell count also catches a table that gained a column (see
    ``snapshot._metadata_row``).
    """
    return tuple(
        (row.get("kind"), row.get("name"),
         len(row["cells"]) if isinstance(row.get("cells"), list) else -1)
        for row in rows
    )


def _metadata_delta(previous: list[MetadataRow],
                    current: list[MetadataRow]) -> list[list[object]] | None:
    """Return changed rows as ``[index, value-or-cells]``, or None for all."""
    if _metadata_shape(previous) != _metadata_shape(current):
        return None
    changed: list[list[object]] = []
    for index, (was, now) in enumerate(zip(previous, current, strict=True)):
        if was.get("value") != now.get("value") or was.get("cells") != now.get("cells"):
            changed.append([index, now["cells"] if "cells" in now else now.get("value")])
    return changed


def _fields_delta(previous: Mapping[str, object],
                  current: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    """Return the changed (``set``) and removed (``del``) plain fields."""
    moved = {key: value for key, value in current.items()
             if key != "seq" and key not in _DELTA_LISTS
             and previous.get(key) != value}
    gone = [key for key in previous
            if key not in current and key not in _DELTA_LISTS]
    return moved, gone


def _list_delta[Item](
    was: list[Item], now: list[Item],
    rows_delta: Callable[[list[Item], list[Item]], list[list[object]] | None],
) -> list[Item] | RowsDelta | None:
    """Return *now* whole, its changed rows, or None when nothing changed."""
    if was == now:
        return None
    rows = rows_delta(was, now)
    return now if rows is None else {"rows": rows}


def snapshot_delta(previous: Snapshot, current: Snapshot) -> DeltaFrame:
    """Return the delta frame from *previous* to *current*."""
    frame: DeltaFrame = {"seq": current.get("seq", 0)}
    moved, gone = _fields_delta(previous, current)
    if moved:
        frame["set"] = moved
    if gone:
        frame["del"] = gone
    groups = _list_delta(previous.get("groups") or [], current.get("groups") or [],
                         _group_rows_delta)
    if groups is not None:
        frame["groups"] = groups
    metadata = _list_delta(previous.get("metadata") or [], current.get("metadata") or [],
                           _metadata_delta)
    if metadata is not None:
        frame["metadata"] = metadata
    return frame
