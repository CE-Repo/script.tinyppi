# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Delta frames: what a stream sends after the first snapshot.

``snapshot_delta`` is what the stream loop in web/routes.py measures every
frame after the first with, and js/core.js is what patches them back
together.
"""

# The stream sends one whole snapshot when a browser connects and only what
# moved after that.  Almost nothing does: a title's rows are written once and
# then stand for two hours, while the clock and a handful of figures move five
# times a second -- so a delta is a few dozen bytes where the snapshot it
# replaces is tens of kilobytes, which on a phone is the difference between a
# background tab that costs nothing and one that costs a battery.
#
# The two long lists are diffed by row.  Their *shape* -- which cards exist,
# which rows they hold and what those are called -- decides how: unchanged, and
# only the readings that moved are sent; changed at all, and the whole list
# goes, because a page cannot patch rows into a list it does not have yet.
# Everything else is compared whole and sent whole, each being small.

_DELTA_LISTS = ("groups", "metadata")


def _group_shape(groups: list) -> tuple:
    """Which cards a snapshot has, and which rows under which names."""
    return tuple(
        (group.get("id"), group.get("title"),
         tuple((row.get("id"), row.get("label")) for row in group.get("rows", ())))
        for group in groups
    )


def _group_rows_delta(previous: list, current: list) -> list | None:
    """Changed rows as ``[id, value, detail]``, or None to send the lot."""
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
    """The metadata list's shape: what each row is and how wide it is.

    A trim row carries cells and every other row a single value (see
    ``snapshot._metadata_row``), so the width tells the two apart as well as
    catching a table that gained a column.
    """
    return tuple(
        (row.get("kind"), row.get("name"),
         len(row["cells"]) if isinstance(row.get("cells"), list) else -1)
        for row in rows
    )


def _metadata_delta(previous: list, current: list) -> list | None:
    """Changed rows as ``[index, value-or-cells]``, or None to send the lot."""
    if _metadata_shape(previous) != _metadata_shape(current):
        return None
    changed = []
    for index, (was, now) in enumerate(zip(previous, current)):
        if was.get("value") != now.get("value") or was.get("cells") != now.get("cells"):
            changed.append([index, now["cells"] if "cells" in now else now.get("value")])
    return changed


def snapshot_delta(previous: dict, current: dict) -> dict:
    """One delta frame: what ``current`` has that ``previous`` did not."""
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
