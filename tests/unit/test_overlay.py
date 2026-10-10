# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The overlay dialog and the entry points for both views (ui/overlay.py)."""

import io
import os
import threading
import types

import pytest

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from core.utils import PROP_ACTIVE, PROP_DIALOG_MODE, PROP_RUNNING, localized
from info import publish
from ui import dvmetadata, mode_select, overlay

FULLSCREEN = "Window.IsActive(fullscreenvideo)"
CHANGED_COLOR = "TinyPPI.OutputChangedColor"


class Clock:
    """Stands in for the overlay's ``time`` module: time stands still until moved."""

    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now

    def monotonic(self):
        return self.now


class Player:
    def __init__(self, playing=True):
        self.playing = playing

    def isPlaying(self):
        return self.playing


class Monitor:
    """A monitor that ends the loop after *ticks* waits (or when abort is set)."""

    def __init__(self, clock=None, ticks=1, abort=False, step=0.0):
        self.clock, self.ticks, self.abort, self.step = clock, ticks, abort, step
        self.waits = []

    def abortRequested(self):
        return self.abort

    def waitForAbort(self, timeout=None):
        self.waits.append(timeout)
        if self.clock:
            self.clock.now += self.step
        return len(self.waits) >= self.ticks


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(overlay, "time", fake)
    return fake


@pytest.fixture(autouse=True)
def settle(monkeypatch):
    """Let _release_overlay settle without sleeping; record whether re-entry was held."""
    held = []

    def wait(_monitor, timeout=None):
        held.append((timeout, overlay._releasing.is_set()))
        return False

    monkeypatch.setattr(xbmc.Monitor, "waitForAbort", wait)
    return held


def home():
    return xbmcgui.Window(10000)


def use(**values):
    xbmcaddon.SETTINGS.update(
        {key: str(value).lower() if isinstance(value, bool) else str(value)
         for key, value in values.items()})


def make_dialog():
    return overlay.TinyPPIDialog("script-tinyppi-main.xml", overlay._ADDON_PATH, "Default", "1080i")


@pytest.fixture
def opened(clock):
    """Open an overlay as Kodi would (onInit, whose loop ends at once: nothing plays)."""

    def open_with(**settings):
        use(**settings)
        dialog = make_dialog()
        dialog.onInit()
        dialog.join_update_loop()
        clock.now += 1      # past the guard against the key press that opened it
        return dialog

    return open_with


def position(dialog, control_id=5000):
    return dialog.getControl(control_id).position


def moves(dialog, control_id=5000):
    return [args for name, args in dialog.getControl(control_id).calls if name == "setPosition"]


def show_layout(dialog, hdr_type="", channels=False):
    home().setProperty("TinyPPI.EffectiveHdrType", hdr_type)
    home().setProperty("TinyPPI.ShowChannelIcon", "1" if channels else "0")
    dialog.setProperty("ChannelIconVar", "channels/6.png" if channels else "")


# --- Platform and playback checks -------------------------------------------

@pytest.mark.parametrize(("has_dir", "os_release", "expected"), [
    (True, None, True),
    (False, 'NAME="CoreELEC"\nVERSION_ID="22.0"\n', True),
    (False, 'NAME="LibreELEC"\nVERSION_ID="12.0"\n', False),
    (False, OSError, False),
])
def test_coreelec_is_told_from_its_folder_or_os_release(monkeypatch, has_dir, os_release, expected):
    looked_at = []

    def isdir(path):
        looked_at.append(path)
        return has_dir

    def fake_open(path, *args, **kwargs):
        looked_at.append(path)
        if os_release is OSError:
            raise FileNotFoundError(path)
        return io.StringIO(os_release)

    monkeypatch.setattr(overlay, "os", types.SimpleNamespace(path=types.SimpleNamespace(isdir=isdir)))
    monkeypatch.setattr(overlay, "open", fake_open, raising=False)
    assert overlay._is_coreelec() is expected
    assert looked_at == (["/etc/coreelec"] if has_dir else ["/etc/coreelec", "/etc/os-release"])


