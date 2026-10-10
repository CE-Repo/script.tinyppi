# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The background service's notification handling (service/monitor.py)."""

import os
import runpy
import sys
import threading
import types

import pytest
from service import monitor as service

import xbmc
import xbmcaddon
import xbmcgui
from core.constants import OPEN_WITHDRAWN, PROP_OPEN_ACK, PROP_OPEN_REQUEST, PROP_SERVICE
from ui import theme
from web import library, server


class Threads:
    """Stands in for threading.Thread: records the targets, runs on demand."""

    def __init__(self):
        self.started = []

    def __call__(self, target, args=(), **_kwargs):
        started = self.started
        return types.SimpleNamespace(start=lambda: started.append((target, args)))

    def run_all(self):
        while self.started:
            target, args = self.started.pop(0)
            target(*args)


@pytest.fixture
def threads(monkeypatch):
    fake = Threads()
    monkeypatch.setattr(service.threading, "Thread", fake)
    return fake


@pytest.fixture
def calls(monkeypatch):
    """Record the library hooks the notifications trigger."""
    seen = []
    for name in ("invalidate", "changed", "settle"):
        monkeypatch.setattr(library, name, lambda name=name: seen.append(name))
    return seen


@pytest.mark.parametrize(("method", "expected"), [
    ("VideoLibrary.OnScanFinished", ["invalidate"]),
    ("VideoLibrary.OnCleanFinished", ["invalidate"]),
    ("VideoLibrary.OnUpdate", ["changed"]),
    ("VideoLibrary.OnRemove", ["changed"]),
    ("Player.OnStop", ["settle"]),
    ("Player.OnPause", []),
])
def test_library_notifications(threads, calls, method, expected):
    service.KodiMonitor().onNotification("xbmc", method, "{}")
    assert calls == expected


def test_every_notification_is_logged_cut_short(threads, calls):
    service.KodiMonitor().onNotification("xbmc", "Player.OnPause", "x" * 500)
    [(_level, line)] = [entry for entry in xbmc.LOG if "method=Player.OnPause" in entry[1]]
    assert line.endswith("x" * 200) and "x" * 201 not in line


def test_an_open_request_is_acknowledged_and_run(threads, monkeypatch):
    opened = []
    overlay = types.SimpleNamespace(open_tinyppi=lambda: opened.append("overlay"),
                                    open_dialog_mode=lambda: opened.append("dialog"))
    monkeypatch.setitem(sys.modules, "ui.overlay", overlay)
    home = xbmcgui.Window(10000)
    for message, view in (("open_overlay", "overlay"), ("open_dialog", "dialog")):
        home.setProperty(PROP_OPEN_REQUEST, f"token-{view}")
        service.KodiMonitor().onNotification("script.tinyppi", f"Other.{message}", "")
        assert home.getProperty(PROP_OPEN_ACK) == f"token-{view}"
        assert home.getProperty(PROP_OPEN_REQUEST) == ""
    threads.run_all()
    assert opened == ["overlay", "dialog"]


def test_open_messages_from_other_senders_are_ignored(threads):
    service.KodiMonitor().onNotification("someone.else", "Other.open_overlay", "")
    assert threads.started == []


def test_a_withdrawn_request_opens_nothing(threads):
    home = xbmcgui.Window(10000)
    home.setProperty(PROP_OPEN_REQUEST, OPEN_WITHDRAWN)
    service.KodiMonitor().onNotification("script.tinyppi", "Other.open_overlay", "")
    assert threads.started == []
    assert home.getProperty(PROP_OPEN_ACK) == OPEN_WITHDRAWN
    assert home.getProperty(PROP_OPEN_REQUEST) == ""


def test_a_failing_view_is_logged(threads, monkeypatch):
    def broken():
        raise RuntimeError("no window")
    monkeypatch.setitem(sys.modules, "ui.overlay",
                        types.SimpleNamespace(open_tinyppi=broken, open_dialog_mode=broken))
    service.KodiMonitor().onNotification("script.tinyppi", "Other.open_overlay", "")
    threads.run_all()
    assert (xbmc.LOGERROR, "TinyPPI [service]: Exception opening the overlay view: no window") in xbmc.LOG


def test_a_skin_load_registers_the_fonts(threads, monkeypatch):
    installed = []
    monkeypatch.setattr(service.fonts, "ensure_fonts", lambda: installed.append(1))
    monkeypatch.setattr(service.KodiMonitor, "waitForAbort", lambda self, timeout=None: False)
    service.KodiMonitor().onNotification("xbmc", "GUI.OnSkinLoaded", "")
    threads.run_all()
    assert installed == [1]


def test_no_font_work_while_kodi_stops(threads, monkeypatch):
    waits = []
    monkeypatch.setattr(service.fonts, "ensure_fonts", pytest.fail)
    monkeypatch.setattr(service.KodiMonitor, "waitForAbort",
                        lambda self, timeout=None: waits.append(timeout) or True)
    service.KodiMonitor().onNotification("xbmc", "GUI.OnSkinLoaded", "")
    assert len(threads.started) == 1            # off Kodi's notification thread
    threads.run_all()
    assert waits == [service._SKIN_SETTLE]
    assert [entry for entry in xbmc.LOG if entry[0] >= xbmc.LOGWARNING] == []


