# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Delta frames of the event stream (web/delta.py)."""

import copy

from web.delta import snapshot_delta

BASE = {
    "seq": 1, "playing": True, "time": "00:10", "title": "Film",
    "groups": [{"id": "video", "title": "Video", "rows": [
        {"id": "res", "label": "Resolution", "value": "2160p", "detail": ""},
        {"id": "fps", "label": "Frame rate", "value": "23.976", "detail": ""}]}],
    "metadata": [{"kind": "row", "name": "L1 max", "value": "1000"},
                 {"kind": "table", "name": "L2", "cells": ["1", "2"]}],
}


def apply(previous, frame):
    """What js/core.js does with a frame."""
    state = copy.deepcopy(previous)
    state.update(frame.get("set", {}))
    for key in frame.get("del", []):
        state.pop(key, None)
    state["seq"] = frame["seq"]
    groups = frame.get("groups")
    if isinstance(groups, list):
        state["groups"] = groups
    elif groups:
        rows = {row["id"]: row for group in state["groups"] for row in group["rows"]}
        for row_id, value, detail in groups["rows"]:
            rows[row_id]["value"], rows[row_id]["detail"] = value, detail
    metadata = frame.get("metadata")
    if isinstance(metadata, list):
        state["metadata"] = metadata
    elif metadata:
        for index, value in metadata["rows"]:
            row = state["metadata"][index]
            row["cells" if "cells" in row else "value"] = value
    return state


def test_unchanged_snapshot_sends_only_the_sequence():
    current = copy.deepcopy(BASE)
    current["seq"] = 2
    assert snapshot_delta(BASE, current) == {"seq": 2}


def test_changed_values_round_trip():
    current = copy.deepcopy(BASE)
    current.update(seq=2, time="00:11")
    current["groups"][0]["rows"][1]["value"] = "24"
    current["metadata"][0]["value"] = "1200"
    current["metadata"][1]["cells"] = ["3", "4"]
    del current["title"]
    frame = snapshot_delta(BASE, current)
    assert frame["set"] == {"time": "00:11"} and frame["del"] == ["title"]
    assert frame["groups"] == {"rows": [["fps", "24", ""]]}
    assert apply(BASE, frame) == current


def test_a_new_shape_sends_the_whole_list():
    current = copy.deepcopy(BASE)
    current["seq"] = 2
    current["groups"][0]["rows"].append({"id": "hdr", "label": "HDR", "value": "HDR10", "detail": ""})
    current["metadata"][1]["cells"].append("5")
    frame = snapshot_delta(BASE, current)
    assert frame["groups"] == current["groups"] and frame["metadata"] == current["metadata"]
    assert apply(BASE, frame) == current