@pytest.fixture
def ready(monkeypatch, tmp_path):
    """A CoreELEC box on Kodi 22 playing fullscreen video with a 1080p skin."""
    monkeypatch.setattr(xbmcvfs, "HOME", str(tmp_path))
    monkeypatch.setattr(overlay, "_is_coreelec", lambda: True)
    xbmc.INFO["System.BuildVersion"] = "22.0 (22.0.0) Git:20260901-abc"
    xbmc.CONDITIONS[FULLSCREEN] = True
    return tmp_path


def test_a_view_may_open_over_playing_fullscreen_video(ready):
    assert overlay._preflight(home(), Player(), "Toggle close") is True
    assert xbmcgui.DIALOGS == [] and xbmc.BUILTINS == []


@pytest.mark.parametrize(("coreelec", "build", "message"), [
    (False, "22.0 (22.0.0)", 32215),
    (True, "", 32216),
    (True, "Git:20260901", 32216),
    (True, "21.2 (21.2.0) Git:20250101", 32215),
])
def test_an_unsupported_system_is_refused_with_a_notification(monkeypatch, ready, coreelec,
                                                              build, message):
    monkeypatch.setattr(overlay, "_is_coreelec", lambda: coreelec)
    xbmc.INFO["System.BuildVersion"] = build
    assert overlay._preflight(home(), Player(), "Toggle close") is False
    [notice] = xbmcgui.DIALOGS
    assert notice == ("notification",
                      ("TinyPPI", localized(message), xbmcgui.NOTIFICATION_ERROR, 4000), {})


def test_the_platform_checks_can_be_switched_off_for_testing(monkeypatch, ready):
    monkeypatch.setattr(overlay, "_ALLOW_NON_COREELEC", True)
    monkeypatch.setattr(overlay, "_is_coreelec", lambda: False)
    xbmc.INFO["System.BuildVersion"] = ""
    assert overlay._preflight(home(), Player(), "Toggle close") is True
    assert xbmcgui.DIALOGS == []


def test_a_720p_skin_is_refused(ready):
    os.makedirs(ready / "skin" / "720p")
    assert overlay._preflight(home(), Player(), "Toggle close") is False
    assert [args[1] for _name, args, _kw in xbmcgui.DIALOGS] == [localized(32217)]
    assert (xbmc.LOGWARNING, "TinyPPI: 720p skin detected – unsupported") in xbmc.LOG


@pytest.mark.parametrize(("fullscreen", "playing"), [(False, True), (True, False)])
def test_nothing_opens_without_fullscreen_playback(ready, fullscreen, playing):
    xbmc.CONDITIONS[FULLSCREEN] = fullscreen
    assert overlay._preflight(home(), Player(playing), "Toggle close") is False
    assert xbmcgui.DIALOGS == [] and xbmc.BUILTINS == []


def test_a_press_while_open_toggles_the_view_closed(ready):
    home().setProperty(PROP_RUNNING, "true")
    assert overlay._preflight(home(), Player(), "Toggle close (dialog mode)") is False
    assert xbmc.BUILTINS == ["Action(Back)"]
    assert (xbmc.LOGINFO, "TinyPPI: Toggle close (dialog mode)") in xbmc.LOG


def test_a_press_while_the_closed_overlay_settles_is_dropped(monkeypatch, ready):
    releasing = threading.Event()
    releasing.set()
    monkeypatch.setattr(overlay, "_releasing", releasing)
    assert overlay._preflight(home(), Player(), "Toggle close") is False
    assert xbmc.BUILTINS == []


# --- Opening and placing the overlay -----------------------------------------

def test_opening_places_the_overlay_and_the_loop_closes_it_when_nothing_plays(opened):
    home().setProperty(PROP_ACTIVE, "true")
    dialog = opened(offset_x=50, offset_y=50, offset_x_dv=0)
    assert position(dialog) == (297, -152)
    assert position(dialog, 5100) == (-1450, 0)
    assert ("close", ()) in dialog.calls
    assert home().getProperty(PROP_ACTIVE) == ""