def splash_ran(threads, monkeypatch, video=True, **flags):
    for name in ("splash_enabled", "splash_show_on_osd", "splash_show_on_tinyppi"):
        xbmcaddon.SETTINGS[name] = "true" if flags.get(name) else "false"
    xbmc.CONDITIONS["Player.HasVideo"] = video
    ran = []
    monkeypatch.setitem(sys.modules, "ui.splash",
                        types.SimpleNamespace(open_splash=lambda: ran.append(1)))
    service.KodiMonitor().onNotification("xbmc", "Player.OnAVStart", "")
    threads.run_all()
    return bool(ran)


def test_the_splash_starts_only_when_enabled_for_a_video(threads, monkeypatch):
    assert not splash_ran(threads, monkeypatch)
    assert not splash_ran(threads, monkeypatch, video=False, splash_enabled=True)
    assert splash_ran(threads, monkeypatch, splash_enabled=True)
    assert splash_ran(threads, monkeypatch, splash_show_on_osd=True)
    assert splash_ran(threads, monkeypatch, splash_show_on_tinyppi=True)


def test_one_splash_at_a_time(threads, monkeypatch):
    xbmcaddon.SETTINGS["splash_enabled"] = "true"
    xbmc.CONDITIONS["Player.HasVideo"] = True
    kodi = service.KodiMonitor()
    kodi.onNotification("xbmc", "Player.OnAVStart", "")
    kodi.onNotification("xbmc", "Player.OnAVStart", "")
    assert len(threads.started) == 1
    monkeypatch.setitem(sys.modules, "ui.splash", types.SimpleNamespace(open_splash=lambda: None))
    threads.run_all()
    kodi.onNotification("xbmc", "Player.OnAVStart", "")     # the lock was released
    assert len(threads.started) == 1


def test_a_failing_splash_releases_its_lock(threads, monkeypatch):
    xbmcaddon.SETTINGS["splash_enabled"] = "true"
    xbmc.CONDITIONS["Player.HasVideo"] = True

    def broken():
        raise RuntimeError("boom")
    monkeypatch.setitem(sys.modules, "ui.splash", types.SimpleNamespace(open_splash=broken))
    kodi = service.KodiMonitor()
    kodi.onNotification("xbmc", "Player.OnAVStart", "")
    threads.run_all()
    assert any("Exception in the splash: boom" in line for _level, line in xbmc.LOG)
    kodi.onNotification("xbmc", "Player.OnAVStart", "")
    assert len(threads.started) == 1


def test_settings_changes_reach_the_dashboard(threads):
    applied = []
    dashboard = types.SimpleNamespace(apply_settings=lambda: applied.append(1))
    service.KodiMonitor(dashboard).onSettingsChanged()
    assert applied == [1]


def test_a_failing_dashboard_does_not_take_the_monitor_down(threads):
    def broken():
        raise OSError("port in use")
    service.KodiMonitor(types.SimpleNamespace(apply_settings=broken)).apply_dashboard_settings()
    service.KodiMonitor(None).apply_dashboard_settings()
    assert (xbmc.LOGERROR,
            "TinyPPI [service]: Exception applying web dashboard settings: port in use") in xbmc.LOG


def test_the_warm_up_skips_everything_while_kodi_stops(monkeypatch):
    waits = []
    monkeypatch.setattr(service.fonts, "ensure_fonts", pytest.fail)
    monkeypatch.setattr(service.images, "prune_cache", pytest.fail)
    stopping = types.SimpleNamespace(waitForAbort=lambda timeout=None: waits.append(timeout) or True)
    service._warm_up(stopping)
    assert waits == [service._WARMUP_DELAY]
    assert xbmc.LOG == []


def test_the_warm_up_registers_fonts_and_prunes_textures(monkeypatch):
    done = []
    monkeypatch.setattr(service.fonts, "ensure_fonts", lambda: done.append("fonts"))
    monkeypatch.setattr(service.images, "prune_cache",
                        lambda media: done.append(media.replace("\\", "/")) or 2)
    service._warm_up(types.SimpleNamespace(waitForAbort=lambda timeout=None: False))
    assert done[0] == "fonts"
    assert done[1].endswith("resources/skins/Default/media")
    assert any("removed 2 outdated" in line for _level, line in xbmc.LOG)


def test_the_warm_up_is_quiet_when_nothing_was_pruned(monkeypatch):
    pruned = []
    monkeypatch.setattr(service.fonts, "ensure_fonts", lambda: None)
    monkeypatch.setattr(service.images, "prune_cache", lambda media: pruned.append(media) or 0)
    service._warm_up(types.SimpleNamespace(waitForAbort=lambda timeout=None: False))
    assert len(pruned) == 1
    assert not any("outdated" in line for _level, line in xbmc.LOG)


