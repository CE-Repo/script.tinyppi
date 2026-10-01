# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

import threading

from ui import overlay


def test_a_second_open_while_the_first_is_on_its_way_up_is_dropped(
        kodi, monkeypatch):
    inside = threading.Event()
    release = threading.Event()
    calls = []

    def slow_preflight(home, player, toggle_log):
        calls.append(toggle_log)
        inside.set()
        release.wait(2)
        return False          # the first request then ends without a view

    monkeypatch.setattr(overlay, "_preflight", slow_preflight)

    first = threading.Thread(target=overlay.open_tinyppi)
    first.start()
    assert inside.wait(2)

    overlay.open_tinyppi()        # arrives while the first is in its guards
    overlay.open_dialog_mode()

    release.set()
    first.join(2)
    assert calls == ["Toggle close"]
    assert sum("dropped" in line for line, _ in kodi.logged) == 2

    # And the guard is free again afterwards.
    overlay.open_tinyppi()
    assert len(calls) == 2


def test_the_guard_is_released_when_the_preflight_raises(monkeypatch):
    def broken(*args):
        raise RuntimeError("no player")

    monkeypatch.setattr(overlay, "_preflight", broken)
    for _ in range(2):
        try:
            overlay.open_tinyppi()
        except RuntimeError:
            pass
    assert not overlay._opening.locked()