@pytest.mark.parametrize(("hdr_type", "channels", "expected"), [
    ("", False, (593, -303)),               # SDR: narrow, may move right
    ("HDR10", False, (0, -303)),            # wide layouts stay left-aligned
    ("", True, (0, -303)),
    ("Dolby Vision", False, (0, -303)),
    ("Dolby Vision", True, (0, 0)),         # the channel panel above keeps its top margin
])
def test_the_configured_offset_follows_the_layout(opened, hdr_type, channels, expected):
    dialog = opened(offset_x=100, offset_y=100)
    show_layout(dialog, hdr_type, channels)
    dialog._apply_position_offset()
    assert position(dialog) == expected


def test_the_channel_icon_alone_does_not_widen_the_layout(opened):
    dialog = opened(offset_x=100)
    home().setProperty("TinyPPI.ShowChannelIcon", "1")      # but the window has no icon
    dialog._apply_position_offset()
    assert position(dialog) == (593, 0)


def test_an_unchanged_placement_is_not_sent_again(opened):
    dialog = opened(offset_x=100, offset_x_dv=50)
    for _ in range(3):
        dialog._apply_position_offset()
    assert moves(dialog) == [(593, 0)]
    assert moves(dialog, 5100) == [(-725, 0)]


@pytest.mark.parametrize(("action", "expected"), [
    (xbmcgui.ACTION_MOVE_LEFT, (-10, 0)),
    (xbmcgui.ACTION_MOVE_RIGHT, (10, 0)),
    (xbmcgui.ACTION_MOVE_UP, (0, -10)),
    (xbmcgui.ACTION_MOVE_DOWN, (0, 10)),
])
def test_the_arrow_keys_nudge_the_overlay_when_enabled(opened, action, expected):
    dialog = opened(nudge_position=True)
    dialog.onAction(xbmcgui.Action(action))
    assert position(dialog) == expected


def test_the_arrow_keys_do_nothing_by_default(opened):
    dialog = opened()
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
    assert moves(dialog) == [(0, 0)]


def test_other_keys_do_not_nudge(opened):
    dialog = opened(nudge_position=True)
    dialog.calls.clear()
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_STOP))
    assert moves(dialog) == [(0, 0)] and dialog.calls == []


def test_the_nudge_stops_at_the_screen_edge_and_comes_back_at_once(opened):
    dialog = opened(nudge_position=True)
    for _ in range(10):
        dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    assert position(dialog) == (-35, 0)
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
    assert position(dialog) == (-25, 0)
    for _ in range(50):
        dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
    assert position(dialog) == (-25, -340)


def test_a_layout_change_pulls_a_nudged_overlay_back_on_screen(opened):
    dialog = opened(nudge_position=True)
    for _ in range(70):
        dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
    assert position(dialog) == (628, 0)                     # narrow SDR box at the right edge
    show_layout(dialog, "HDR10")
    dialog._apply_position_offset()
    assert position(dialog) == (35, 0)                      # the wide box ends at the edge
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    assert position(dialog) == (25, 0)


# --- Keys and closing ----------------------------------------------------------

@pytest.mark.parametrize("action", [xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK])
def test_back_closes_the_overlay(opened, action):
    dialog = opened()
    dialog.calls.clear()
    home().setProperty(PROP_ACTIVE, "true")
    dialog.onAction(xbmcgui.Action(action))
    assert dialog.calls == [("close", ())]
    assert home().getProperty(PROP_ACTIVE) == "" and dialog.next_view is None


def test_keys_right_after_opening_are_ignored(opened, clock):
    dialog = opened()
    dialog.calls.clear()
    clock.now -= 0.9            # 0.1 s after onInit
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert dialog.calls == []


