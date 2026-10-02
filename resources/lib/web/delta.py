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

_DELTA_LISTS = ("groups", "metadata")


def _group_shape(groups: list) -> tuple:
    """Return the cards and their rows' ids and labels."""
    return tuple(
        (group.get("id"), group.get("title"),
         tuple((row.get("id"), row.get("label")) for row in group.get("rows", ())))
        for group in groups
    )


def _group_rows_delta(previous: list, current: list) -> list | None:
    """Return changed rows as ``[id, value, detail]``, or None for all."""
    if _group_shape(previous) != _group_shape(current):
        return None
    changed = []
    for was, now in zip(previous, current):
        for old_row, new_row in zip(was.get("rows", ()), now.get("rows", ())):
            if (old_row.get("value") != new_row.get("value")
                    or old_row.get("detail") != new_row.get("detail")):
                changed.append([new_row.get("id"), new_row.get("value"),
                                new_row.get("detail")])
    return changed


def _metadata_shape(rows: list) -> tuple:
    """Return each metadata row's kind, name and cell count (-1 for a value).

    The cell count also catches a table that gained a column (see
    ``snapshot._metadata_row``).
    """
    return tuple(
        (row.get("kind"), row.get("name"),
         len(row["cells"]) if isinstance(row.get("cells"), list) else -1)
        for row in rows
    )


def _metadata_delta(previous: list, current: list) -> list | None:
    """Return changed rows as ``[index, value-or-cells]``, or None for all."""
    if _metadata_shape(previous) != _metadata_shape(current):
        return None
    changed = []
    for index, (was, now) in enumerate(zip(previous, current)):
        if was.get("value") != now.get("value") or was.get("cells") != now.get("cells"):
            changed.append([index, now["cells"] if "cells" in now else now.get("value")])
    return changed


def snapshot_delta(previous: dict, current: dict) -> dict:
    """Return the delta frame from *previous* to *current*."""
    frame: dict = {"seq": current.get("seq", 0)}

    moved = {key: value for key, value in current.items()
             if key != "seq" and key not in _DELTA_LISTS
             and previous.get(key) != value}
    gone = [key for key in previous
            if key not in current and key not in _DELTA_LISTS]
    if moved:
        frame["set"] = moved
    if gone:
        frame["del"] = gone

    for key, rows_delta in (("groups", _group_rows_delta),
                            ("metadata", _metadata_delta)):
        was = previous.get(key) or []
        now = current.get(key) or []
        if was == now:
            continue
        rows = rows_delta(was, now)
        frame[key] = now if rows is None else {"rows": rows}
    return frame
