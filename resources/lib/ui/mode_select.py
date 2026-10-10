# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The VS10 mode-selection dialog.

Open via ``RunScript(script.tinyppi,dialog)`` or ``open_dialog()``; the
chosen mode is applied by ``core.vs10.set_mode``.
"""

import threading
from typing import Any

import xbmc
import xbmcgui
from core import settings
from core.log import log
from core.utils import (
    PROP_HDR10PLUS_PRESENT,
    clear_overlay_state,
    home_window,
)
from core.vs10 import delay, set_mode
from ui import dialog_layout

# The add-on folder (via the shared settings handle, see core.settings).
_ADDON_PATH = settings.addon().getAddonInfo("path")

# Dialog button id -> mode, from the same description the window files are
# generated from (ui.dialog_layout).
_ACTIONS = {
    control_id: action
    for branch in dialog_layout.BRANCHES
    for control_id, _label, action in branch["buttons"]
    if action is not None
}


class SettingsDialog(xbmcgui.WindowXMLDialog):
    """Menu dialog to pick a VS10 output mode or launch the TinyPPI overlay."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The layout this window was built from (geometry, key handling).
        self._layout = dialog_layout.dialog_mode()
        # Current choice of the single-button layout.
        self._step = 0
        self._branch_key: str | None = None
        self._running = False
        self._pending_mode: int | str | None = None
        self._monitor: xbmc.Monitor | None = None

    def onInit(self) -> None:
        # Refresh TinyPPI.HdrType before placing the panel: the branch
        # decides which button gets focus.
        self._running = True
        self._pending_mode = None
        self._monitor = xbmc.Monitor()
        self._publish_hdr_type(logged=False)
        self._place()
        threading.Thread(target=self._hdr_type_loop, daemon=True).start()

    # --- Layout ------------------------------------------------------------

    def _place(self) -> None:
        """Move the panel to the configured position, then reveal it.

        The window files keep the panel hidden until then, so it never jumps.
        """
        left, top = dialog_layout.panel_position(self._layout)
        try:
            self.getControl(dialog_layout.GROUP_PANEL).setPosition(left, top)
        except Exception as e:
            log(f"could not place the dialog panel: {e}", xbmc.LOGWARNING)
        home_window().setProperty(dialog_layout.PROP_PLACED, "1")
        # Default focus went nowhere while hidden; focus the visible branch.
        self._sync_branch(force=True)

    def _branch(self) -> dict:
        home = home_window()
        return dialog_layout.branch_for(
            home.getProperty("TinyPPI.HdrType"),
            home.getProperty(PROP_HDR10PLUS_PRESENT),
        )

    def _sync_branch(self, force: bool = False) -> None:
        """Follow branch changes: focus the first button, update the step.

        The branch can change while the dialog is open (detection finishing,
        output switched).
        """
        branch = self._branch()
        if not force and branch["key"] == self._branch_key:
            return
        self._branch_key = branch["key"]
        if self._layout == dialog_layout.MODE_SINGLE:
            self._show_step()
            focus = dialog_layout.SINGLE_BUTTON
        else:
            focus = branch["buttons"][0][0]
        try:
            self.setFocusId(focus)
        except Exception as e:
            log(f"could not focus dialog button {focus}: {e}", xbmc.LOGDEBUG)

    def _set_label(self, control_id: int, text: str) -> None:
        try:
            self.getControl(control_id).setLabel(text)
        except Exception as e:
            if self._running:
                log(f"could not set label {control_id}: {e}", xbmc.LOGWARNING)

    def _show_step(self) -> None:
        """Show the current choice on the single button (the step wraps)."""
        buttons = self._branch()["buttons"]
        self._step %= len(buttons)
        _control_id, markup, _action = buttons[self._step]
        self._set_label(dialog_layout.SINGLE_BUTTON,
                        dialog_layout.plain_label(markup))

    # --- Lifecycle ---------------------------------------------------------

    def _publish_hdr_type(self, logged: bool = True) -> bool:
        """Republish the HDR type; False when the read failed.

        *logged* suppresses repeated failure logs.
        """
        from info.publish import publish_hdr_type

        try:
            publish_hdr_type(home_window())
            return True
        except Exception as e:
            if not logged:
                log(f"HDR type refresh failed: {e}", xbmc.LOGWARNING)
            return False

    def _hdr_type_loop(self) -> None:
        """Republish the HDR type until the dialog closes (failures cost a cycle)."""
        logged = False
        monitor = self._monitor
        if monitor is None:  # before onInit
            return
        while self._running and not monitor.abortRequested():
            if self._publish_hdr_type(logged):
                if self._running:
                    self._sync_branch()
            else:
                logged = True
            if monitor.waitForAbort(0.5):
                break

    def close(self) -> None:
        self._running = False
        super().close()

    def onClick(self, control_id: int) -> None:
        if control_id == dialog_layout.SINGLE_BUTTON:
            # The single button acts as its current choice.
            buttons = self._branch()["buttons"]
            control_id = buttons[self._step % len(buttons)][0]

        if control_id in dialog_layout.PPI_BUTTONS:
            self.close()
            clear_overlay_state(home_window())
            from ui.overlay import open_tinyppi
            open_tinyppi()
            return

        mode = _ACTIONS.get(control_id)
        if mode:
            # Applied by open_dialog() after doModal(): Kodi drops actions
            # while a modal dialog's closing animation runs.
            self._pending_mode = mode
            self.close()

    def onAction(self, action: xbmcgui.Action) -> None:
        if action.getId() in (
            xbmcgui.ACTION_PREVIOUS_MENU,
            xbmcgui.ACTION_NAV_BACK,
            xbmcgui.ACTION_STOP,
        ):
            self.close()
            return
        if self._layout != dialog_layout.MODE_SINGLE:
            return
        # Left and right step through the choices (the button navigates to
        # itself, so the actions arrive here).
        if action.getId() == dialog_layout.ACTION_MOVE_LEFT:
            self._step -= 1
            self._show_step()
        elif action.getId() == dialog_layout.ACTION_MOVE_RIGHT:
            self._step += 1
            self._show_step()


def open_dialog() -> None:
    """Show the mode-selection dialog and apply the chosen mode."""
    home = home_window()
    # Hidden until the dialog has placed its panel.
    home.clearProperty(dialog_layout.PROP_PLACED)
    win = SettingsDialog(
        dialog_layout.xml_file(),
        _ADDON_PATH,
        "Default",
        "1080i",
    )
    win.doModal()
    mode = getattr(win, "_pending_mode", None)
    del win
    if mode:
        # The dialog is gone; let the video window settle, then apply.
        delay(250)
        set_mode(mode)
