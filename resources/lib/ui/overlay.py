# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The TinyPPI overlay dialog and the entry points for both views.

Imported by main.py (which sets up sys.path) and by the service.
"""

import os
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from core import settings
from core.log import log
from core.utils import (
    PROP_ACTIVE,
    PROP_DIALOG_MODE,
    PROP_RUNNING,
    ChangeHighlighter,
    clear_overlay_state,
    effective_hdr_type,
    highlight_hold,
    home_window,
    is_effective_dv,
    join_refresh_thread,
    localized,
    log_refresh_failure,
    read_pass,
    set_window_properties,
)
from info import properties
from ui.fonts import ensure_fonts
from ui.theme import apply_theme

# --- Constants -------------------------------------------------------------

# The add-on folder, fixed while Kodi runs.  Settings and strings are read
# through _settings() and localized(), so changes are seen.
_ADDON_PATH = settings.addon().getAddonInfo("path")

# Set while a closed overlay settles (see _release_overlay); a press then is
# dropped rather than opening it again at once.
_releasing = threading.Event()

# Held from the _preflight guards until TinyPPI is marked open.  The service
# handles each request on its own thread, so a second press in that window
# would stack a second view; it is dropped instead.  Once open, a press
# toggles TinyPPI closed.
_opening = threading.Lock()

# Set True to allow launching on non-CoreELEC platforms (for testing).
_ALLOW_NON_COREELEC = False

# Arrow-key nudge: pixels per press.  Only when enabled (see _nudge_enabled)
# and never saved; the next launch starts from the configured offsets.
_NUDGE_STEP = 10

# Outer edges of the content in group 5000 (see the skin XML); offsets and
# nudge are clamped to keep them on screen.
_CONTENT_LEFT         = 35
_CONTENT_BOTTOM       = 1045
_CONTENT_TOP          = 340
_CONTENT_TOP_DV       = 37    # DV with channels: separate panel above the main box
_CONTENT_RIGHT_NARROW = 1292  # SDR without channels
_CONTENT_RIGHT_WIDE   = 1885  # HDR, and SDR with channels

# Skin x of the DV channel panel (control 5100); offset_x_dv slides it left,
# to _CONTENT_LEFT at 0 %.
_CHANNEL_PANEL_DV_LEFT = 1485

# Top gap kept by the configured offset above the DV channel panel; the
# nudge may go to the edge.
_MARGIN_TOP_DV = 37

_NUDGE_ACTIONS = {
    xbmcgui.ACTION_MOVE_LEFT:  (-_NUDGE_STEP, 0),
    xbmcgui.ACTION_MOVE_RIGHT: (_NUDGE_STEP, 0),
    xbmcgui.ACTION_MOVE_UP:    (0, -_NUDGE_STEP),
    xbmcgui.ACTION_MOVE_DOWN:  (0, _NUDGE_STEP),
}

# Next view for open_tinyppi(): OK on a DV source opens the metadata view,
# Back returns.  Back on the overlay ends the session.
_VIEW_DV_METADATA = "dv_metadata"

# Text properties of the two DV panels that get the change highlight.  The
# RPU / BL / EL icons and the FEL/MEL tag show changes on their own.  The
# HDR10 rows sit in the DV panel, so they are included.
_DV_VALUE_PROPERTIES = (
    "DoviCmVersionVar",
    "DoviStructureVar",
    "DoviVersionVar",
    "DoviProfileNumberVar",
    "DoviLevel1FllVar",
    "DoviLevel1PqVar",
    "DoviLevel5OffsetsVar",
    "DoviRpuMdlVar",
    "DoviLevel6RpuMaxCllFallVar",
    "Hdr10MdlVar",
    "Hdr10MaxCllFallVar",
)

_DV_CHANGED_COLOR    = "TinyPPI.OutputChangedColor"
_DV_CHANGED_FALLBACK = "FF82B1FF"  # Blue, the setting's default

# Setting for how long a changed reading stays highlighted (ms); polling
# stays at 100 ms.
_DV_CHANGED_HOLD = "output_changed_duration"

# Interval of properties.update_static_properties: per-title facts and CPU
# stats need not follow the 100 ms scene cadence.
_STATIC_POLL_INTERVAL = 1.0


def _settings() -> xbmcaddon.Addon:
    """Return a handle with the settings currently in force.

    The overlay runs inside the long-lived service, so a handle kept in a
    global would freeze the settings at Kodi start; ``core.settings`` renews
    it on every change.
    """
    return settings.addon()


def _is_coreelec() -> bool:
    """Return whether this is a CoreELEC installation."""
    if os.path.isdir("/etc/coreelec"):
        return True
    try:
        with open("/etc/os-release") as f:
            return any("coreelec" in line.lower() for line in f)
    except OSError:
        return False


def _notify_error(message_id: int) -> None:
    """Show an error notification with localized string *message_id*."""
    xbmcgui.Dialog().notification(
        "TinyPPI",
        localized(message_id),
        xbmcgui.NOTIFICATION_ERROR,
        4000,
    )


def _set_overlay_state(home, dialog_mode: bool = False) -> None:
    """Publish the Home-window properties that mark TinyPPI as open."""
    set_window_properties(
        home,
        (
            (PROP_RUNNING, "true"),
            (PROP_ACTIVE, "true"),
        ),
    )

    if dialog_mode:
        home.setProperty(PROP_DIALOG_MODE, "true")
    else:
        home.clearProperty(PROP_DIALOG_MODE)


def _preflight(home, player, toggle_log: str) -> bool:
    """Run the platform and playback checks shared by both entry points.

    Returns True when a view may open; otherwise notifies (or toggles the
    open view closed) and returns False.
    """
    if not _ALLOW_NON_COREELEC:
        if not _is_coreelec():
            _notify_error(32215)
            return False

        build_version = xbmc.getInfoLabel("System.BuildVersion")
        try:
            major_version = int(build_version.split(".")[0])
        except (ValueError, IndexError):
            _notify_error(32216)
            return False

        if major_version < 22:
            _notify_error(32215)
            return False

    skin_path = xbmcvfs.translatePath("special://skin/")
    if os.path.exists(os.path.join(skin_path, "720p")):
        _notify_error(32217)
        log("720p skin detected – unsupported", xbmc.LOGWARNING)
        return False

    if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
        return False

    if not player.isPlaying():
        return False

    if home.getProperty(PROP_RUNNING) == "true":
        log(toggle_log, xbmc.LOGINFO)
        xbmc.executebuiltin("Action(Back)")
        return False

    return not _releasing.is_set()


def _dv_metadata_enabled() -> bool:
    """Return whether OK may open the Dolby Vision metadata view.

    On by default (DV metadata settings); read per press, so a change
    applies immediately.
    """
    return _settings().getSettingBool("dv_metadata_view")


def _nudge_enabled() -> bool:
    """Return whether the arrow keys may move the overlay.

    Off by default (General -> Position), so stray presses cannot move it.
    Read once when the overlay opens, not per key press.
    """
    return _settings().getSettingBool("nudge_position")


def _elements_visible(addon) -> str:
    """Return "0" when the background is fully transparent, else "1".

    Controls the header title, header icon and separator lines.
    """
    return "0" if addon.getSettingInt("background_opacity") == 0 else "1"


def _release_overlay(home) -> None:
    """Clear the overlay state, then hold the re-entry lock briefly."""
    _releasing.set()
    clear_overlay_state(home)
    try:
        xbmc.Monitor().waitForAbort(0.2)
    finally:
        _releasing.clear()


# --- Overlay dialog --------------------------------------------------------

class TinyPPIDialog(xbmcgui.WindowXMLDialog):
    """Live player info over fullscreen video.

    Closes when playback stops or fullscreen video is left.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._running   = False
        self._monitor   = xbmc.Monitor()
        self._opened_at = 0.0
        self._offset    = None
        self._auto_hide = 0
        self._nudge     = (0, 0)
        self._nudge_on  = False
        # Position sliders, read in onInit.
        self._offset_pct    = (0, 0)
        self._dv_offset_pct = 100
        self._thread    = None
        self._dv_channel_offset = None
        self._refresh_failed    = False
        # Highlight state for the DV readings, built in onInit.  _shown is
        # what the window holds (with markup), unlike self.published (see
        # _highlight_dv_changes).
        self._highlighter       = None
        self._shown: dict       = {}
        # Public: _show_overlay() fills it before doModal().
        self.published: dict    = {}
        self._color_missing     = False
        # Highlight color, refreshed on the slow cadence (see _update_loop).
        self._changed_color     = ""
        # Read by open_tinyppi() after doModal() (see _open_dv_metadata).
        self.next_view  = None

    def onInit(self) -> None:
        self._running   = True
        self._opened_at = time.time()
        addon = _settings()
        # Auto-hide in seconds (0 = off); overlay only, not the VS10 dialog.
        self._auto_hide = addon.getSettingInt("auto_hide")
        self._nudge_on  = _nudge_enabled()
        # Read once: offsets are re-applied every tick because the layout
        # changes, not the sliders.
        self._offset_pct    = (
            addon.getSettingInt("offset_x"),
            addon.getSettingInt("offset_y"),
        )
        self._dv_offset_pct = addon.getSettingInt("offset_x_dv")

        # The values were published before doModal(); onInit runs with the
        # window already visible, so it only places the overlay and starts
        # the loop (which also sets the progress control).
        self._apply_position_offset()
        self._remember_dv_values()
        self._start_update_loop()

    def _remember_dv_values(self) -> None:
        """Record the opening DV readings as history, without highlighting."""
        self._highlighter = ChangeHighlighter(highlight_hold(_DV_CHANGED_HOLD))
        self._changed_color = self._dv_changed_color()
        self._shown = {
            name: self.getProperty(name) for name in _DV_VALUE_PROPERTIES
        }
        for name, value in self._shown.items():
            self._highlighter.mark(name, value, "")

    def _dv_changed_color(self) -> str:
        """Return the themed highlight color, or the default blue."""
        color = home_window().getProperty(_DV_CHANGED_COLOR)
        if color:
            return color
        if not self._color_missing:
            self._color_missing = True
            log(
                f"{_DV_CHANGED_COLOR} is not published, highlighting "
                f"changed overlay values in {_DV_CHANGED_FALLBACK} instead",
                xbmc.LOGWARNING,
            )
        return _DV_CHANGED_FALLBACK

    def _highlight_dv_changes(self) -> None:
        """Highlight DV readings that changed, for the highlight duration.

        Plain values come from ``self.published`` (never colored, as the
        publish passes compare against them).  The colored text goes to the
        window and into ``self._shown``, so a highlight costs one
        ``setProperty`` when it starts and one when it ends.

        Outside Dolby Vision the history is kept without highlighting.
        """
        current = {
            name: self.published.get(name, "") for name in _DV_VALUE_PROPERTIES
        }
        hdr_type = self.published.get("TinyPPI.HdrType", "").lower()
        color = self._changed_color if "dolby" in hdr_type else ""
        now   = time.monotonic()
        for name, value in current.items():
            highlighted = self._highlighter.mark(name, value, color, now)
            if self._shown.get(name) != highlighted:
                self.setProperty(name, highlighted)
                self._shown[name] = highlighted

    def _base_offset(self, wide: bool, up_limit: int) -> tuple:
        """Return the configured (x, y) offset.

        100 % is the maximum travel (30.9 % / 28.1 % of the screen).  The
        wide layouts (*wide*) stay left-aligned; vertical travel stops
        *up_limit* pixels up.
        """
        max_x = 0.309
        max_y = 0.281
        pct_x, pct_y = self._offset_pct
        offset_x = round(1920 * max_x * pct_x / 100)
        offset_y = -round(1080 * max_y * pct_y / 100)
        if wide:
            offset_x = 0
        offset_y = max(offset_y, -up_limit)
        return offset_x, offset_y

    @staticmethod
    def _is_dv_source() -> bool:
        """Return whether the source is Dolby Vision.

        The source type, not the effective one: the side data still describes
        the DV stream while VS10 converts it.
        """
        return "dolby" in home_window().getProperty("TinyPPI.HdrType").lower()

    def _layout(self) -> tuple[bool, bool, bool]:
        """Return ``(hdr, dv, channels)`` for the current layout.

        Uses the effective type (VS10 to SDR uses the SDR layout); *channels*
        mirrors the skin's condition.  Read once per placement, since each
        read takes Kodi's GUI lock.
        """
        channels = (
            home_window().getProperty("TinyPPI.ShowChannelIcon") == "1"
            and bool(self.getProperty("ChannelIconVar"))
        )
        return bool(effective_hdr_type()), is_effective_dv(), channels

    def _apply_position_offset(self) -> None:
        """Move group 5000 to the configured offset plus the nudge.

        The nudge itself is clamped, so a layout change pulls a nudged
        overlay back on screen and the next opposite press acts at once.
        Re-applied every tick (the HDR type is detected asynchronously) and
        skipped when unchanged.  In DV with channels the channel panel sits
        above the main box; the nudge may reach the edge, the configured
        offset keeps a margin.
        """
        hdr, dv, channels = self._layout()
        wide = hdr or channels
        top = _CONTENT_TOP_DV if dv and channels else _CONTENT_TOP
        up_limit = top - _MARGIN_TOP_DV if dv and channels else top

        base_x, base_y = self._base_offset(wide, up_limit)
        nudge_x, nudge_y = self._nudge
        right = _CONTENT_RIGHT_WIDE if wide else _CONTENT_RIGHT_NARROW

        nudge_x = min(max(nudge_x, -_CONTENT_LEFT - base_x), 1920 - right - base_x)
        nudge_y = min(max(nudge_y, -top - base_y), 1080 - _CONTENT_BOTTOM - base_y)
        self._nudge = (nudge_x, nudge_y)

        offset = (base_x + nudge_x, base_y + nudge_y)
        if offset != self._offset:
            self._offset = offset
            self.getControl(5000).setPosition(*offset)

        self._apply_dv_channel_offset()

    def _apply_dv_channel_offset(self) -> None:
        """Slide the DV channel panel (5100) horizontally on its own.

        100 % keeps it at the right as in the skin, 0 % at the left inset.
        """
        travel = _CHANNEL_PANEL_DV_LEFT - _CONTENT_LEFT
        pct    = min(max(self._dv_offset_pct, 0), 100)
        offset = (-round(travel * (100 - pct) / 100), 0)
        if offset == self._dv_channel_offset:
            return
        self._dv_channel_offset = offset
        self.getControl(5100).setPosition(*offset)

    def _move(self, dx: int, dy: int) -> None:
        """Nudge the overlay by (*dx*, *dy*); not saved."""
        nudge_x, nudge_y = self._nudge
        self._nudge = (nudge_x + dx, nudge_y + dy)
        self._apply_position_offset()

    def onClick(self, control_id: int) -> None:
        self.close_dialog()

    def onAction(self, action: xbmcgui.Action) -> None:
        if time.time() - self._opened_at < 0.3:
            return
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close_dialog()
            return
        if action_id == xbmcgui.ACTION_SELECT_ITEM:
            self._open_dv_metadata()
            return
        if not self._nudge_on:
            return
        step = _NUDGE_ACTIONS.get(action_id)
        if step:
            self._move(*step)

    def _open_dv_metadata(self) -> None:
        """Hand over to the Dolby Vision metadata view.

        Only for a DV source with the setting on.  open_tinyppi() opens the
        view after this window has closed: a modal opened from a callback
        would nest in its dispatch loop, and actions sent while a modal is
        closing are dropped.
        """
        if not _dv_metadata_enabled() or not self._is_dv_source():
            return
        self.next_view = _VIEW_DV_METADATA
        self.close_dialog()

    def _start_update_loop(self) -> None:
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()

    def join_update_loop(self) -> None:
        """Wait for the update loop to stop before handing over."""
        join_refresh_thread(self._thread)

    def _update_loop(self) -> None:
        """Refresh the overlay every 100 ms until it should close.

        The scene readings refresh every tick, the per-title ones every
        ``_STATIC_POLL_INTERVAL``; ``self.published`` makes idle ticks free
        of ``setProperty`` calls.  A failed refresh costs one stale tick, not
        the loop, and ``close_dialog`` runs in ``finally`` so the overlay is
        never left frozen.
        """
        player = xbmc.Player()
        next_static_publish = 0.0

        try:
            while self._running and not self._monitor.abortRequested():
                if not player.isPlaying():
                    break
                if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
                    break
                if self._auto_hide and time.time() - self._opened_at >= self._auto_hide:
                    break

                try:
                    # One read pass for the whole tick (see read_pass).
                    with read_pass():
                        properties.publish_scene_properties(self, self.published)
                        self._highlight_dv_changes()
                        self._apply_position_offset()

                        now = time.time()
                        if now >= next_static_publish:
                            # Advance first, so a failure retries after an
                            # interval rather than every tick.
                            next_static_publish = now + _STATIC_POLL_INTERVAL
                            properties.update_static_properties(
                                self, self.published)
                            self._changed_color = self._dv_changed_color()
                except Exception as exc:
                    self._log_refresh_failure(exc)

                if self._monitor.waitForAbort(0.1):
                    break
        finally:
            self.close_dialog()

    def _log_refresh_failure(self, exc: Exception) -> None:
        """Log a failed refresh once per overlay."""
        if self._refresh_failed:
            return
        self._refresh_failed = True
        log_refresh_failure("overlay", exc)

    def close_dialog(self) -> None:
        self._running = False
        home_window().clearProperty(PROP_ACTIVE)
        try:
            self.close()
        except Exception:
            pass