def test_a_click_closes_the_overlay(opened):
    dialog = opened()
    dialog.calls.clear()
    dialog.onClick(5000)
    assert dialog.calls == [("close", ())]


def test_closing_survives_a_window_that_is_already_gone(monkeypatch):
    dialog = make_dialog()
    dialog._running = True
    home().setProperty(PROP_ACTIVE, "true")

    def gone():
        raise RuntimeError("window gone")

    monkeypatch.setattr(dialog, "close", gone)
    dialog.close_dialog()
    assert home().getProperty(PROP_ACTIVE) == "" and dialog._running is False


@pytest.mark.parametrize(("enabled", "source", "next_view"), [
    (True, "Dolby Vision", "dv_metadata"),
    (False, "Dolby Vision", None),
    (True, "HDR10", None),
])
def test_ok_hands_a_dolby_vision_source_over_to_the_metadata_view(opened, enabled, source,
                                                                  next_view):
    dialog = opened(dv_metadata_view=enabled)
    dialog.calls.clear()
    home().setProperty("TinyPPI.HdrType", source)
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert dialog.next_view == next_view
    assert dialog.calls == ([("close", ())] if next_view else [])


# --- Highlighting changed Dolby Vision readings --------------------------------

def remembered(color="FFFF0000", **shown):
    if color:
        home().setProperty(CHANGED_COLOR, color)
    use(output_changed_duration=2000)
    dialog = make_dialog()
    for name, value in shown.items():
        dialog.setProperty(name, value)
    dialog._remember_dv_values()
    return dialog


def test_a_changed_dv_reading_is_highlighted_for_the_set_duration(clock):
    dialog = remembered(DoviProfileNumberVar="8", DoviCmVersionVar="CM v4.0")
    dialog.published = {"TinyPPI.HdrType": "Dolby Vision", "DoviProfileNumberVar": "7",
                        "DoviCmVersionVar": "CM v4.0"}
    dialog._highlight_dv_changes()
    assert dialog.getProperty("DoviProfileNumberVar") == "[COLOR=FFFF0000]7[/COLOR]"
    assert dialog.getProperty("DoviCmVersionVar") == "CM v4.0"
    clock.now += 1.9
    dialog._highlight_dv_changes()
    assert dialog.getProperty("DoviProfileNumberVar") == "[COLOR=FFFF0000]7[/COLOR]"
    clock.now += 0.2
    dialog._highlight_dv_changes()
    assert dialog.getProperty("DoviProfileNumberVar") == "7"


def test_opening_values_are_not_highlighted(clock):
    dialog = remembered(DoviProfileNumberVar="8")
    dialog.published = {"TinyPPI.HdrType": "Dolby Vision", "DoviProfileNumberVar": "8"}
    dialog._highlight_dv_changes()
    assert dialog.getProperty("DoviProfileNumberVar") == "8"


def test_readings_outside_dolby_vision_are_never_highlighted(clock):
    dialog = remembered(Hdr10MdlVar="1000 nits")
    dialog.published = {"TinyPPI.HdrType": "HDR10", "Hdr10MdlVar": "4000 nits"}
    dialog._highlight_dv_changes()
    assert dialog.getProperty("Hdr10MdlVar") == "4000 nits"


def test_nothing_is_highlighted_before_the_overlay_is_initialised(clock):
    dialog = make_dialog()
    dialog.published = {"TinyPPI.HdrType": "Dolby Vision", "DoviProfileNumberVar": "7"}
    dialog._highlight_dv_changes()
    assert dialog.getProperty("DoviProfileNumberVar") == ""


def test_without_a_themed_color_the_default_blue_is_used_and_logged_once(clock):
    dialog = remembered(color="", DoviProfileNumberVar="8")
    dialog.published = {"TinyPPI.HdrType": "Dolby Vision", "DoviProfileNumberVar": "7"}
    dialog._highlight_dv_changes()
    assert dialog.getProperty("DoviProfileNumberVar") == "[COLOR=FF82B1FF]7[/COLOR]"
    dialog._dv_changed_color()
    warnings = [line for level, line in xbmc.LOG
                if level == xbmc.LOGWARNING and CHANGED_COLOR in line]
    assert warnings == ["TinyPPI: TinyPPI.OutputChangedColor is not published, highlighting "
                        "changed overlay values in FF82B1FF instead"]