def test_a_failing_font_registration_is_logged(threads, monkeypatch):
    def read_only():
        raise OSError("read-only skin")
    monkeypatch.setattr(service.fonts, "ensure_fonts", read_only)
    monkeypatch.setattr(service.KodiMonitor, "waitForAbort", lambda self, timeout=None: False)
    service.KodiMonitor().onNotification("xbmc", "GUI.OnSkinLoaded", "")
    threads.run_all()
    assert (xbmc.LOGERROR,
            "TinyPPI [service]: Exception registering the fonts: read-only skin") in xbmc.LOG


def test_unreadable_settings_start_no_splash(threads, monkeypatch):
    def unregistered():
        raise RuntimeError("add-on being updated")
    monkeypatch.setattr(service.settings, "addon", unregistered)
    service.KodiMonitor().onNotification("xbmc", "Player.OnAVStart", "")
    assert threads.started == []
    assert (xbmc.LOGERROR,
            "TinyPPI [service]: Exception starting splash: add-on being updated") in xbmc.LOG


# --- The service script -------------------------------------------------------

LIB = os.path.dirname(os.path.dirname(os.path.abspath(service.__file__)))


def run_service(monkeypatch, moved=0, broken=()):
    """Run service/monitor.py as Kodi starts it; return what happened, in order.

    *broken* names the steps that raise, as they are recorded in the events.
    """
    events = []

    def step(name, result=None):
        def run(*_args, **_kwargs):
            if name in broken:
                raise RuntimeError(f"{name} broke")
            events.append(name)
            return result
        return run

    class Dashboard:
        apply_settings = step("dashboard applied")

        def stop(self, final=False):
            step("dashboard stopped")()
            events.append(("final", final))

    def wait_for_abort(_monitor, timeout=None):
        events.append(("running", home.getProperty(PROP_SERVICE)))
        return True

    home = xbmcgui.Window(10000)
    started = []
    monkeypatch.setattr(server, "WebDashboard", Dashboard)
    monkeypatch.setattr(theme, "migrate_legacy_colors", step("colors", moved))
    monkeypatch.setattr(theme, "apply_theme", step("theme"))
    monkeypatch.setattr(threading, "Thread", lambda target, args=(), **_kwargs:
                        types.SimpleNamespace(start=lambda: started.append((target, args))))
    monkeypatch.setattr(xbmc.Monitor, "waitForAbort", wait_for_abort)
    # Started by Kodi, the script finds its own folder missing from sys.path.
    monkeypatch.setattr(sys, "path", [path for path in sys.path if path != LIB])
    runpy.run_path(service.__file__, run_name="__main__")
    assert sys.path[0] == LIB
    return events, started


def test_the_service_starts_everything_and_stops_the_dashboard_at_shutdown(monkeypatch):
    events, started = run_service(monkeypatch)
    assert events == ["colors", "theme", "dashboard applied", ("running", "1"),
                      "dashboard stopped", ("final", True)]
    assert xbmcgui.Window(10000).getProperty(PROP_SERVICE) == ""   # no handovers any more
    [(target, (monitor,))] = started
    assert target.__name__ == "_warm_up" and type(monitor).__name__ == "KodiMonitor"
    assert (xbmc.LOGINFO, "TinyPPI [service]: KodiMonitor started") in xbmc.LOG
    assert not any("color setting" in line for _level, line in xbmc.LOG)


def test_the_service_reports_carried_over_colors(monkeypatch):
    run_service(monkeypatch, moved=3)
    assert (xbmc.LOGINFO,
            "TinyPPI [service]: carried 3 color setting(s) over to the color picker") in xbmc.LOG


def test_failing_startup_and_shutdown_steps_never_stop_the_service(monkeypatch):
    events, started = run_service(monkeypatch, broken={"colors", "theme", "dashboard stopped"})
    assert events == ["dashboard applied", ("running", "1")]
    assert xbmcgui.Window(10000).getProperty(PROP_SERVICE) == ""
    assert len(started) == 1
    problems = [entry for entry in xbmc.LOG if entry[0] >= xbmc.LOGWARNING]
    assert problems == [
        (xbmc.LOGWARNING,
         "TinyPPI [service]: carrying the color settings over failed: colors broke"),
        (xbmc.LOGWARNING, "TinyPPI [service]: apply_theme at startup failed: theme broke"),
        (xbmc.LOGERROR,
         "TinyPPI [service]: stopping the web dashboard failed: dashboard stopped broke"),
    ]


def test_the_warm_up_carries_on_past_every_failure(monkeypatch):
    def broken(*_args):
        raise OSError("no access")
    monkeypatch.setattr(service.fonts, "ensure_fonts", broken)
    monkeypatch.setitem(sys.modules, "ui.mode_select", None)      # the import fails
    monkeypatch.setattr(service.images, "prune_cache", broken)
    service._warm_up(types.SimpleNamespace(waitForAbort=lambda timeout=None: False))
    warnings = [line for level, line in xbmc.LOG if level == xbmc.LOGWARNING]
    assert warnings[0] == "TinyPPI [service]: registering the fonts failed: no access"
    assert warnings[1].startswith("TinyPPI [service]: pre-loading the views failed: ")
    assert warnings[2] == "TinyPPI [service]: tidying the texture cache failed: no access"
    assert len(warnings) == 3