# --- Entry points ----------------------------------------------------------

def _show_overlay(home) -> str | None:
    """Show the overlay once and return the next view, or None to end."""
    # Marks the overlay as visible for the codec-logo splash.  Set per
    # showing: the overlay clears it on close, including when handing over to
    # the metadata view, which has no splash.
    home.setProperty(PROP_ACTIVE, "true")

    dialog = TinyPPIDialog(
        "script-tinyppi-main.xml",
        _ADDON_PATH,
        "Default",
        "1080i",
    )
    # Fill the window before Kodi draws it (onInit runs only once it is
    # visible).  Properties only: the controls do not exist yet.
    properties.publish_properties(dialog, dialog.published)
    dialog.doModal()
    dialog.join_update_loop()
    next_view = dialog.next_view
    del dialog
    return next_view


def open_tinyppi() -> None:
    """Check the environment and show TinyPPI until the viewer closes it.

    Starts with the overlay; on a DV source OK switches to the metadata view
    and Back returns.  Does nothing on non-CoreELEC (unless
    ``_ALLOW_NON_COREELEC``), Kodi < 22, a 720p skin, without fullscreen
    video or playback; toggles closed when already open.
    """
    home   = home_window()
    player = xbmc.Player()

    if not _opening.acquire(blocking=False):
        log("open request dropped: TinyPPI is already opening")
        return
    try:
        if not _preflight(home, player, "Toggle close"):
            return

        # Normally one property read: the service registered the fonts.
        ensure_fonts()

        addon            = _settings()
        elements_visible = _elements_visible(addon)
        _set_overlay_state(home)
    finally:
        _opening.release()

    try:
        set_window_properties(
            home,
            (
                ("TinyPPI.Filename", addon.getSetting("filename")),
                (
                    "TinyPPI.ShowL5Icon",
                    "0" if addon.getSetting("show_l5_icon") == "false" else "1",
                ),
                ("TinyPPI.ShowLine", elements_visible),
                ("TinyPPI.ShowHeaderTitle", elements_visible),
                ("TinyPPI.ShowHeaderIcon", elements_visible),
            ),
        )
        # From the HDR type known so far; the update loop refreshes it.
        properties.publish_channel_visibility(home)
        apply_theme(home, addon)

        while _show_overlay(home) == _VIEW_DV_METADATA:
            # Imported on first use only.
            from ui.dvmetadata import open_dv_metadata
            if not open_dv_metadata():
                break
    finally:
        _release_overlay(home)


def open_dialog_mode() -> None:
    """Open the VS10-mode selection dialog."""
    home   = home_window()
    player = xbmc.Player()

    # See _opening.
    if not _opening.acquire(blocking=False):
        log("open request dropped: TinyPPI is already opening")
        return
    try:
        if not _preflight(home, player, "Toggle close (dialog mode)"):
            return

        ensure_fonts()

        addon            = _settings()
        elements_visible = _elements_visible(addon)
        _set_overlay_state(home, dialog_mode=True)
    finally:
        _opening.release()

    try:
        set_window_properties(
            home,
            (
                ("TinyPPI.ShowLine", elements_visible),
                ("TinyPPI.ShowHeaderTitle", elements_visible),
                ("TinyPPI.ShowHeaderIcon", elements_visible),
            ),
        )
        apply_theme(home, addon)

        from ui.mode_select import open_dialog
        open_dialog()
    finally:
        _release_overlay(home)