# --- The update loop -----------------------------------------------------------

@pytest.fixture
def loop(monkeypatch, clock):
    """A dialog whose update loop runs in the test thread with recorded publishes."""
    seen = {"scene": 0, "static": 0}

    def scene(window, published):
        seen["scene"] += 1

    def static(window, published):
        seen["static"] += 1

    monkeypatch.setattr(publish, "publish_scene_properties", scene)
    monkeypatch.setattr(publish, "update_static_properties", static)
    monkeypatch.setattr(xbmc, "Player", Player)
    xbmc.CONDITIONS[FULLSCREEN] = True
    home().setProperty(PROP_ACTIVE, "true")
    dialog = make_dialog()
    dialog._running = True
    dialog._opened_at = clock.now
    dialog.seen = seen
    return dialog


@pytest.mark.parametrize("stop", ["playback", "fullscreen", "auto_hide", "abort", "running"])
def test_the_loop_closes_the_overlay_when_it_should_go(monkeypatch, loop, clock, stop):
    loop._monitor = Monitor(abort=stop == "abort")
    if stop == "playback":
        monkeypatch.setattr(xbmc, "Player", lambda: Player(playing=False))
    elif stop == "fullscreen":
        xbmc.CONDITIONS[FULLSCREEN] = False
    elif stop == "auto_hide":
        loop._auto_hide = 5
        clock.now += 5
    elif stop == "running":
        loop._running = False
    loop._update_loop()
    assert loop.seen == {"scene": 0, "static": 0}
    assert ("close", ()) in loop.calls and home().getProperty(PROP_ACTIVE) == ""


def test_the_loop_refreshes_until_auto_hide_ends_it(loop, clock):
    loop._auto_hide = 5
    loop._monitor = Monitor(clock, ticks=99, step=1.0)
    loop._update_loop()
    assert loop.seen["scene"] == 5
    assert loop._monitor.waits == [0.1] * 5
    assert ("close", ()) in loop.calls


def test_per_title_readings_refresh_on_the_slow_cadence(loop, clock):
    home().setProperty(CHANGED_COLOR, "FFFF0000")
    loop._monitor = Monitor(clock, ticks=4, step=0.4)       # ticks at 0, 0.4, 0.8 and 1.2 s
    loop._update_loop()
    assert loop.seen == {"scene": 4, "static": 2}
    assert loop._changed_color == "FFFF0000"


def test_the_loop_highlights_the_readings_each_tick_publishes(monkeypatch, loop, clock):
    home().setProperty(CHANGED_COLOR, "FFFF0000")
    loop.setProperty("DoviProfileNumberVar", "8")
    loop._remember_dv_values()

    def scene(window, published):
        published.update({"TinyPPI.HdrType": "Dolby Vision", "DoviProfileNumberVar": "7"})

    monkeypatch.setattr(publish, "publish_scene_properties", scene)
    loop._monitor = Monitor(clock, ticks=1)
    loop._update_loop()
    assert loop.getProperty("DoviProfileNumberVar") == "[COLOR=FFFF0000]7[/COLOR]"


def test_the_loop_follows_a_layout_change_while_it_runs(monkeypatch, loop, clock):
    loop._offset_pct = (100, 0)

    def scene(window, published):
        if loop.seen["scene"] == 1:
            show_layout(window, "HDR10")      # the HDR type is detected late
        loop.seen["scene"] += 1

    monkeypatch.setattr(publish, "publish_scene_properties", scene)
    loop._monitor = Monitor(clock, ticks=3)
    loop._update_loop()
    assert moves(loop) == [(593, 0), (0, 0)]


