"""Core logic for the TinyPPI overlay dialog and its entry points.

Imported by main.py, which sets up sys.path first.
"""

import os
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from core.utils import (
    PROP_ACTIVE,
    PROP_DIALOG_MODE,
    PROP_RUNNING,
    ChangeHighlighter,
    clear_overlay_state,
    effective_hdr_type,
    highlight_hold,
    is_effective_dv,
    join_refresh_thread,
    log_refresh_failure,
    set_window_properties,
)
from info import properties
from ui import fonts  # noqa: F401  imported for its install-fonts-on-import side effect
from ui.theme import apply_theme

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

_dialog_lock = False

# Raise to True to allow launching on non-CoreELEC platforms (e.g. for testing).
_ALLOW_NON_COREELEC = False

# Runtime nudge: pixels moved per arrow-key press, and the direction each key
# shifts the overlay by.  Off unless the viewer turns it on (see
# _nudge_enabled), and deliberately not persisted even then – the nudge lives
# on the dialog instance, so the next launch starts from the configured
# offsets again.
_NUDGE_STEP = 10

# Outermost edges of the overlay content inside group 5000 (see the skin XML);
# the nudge and the configured offsets are clamped so these stay on screen.
_CONTENT_LEFT         = 35
_CONTENT_BOTTOM       = 1045
_CONTENT_TOP          = 340
_CONTENT_TOP_DV       = 37    # DV with channels: separate panel above the main box
_CONTENT_RIGHT_NARROW = 1292  # SDR without channels
_CONTENT_RIGHT_WIDE   = 1885  # HDR, and SDR with channels

# Skin position of the DV channel panel (control 5100), which offset_x_dv slides
# left from: at 0 % its left edge lands on _CONTENT_LEFT.
_CHANNEL_PANEL_DV_LEFT = 1485

# Gap the configured vertical offset leaves above the DV channel panel, matching
# the left inset.  The arrow-key nudge ignores it and goes to the edge.
_MARGIN_TOP_DV = 37

_NUDGE_ACTIONS = {
    xbmcgui.ACTION_MOVE_LEFT:  (-_NUDGE_STEP, 0),
    xbmcgui.ACTION_MOVE_RIGHT: (_NUDGE_STEP, 0),
    xbmcgui.ACTION_MOVE_UP:    (0, -_NUDGE_STEP),
    xbmcgui.ACTION_MOVE_DOWN:  (0, _NUDGE_STEP),
}

# The view open_tinyppi() shows next once the current one closes.  On a Dolby
# Vision source OK goes down into it and Back comes back up out of it; Back
# here, on the overlay itself, is the end of the session.
_VIEW_DV_METADATA = "dv_metadata"

# Label properties carrying the readings in the overlay's two Dolby Vision
# panels.  The RPU / BL / EL fields are icons whose green/red state already
# makes a change visible, and the FEL/MEL tag has its own themed color; the
# remaining text would otherwise all use the normal output color.  HDR10 rows
# are included because they sit inside the DV metadata panel and are part of
# the side data shown for a DV source.
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
_DV_CHANGED_FALLBACK = "FF82B1FF"  # Light blue, the setting's default

# How long a changed reading stays in that color, in milliseconds (Output ->
# Changed values -> Highlight duration).  The loop below still polls at 100ms:
# what this setting holds is the highlight, not the reading behind it.
_DV_CHANGED_HOLD = "output_changed_duration"

# How often the tick loop refreshes properties.update_static_properties.
# Video/audio/subtitle facts and CPU stats settle at most once a title, so
# they do not need the loop's own 100ms cadence the way the Dolby Vision /
# HDR10 readings in publish_scene_properties do.
_STATIC_POLL_INTERVAL = 1.0


def _is_coreelec() -> bool:
    """Return True when running on a CoreELEC installation."""
    if os.path.isdir("/etc/coreelec"):
        return True
    try:
        with open("/etc/os-release") as f:
            return any("coreelec" in line.lower() for line in f)
    except OSError:
        return False