def test_a_failing_refresh_is_logged_once_and_the_loop_goes_on(monkeypatch, loop, clock):
    def broken(window, published):
        raise RuntimeError("no window")

    monkeypatch.setattr(publish, "publish_scene_properties", broken)
    loop._monitor = Monitor(clock, ticks=3, step=0.1)
    loop._update_loop()
    assert loop._monitor.waits == [0.1] * 3
    failures = [entry for entry in xbmc.LOG if "refresh failed" in entry[1]]
    assert failures == [(xbmc.LOGWARNING,
                         "TinyPPI: overlay refresh failed, continuing with the last values: "
                         "no window")]
    assert ("close", ()) in loop.calls


# --- Entry points ----------------------------------------------------------------

def test_showing_the_overlay_fills_it_first_and_waits_for_its_loop(monkeypatch, clock):
    order = []
    shown = []

    def fill(window, published):
        order.append(("publish", window))
        window.setProperty("TinyPPI.HdrType", "Dolby Vision")

    def do_modal(dialog):
        order.append(("doModal", dialog))
        shown.append((dialog, home().getProperty(PROP_ACTIVE)))
        dialog.onInit()          # Kodi runs onInit once the window shows
        dialog.next_view = "dv_metadata"

    monkeypatch.setattr(publish, "publish_properties", fill)
    monkeypatch.setattr(overlay.TinyPPIDialog, "doModal", do_modal)
    assert overlay._show_overlay(home()) == "dv_metadata"
    [(dialog, active)] = shown
    assert order == [("publish", dialog), ("doModal", dialog)]
    assert active == "true"
    assert not dialog._thread.is_alive()


@pytest.fixture
def entry(monkeypatch):
    """Stand-ins for what the entry points call around the views."""
    record = types.SimpleNamespace(preflight=[], fonts=0, themes=[], channels=[], shown=[],
                                   dv_views=0, dialogs=[], show_results=[None],
                                   dv_results=[], preflight_ok=True)

    def preflight(window, player, toggle_log):
        record.preflight.append(toggle_log)
        return record.preflight_ok

    def fonts():
        record.fonts += 1

    def theme(window, addon):
        record.themes.append(addon.getSetting("background_opacity"))

    def show(window):
        record.shown.append({prop: window.getProperty(prop)
                             for prop in (PROP_RUNNING, PROP_ACTIVE, PROP_DIALOG_MODE)})
        return record.show_results.pop(0)

    def dv_view():
        record.dv_views += 1
        return record.dv_results.pop(0)

    def dialog():
        record.dialogs.append({prop: home().getProperty(prop)
                               for prop in (PROP_RUNNING, PROP_ACTIVE, PROP_DIALOG_MODE)})

    monkeypatch.setattr(overlay, "_preflight", preflight)
    monkeypatch.setattr(overlay, "ensure_fonts", fonts)
    monkeypatch.setattr(overlay, "apply_theme", theme)
    monkeypatch.setattr(publish, "publish_channel_visibility", record.channels.append)
    monkeypatch.setattr(overlay, "_show_overlay", show)
    monkeypatch.setattr(dvmetadata, "open_dv_metadata", dv_view)
    monkeypatch.setattr(mode_select, "open_dialog", dialog)
    return record


CLOSED_STATE = (PROP_RUNNING, PROP_ACTIVE, PROP_DIALOG_MODE)


def state():
    return {prop: home().getProperty(prop) for prop in CLOSED_STATE}


@pytest.mark.parametrize(("opacity", "l5_icon", "filename", "visible", "l5"), [
    (98, True, False, "1", "1"),
    (0, False, True, "0", "0"),
])
def test_the_overlay_opens_with_its_settings_and_releases_the_state(entry, settle, opacity,
                                                                    l5_icon, filename, visible, l5):
    use(background_opacity=opacity, show_l5_icon=l5_icon, filename=filename)
    home().setProperty(PROP_DIALOG_MODE, "true")         # left over from the dialog
    overlay.open_tinyppi()
    assert entry.preflight == ["Toggle close"] and entry.fonts == 1
    assert entry.shown == [{PROP_RUNNING: "true", PROP_ACTIVE: "true", PROP_DIALOG_MODE: ""}]
    [channel_window] = entry.channels
    assert channel_window.getProperty("TinyPPI.ShowL5Icon") == l5     # the Home window
    assert entry.themes == [str(opacity)]
    assert home().getProperty("TinyPPI.Filename") == str(filename).lower()
    assert home().getProperty("TinyPPI.ShowL5Icon") == l5
    for name in ("TinyPPI.ShowLine", "TinyPPI.ShowHeaderTitle", "TinyPPI.ShowHeaderIcon"):
        assert home().getProperty(name) == visible
    assert state() == dict.fromkeys(CLOSED_STATE, "")
    assert settle == [(0.2, True)] and not overlay._releasing.is_set()


@pytest.mark.parametrize(("show_results", "dv_results", "shown", "dv_views"), [
    (["dv_metadata", "dv_metadata", None], [True, True], 3, 2),   # Back returns to the overlay
    (["dv_metadata"], [False], 1, 1),                             # the view ended the session
])
def test_ok_and_back_switch_between_the_overlay_and_the_metadata_view(entry, show_results,
                                                                     dv_results, shown, dv_views):
    entry.show_results, entry.dv_results = list(show_results), list(dv_results)
    overlay.open_tinyppi()
    assert len(entry.shown) == shown and entry.dv_views == dv_views
    assert state() == dict.fromkeys(CLOSED_STATE, "")


def test_the_state_is_released_even_when_the_overlay_fails(monkeypatch, entry, settle):
    def broken(window):
        raise RuntimeError("no skin file")

    monkeypatch.setattr(overlay, "_show_overlay", broken)
    with pytest.raises(RuntimeError):
        overlay.open_tinyppi()
    assert state() == dict.fromkeys(CLOSED_STATE, "")
    assert settle == [(0.2, True)]


def test_the_dialog_mode_opens_the_vs10_dialog(entry, settle):
    use(background_opacity=0)
    overlay.open_dialog_mode()
    assert entry.preflight == ["Toggle close (dialog mode)"] and entry.fonts == 1
    assert entry.dialogs == [{PROP_RUNNING: "true", PROP_ACTIVE: "true", PROP_DIALOG_MODE: "true"}]
    assert entry.themes == ["0"] and entry.shown == []
    assert "TinyPPI.Filename" not in xbmcgui.PROPERTIES[10000]
    for name in ("TinyPPI.ShowLine", "TinyPPI.ShowHeaderTitle", "TinyPPI.ShowHeaderIcon"):
        assert home().getProperty(name) == "0"
    assert state() == dict.fromkeys(CLOSED_STATE, "")
    assert settle == [(0.2, True)]


@pytest.mark.parametrize(("open_view", "toggle_log"), [
    (overlay.open_tinyppi, "Toggle close"),
    (overlay.open_dialog_mode, "Toggle close (dialog mode)"),
])
def test_a_refused_check_opens_nothing_and_frees_the_next_press(entry, settle, open_view,
                                                                toggle_log):
    entry.preflight_ok = False
    open_view()
    assert entry.preflight == [toggle_log]
    assert entry.fonts == 0 and entry.shown == [] and entry.dialogs == []
    assert settle == []
    assert overlay._opening.acquire(blocking=False)
    overlay._opening.release()


@pytest.mark.parametrize("open_view", [overlay.open_tinyppi, overlay.open_dialog_mode])
def test_a_second_press_while_opening_is_dropped(entry, open_view):
    assert overlay._opening.acquire(blocking=False)
    try:
        open_view()
    finally:
        overlay._opening.release()
    assert entry.preflight == [] and entry.shown == [] and entry.dialogs == []
    assert (xbmc.LOGDEBUG, "TinyPPI: open request dropped: TinyPPI is already opening") in xbmc.LOG