def _notify_error(message_id: int) -> None:
    """Show a Kodi error notification using a localised string ID."""
    xbmcgui.Dialog().notification(
        "TinyPPI",
        _ADDON.getLocalizedString(message_id),
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
    """Run the environment and playback guards shared by both entry points.

    Returns True when the overlay may open, else shows an error notification
    (or triggers the toggle-close) and returns False.
    """
    if not _ALLOW_NON_COREELEC:
        if not _is_coreelec():
            _notify_error(32016)
            return False

        build_version = xbmc.getInfoLabel("System.BuildVersion")
        try:
            major_version = int(build_version.split(".")[0])
        except (ValueError, IndexError):
            _notify_error(32017)
            return False

        if major_version < 22:
            _notify_error(32016)
            return False

    skin_path = xbmcvfs.translatePath("special://skin/")
    if os.path.exists(os.path.join(skin_path, "720p")):
        _notify_error(32012)
        xbmc.log("TinyPPI: 720p skin detected – unsupported", xbmc.LOGWARNING)
        return False

    if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
        return False

    if not player.isPlaying():
        return False

    if home.getProperty(PROP_RUNNING) == "true":
        xbmc.log(toggle_log, xbmc.LOGINFO)
        xbmc.executebuiltin("Action(Back)")
        return False

    return not _dialog_lock


def _dv_metadata_enabled() -> bool:
    """Return whether OK may open the Dolby Vision metadata view.

    Off out of the box: OK does nothing on the overlay until someone turns the
    view on under Metadata, so the key keeps behaving as it always has for anyone
    who has no use for the metadata.  A fresh ``Addon()`` avoids the cached
    settings, so the toggle applies to a session already under way.
    """
    return xbmcaddon.Addon().getSettingBool("dv_metadata_view")


def _nudge_enabled() -> bool:
    """Return whether the arrow keys may move the overlay around.

    Off out of the box, like the metadata view: the arrow keys do nothing on
    the overlay until someone turns the nudge on under General -> Position, so
    a stray press on the remote cannot walk the overlay off where it was put.
    Read once when the overlay opens rather than per key press, which is where
    a held-down arrow key would land it.
    """
    return xbmcaddon.Addon().getSettingBool("nudge_position")


def _elements_visible() -> str:
    """Return the "1"/"0" flag for the header title, header icon and separator
    lines: they follow the background and hide only when it is fully transparent."""
    return "0" if _ADDON.getSettingInt("background_opacity") == 0 else "1"


def _release_overlay(home) -> None:
    """Clear overlay state immediately, then briefly hold the re-entry lock."""
    global _dialog_lock
    _dialog_lock = True
    clear_overlay_state(home)
    try:
        xbmc.Monitor().waitForAbort(0.2)
    finally:
        _dialog_lock = False


# ---------------------------------------------------------------------------
# Overlay dialog
# ---------------------------------------------------------------------------

class TinyPPIDialog(xbmcgui.WindowXMLDialog):
    """Overlay showing live player info during fullscreen playback; auto-closes
    when playback stops or the user leaves the fullscreen video window."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._running   = False
        self._monitor   = xbmc.Monitor()
        self._opened_at = 0.0
        self._offset    = None
        self._auto_hide = 0
        self._nudge     = (0, 0)
        self._nudge_on  = False
        self._thread    = None
        self._dv_channel_offset = None
        self._refresh_failed    = False
        # What the DV readings said last, and how long each change of them
        # stays lit; built in onInit, where the setting behind the duration is
        # read.  self._shown is what the window itself currently holds for
        # those properties, which is not the same thing as self.published --
        # see _highlight_dv_changes.
        self._highlighter       = None
        self._shown: dict       = {}
        # Not underscore-prefixed: _show_overlay() seeds this from outside the
        # class, the same way next_view below is read from outside once doModal()
        # returns.
        self.published: dict    = {}
        self._color_missing     = False
        # Read by open_tinyppi() once doModal() returns; see _open_dv_metadata.
        self.next_view  = None

    def onInit(self) -> None:
        self._running   = True
        self._opened_at = time.time()
        # Auto-hide timeout in seconds (0 = off). Applies to the TinyPPI
        # overlay only, not the VS10 selection dialog.
        self._auto_hide = _ADDON.getSettingInt("auto_hide")
        self._nudge_on  = _nudge_enabled()

        # Everything the first frame needs was published before doModal(), so
        # there is nothing to fetch here: place the overlay against the HDR type
        # already known and hand over to the polling loop, whose first pass runs
        # immediately and covers the progress control a loaded window adds.
        # Kodi dispatches onInit to this thread with the window already on
        # screen, so work done here is work the viewer waits through.
        self._apply_position_offset()
        self._remember_dv_values()
        self._start_update_loop()

    def _remember_dv_values(self) -> None:
        """Take the DV readings the dialog opened with as the starting point.

        Marked without a color, which records them as history without lighting
        any of them: what is already on screen when the overlay opens has not
        changed under anybody's eyes.  The window holds exactly these values,
        so self._shown starts out saying so.
        """
        self._highlighter = ChangeHighlighter(highlight_hold(_DV_CHANGED_HOLD))
        self._shown = {
            name: self.getProperty(name) for name in _DV_VALUE_PROPERTIES
        }
        for name, value in self._shown.items():
            self._highlighter.mark(name, value, "")

    def _dv_changed_color(self) -> str:
        """Return the themed DV-change color, with its light-blue fallback."""
        color = xbmcgui.Window(10000).getProperty(_DV_CHANGED_COLOR)
        if color:
            return color
        if not self._color_missing:
            self._color_missing = True
            xbmc.log(
                f"TinyPPI: {_DV_CHANGED_COLOR} is not published, highlighting "
                f"changed overlay values in {_DV_CHANGED_FALLBACK} instead",
                xbmc.LOGWARNING,
            )
        return _DV_CHANGED_FALLBACK

    def _highlight_dv_changes(self) -> None:
        """Light the DV readings that moved, and keep them lit for as long as
        the highlight duration says.

        Reads current values from ``self.published`` rather than back from
        the window: whichever publish call last touched a given property (the
        fast scene pass or the slower static one) already recorded its plain
        current value there regardless of whether it needed a fresh
        ``setProperty`` call.  Nothing colored is ever written back into it,
        so what it holds stays the plain reading -- which is what the publish
        passes have to compare against, and what the highlighter has to be
        given each tick.  The colored text goes to the window and is recorded
        in ``self._shown`` instead, so a highlight held over several ticks
        costs one ``setProperty`` on the tick it starts and one on the tick it
        ends: the plain value is not rewritten underneath it in between, which
        at ten ticks a second would be ten chances for a frame to catch the
        reading mid-swap.

        An empty color where the source is not Dolby Vision keeps the
        readings' history without lighting any of them, so a stream that comes
        back to DV is compared against what it last said rather than against
        nothing.
        """
        current = {
            name: self.published.get(name, "") for name in _DV_VALUE_PROPERTIES
        }
        hdr_type = self.published.get("TinyPPI.HdrType", "").lower()
        color = self._dv_changed_color() if "dolby" in hdr_type else ""
        now   = time.monotonic()
        for name, value in current.items():
            highlighted = self._highlighter.mark(name, value, color, now)
            if self._shown.get(name) != highlighted:
                self.setProperty(name, highlighted)
                self._shown[name] = highlighted

    def _base_offset(self) -> tuple:
        """Return the (x, y) offset configured in the settings.

        100 % is the max on-screen travel (30.9 % / 28.1 % of the screen);
        horizontal only applies to SDR without channels (HDR and SDR with
        channels stay left-aligned), and vertical stops short of the top edge
        in DV with channels.
        """
        max_x = 0.309
        max_y = 0.281
        offset_x = round(1920 * max_x * _ADDON.getSettingInt("offset_x") / 100)
        offset_y = -round(1080 * max_y * _ADDON.getSettingInt("offset_y") / 100)
        if self._is_hdr() or self._has_channels():
            offset_x = 0
        offset_y = max(offset_y, -self._offset_up_limit())
        return offset_x, offset_y

    # Both read the effective type, not the source: a stream VS10 converts to
    # SDR is drawn in the SDR layout, so the box these clamp against is the
    # narrow one.
    @staticmethod
    def _is_hdr() -> bool:
        return bool(effective_hdr_type())

    @staticmethod
    def _is_dv() -> bool:
        return is_effective_dv()

    @staticmethod
    def _is_dv_source() -> bool:
        """Whether the stream itself is Dolby Vision, which is what decides
        there is anything for the metadata view to show.

        The source type, not the effective one the layout follows: VS10 may be
        converting the picture to SDR or HDR10, but the side data still
        describes the Dolby Vision stream being decoded.
        """
        return "dolby" in xbmcgui.Window(10000).getProperty("TinyPPI.HdrType").lower()

    def _has_channels(self) -> bool:
        """Mirror the skin's visibility condition for the channel variant."""
        return (
            xbmcgui.Window(10000).getProperty("TinyPPI.ShowChannelIcon") == "1"
            and bool(self.getProperty("ChannelIconVar"))
        )

    def _content_top(self) -> int:
        """Top edge of the content: DV puts the channel panel above the main box."""
        return _CONTENT_TOP_DV if self._is_dv() and self._has_channels() else _CONTENT_TOP

    def _offset_up_limit(self) -> int:
        """Pixels the configured offset may move the content up.

        The nudge is free to go all the way to the screen edge; the offset keeps
        the DV channel panel 35 px clear of it, which leaves it 2 px there.
        """
        top = self._content_top()
        if self._is_dv() and self._has_channels():
            return top - _MARGIN_TOP_DV
        return top

    def _apply_position_offset(self) -> None:
        """Move group 5000 to the configured offset plus the current nudge.

        The nudge is clamped here (not at the resulting position) so a later
        HDR switch or channel icon appearing pulls an already-nudged overlay
        back on screen, while keeping the first press in the opposite
        direction effective.  Re-applied each cycle since HDR type is detected
        asynchronously; cached so the unchanged case is skipped.
        """
        base_x, base_y = self._base_offset()
        nudge_x, nudge_y = self._nudge
        wide = self._is_hdr() or self._has_channels()
        right = _CONTENT_RIGHT_WIDE if wide else _CONTENT_RIGHT_NARROW

        top = self._content_top()

        nudge_x = min(max(nudge_x, -_CONTENT_LEFT - base_x), 1920 - right - base_x)
        nudge_y = min(max(nudge_y, -top - base_y), 1080 - _CONTENT_BOTTOM - base_y)
        self._nudge = (nudge_x, nudge_y)

        offset = (base_x + nudge_x, base_y + nudge_y)
        if offset != self._offset:
            self._offset = offset
            self.getControl(5000).setPosition(*offset)

        self._apply_dv_channel_offset()

    def _apply_dv_channel_offset(self) -> None:
        """Slide the DV channel panel (5100) along its own row.

        The panel sits above the main box, so it can move horizontally on its
        own: 100 % leaves it skin-aligned on the right, 0 % puts it at the left
        inset.  Only the panel moves; the main box below it stays put.
        """
        travel = _CHANNEL_PANEL_DV_LEFT - _CONTENT_LEFT
        pct    = min(max(_ADDON.getSettingInt("offset_x_dv"), 0), 100)
        offset = (-round(travel * (100 - pct) / 100), 0)
        if offset == self._dv_channel_offset:
            return
        self._dv_channel_offset = offset
        self.getControl(5100).setPosition(*offset)

    def _move(self, dx: int, dy: int) -> None:
        """Shift the overlay by one step; reverts on the next launch."""
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

        Only when the metadata setting is on, and only for a Dolby Vision source
        -- on anything else there is no side data to show, and OK keeps doing
        what it did before either way, which is nothing.

        The view is not opened from here: open_tinyppi() opens it once this
        window is gone.  A modal opened from inside a callback would nest
        inside the loop that dispatched the callback, and the same deferral is
        what the VS10 dialog does with a picked mode, for the same reason --
        an action fired while a modal is still closing is dropped.
        """
        if not _dv_metadata_enabled() or not self._is_dv_source():
            return
        self.next_view = _VIEW_DV_METADATA
        self.close_dialog()

    def _start_update_loop(self) -> None:
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()

    def join_update_loop(self) -> None:
        """Wait for the update loop to actually stop before handing over."""
        join_refresh_thread(self._thread)

    def _update_loop(self) -> None:
        """Refresh the overlay every 100ms until it should close.

        Only ``publish_scene_properties`` runs on every tick: it is the
        Dolby Vision / HDR10 readings there that can move every scene.
        Everything else settles at most once a title, so
        ``update_static_properties`` runs on its own, slower
        ``_STATIC_POLL_INTERVAL`` timer instead of every tick.

        ``self.published`` makes both cadences cheap: whichever pass ran,
        an idle tick costs no ``setProperty`` calls, only the recompute.

        A failed refresh never ends the loop: the values come from the player
        and from the stream's side data, so a bad cycle is worth one stale
        tick, not a window that stops auto-closing.  ``close_dialog`` runs
        from ``finally`` so even an unforeseen failure still releases the
        overlay instead of leaving it up, frozen and marked active.
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
                    properties.publish_scene_properties(self, self.published)
                    self._highlight_dv_changes()
                    self._apply_position_offset()

                    now = time.time()
                    if now >= next_static_publish:
                        # Advance the deadline before the call, not after: a
                        # failure below still counts this as tried, so it
                        # retries in another _STATIC_POLL_INTERVAL rather than
                        # every tick until it happens to succeed.
                        next_static_publish = now + _STATIC_POLL_INTERVAL
                        properties.update_static_properties(self, self.published)
                except Exception as exc:
                    self._log_refresh_failure(exc)

                if self._monitor.waitForAbort(0.1):
                    break
        finally:
            self.close_dialog()

    def _log_refresh_failure(self, exc: Exception) -> None:
        """Log a failed refresh once per overlay, so a persistent fault leaves
        a trace without writing to the log every second."""
        if self._refresh_failed:
            return
        self._refresh_failed = True
        log_refresh_failure("overlay", exc)

    def close_dialog(self) -> None:
        self._running = False
        xbmcgui.Window(10000).clearProperty(PROP_ACTIVE)
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def _show_overlay(home) -> str | None:
    """Show the overlay window once, and return the view it handed over to.

    None when the overlay was simply closed, which ends the session.
    """
    # Marks the overlay itself as on screen, which the codec-logo splash
    # follows.  Set per showing, not once per session: the overlay clears it as
    # it closes, including when it closes to hand over to the metadata view, and
    # the splash belongs with the overlay rather than with that view.
    home.setProperty(PROP_ACTIVE, "true")

    dialog = TinyPPIDialog(
        "script-tinyppi-main.xml",
        _ADDON_PATH,
        "Default",
        "1080i",
    )
    # Fill the window before Kodi draws it.  onInit() is dispatched to the
    # script thread only once the window is up and fading in, so anything
    # published there arrives after the viewer is already looking at the
    # rows; done here, the first frame carries the values.  Properties only
    # -- the controls the full refresh touches do not exist yet.
    properties.publish_properties(dialog, dialog.published)
    dialog.doModal()
    dialog.join_update_loop()
    next_view = dialog.next_view
    del dialog
    return next_view


def open_tinyppi() -> None:
    """Validate the environment and show TinyPPI until the viewer closes it.

    The overlay is the view it opens with; on a Dolby Vision source OK hands
    over to the metadata view and Back hands back, so this runs until one of
    them is closed for good rather than handing over to the other.

    Skips silently on non-CoreELEC (unless ``_ALLOW_NON_COREELEC``), Kodi < 22,
    a 720p skin, no fullscreen video, or nothing playing; toggle-closes when the
    overlay is already open.
    """
    home   = xbmcgui.Window(10000)
    player = xbmc.Player()

    if not _preflight(home, player, "TinyPPI: Toggle close"):
        return

    elements_visible = _elements_visible()
    _set_overlay_state(home)
    set_window_properties(
        home,
        (
            ("TinyPPI.Filename", _ADDON.getSetting("filename")),
            (
                "TinyPPI.ShowL5Icon",
                "0" if _ADDON.getSetting("show_l5_icon") == "false" else "1",
            ),
            ("TinyPPI.ShowLine", elements_visible),
            ("TinyPPI.ShowHeaderTitle", elements_visible),
            ("TinyPPI.ShowHeaderIcon", elements_visible),
        ),
    )
    # From the HDR type known so far, so the right variant is up before the first
    # frame; the update loop re-publishes it once detection finishes.
    properties.publish_channel_visibility(home)
    apply_theme(home, _ADDON)

    try:
        while _show_overlay(home) == _VIEW_DV_METADATA:
            # Loaded on the first hand-over, so a session that never opens the
            # metadata view never pays for it.
            from ui.dvmetadata import open_dv_metadata
            if not open_dv_metadata():
                break
    finally:
        _release_overlay(home)


def open_dialog_mode() -> None:
    """Open the VS10-mode selection dialog."""
    home   = xbmcgui.Window(10000)
    player = xbmc.Player()

    if not _preflight(home, player, "TinyPPI: Toggle close (dialog mode)"):
        return

    elements_visible = _elements_visible()
    _set_overlay_state(home, dialog_mode=True)
    set_window_properties(
        home,
        (
            ("TinyPPI.ShowLine", elements_visible),
            ("TinyPPI.ShowHeaderTitle", elements_visible),
            ("TinyPPI.ShowHeaderIcon", elements_visible),
        ),
    )
    apply_theme(home, _ADDON)

    try:
        from ui.mode_select import open_dialog
        open_dialog()
    finally:
        _release_overlay(home)
