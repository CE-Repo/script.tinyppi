# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The codec-logo splash: layout, settings, conditions, fades and controller
(ui/splash.py, ui/splash_panel.py, ui/splash_settings.py)."""

import os
from types import SimpleNamespace

import pytest

import xbmc
import xbmcaddon
import xbmcgui
from core.constants import HOME_WINDOW_ID as HOME
from ui import splash, splash_panel, splash_settings

FULLSCREEN = "Window.IsActive(fullscreenvideo)"
GAMUT = "Player.Process(amlogic.eoft_gamut)"
POLL, TICK, FADE_OUT = splash._POLL_INTERVAL, splash._RENDER_TICK, splash._FADE_OUT_SECONDS
CONVERTING = splash.PROP_CONVERTING
VISIBLE = {"start": "TinyPPI.SplashStartVisible", "osd": "TinyPPI.SplashOsdVisible",
           "tinyppi": "TinyPPI.SplashTinyPPIVisible"}

# One distinct tint per colour key, so a control's colour tells what it is.
COLOURS = {
    "bg": "FF000001", "video": "FF000002", "audio": "FF000003", "divider": "FF000004",
    "convert_dot": "FF000005", "fel": "FF000006", "mel": "FF000007", "other": "FF000008",
}
PAIR = [("codecs/HDR10.png", "video"), ("audio/dts.png", "audio")]


def is_true(prop):
    return f"String.IsEqual(Window(10000).Property({prop}),true)"


def media(rel_path):
    return os.path.join(splash_panel._MEDIA_PATH, *rel_path.split("/"))


def use(**values):
    for key, value in values.items():
        xbmcaddon.SETTINGS[key] = ("true" if value else "false") if isinstance(value, bool) else str(value)


def bounds(controls):
    """Return (left, top, right, bottom) around *controls*."""
    return (min(c.box[0] for c in controls), min(c.box[1] for c in controls),
            max(c.box[0] + c.box[2] for c in controls), max(c.box[1] + c.box[3] for c in controls))


class Image(xbmcgui.ControlImage):
    """A ControlImage that also keeps its visibility condition."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.condition = None

    def setVisibleCondition(self, condition, allow_hidden_focus=False):
        self._record("setVisibleCondition", condition, allow_hidden_focus)
        self.condition = condition

    @property
    def box(self):
        return self.args[:4]

    @property
    def texture(self):
        return self.args[4]

    @property
    def color(self):
        return self.kwargs["colorDiffuse"]


@pytest.fixture(autouse=True)
def images(monkeypatch):
    # The real display_texture would write scaled copies under special://.
    monkeypatch.setattr(xbmcgui, "ControlImage", Image)
    monkeypatch.setattr(splash_panel, "display_texture", lambda path, w, h: path)


# --- Which logos a mode shows --------------------------------------------------

@pytest.mark.parametrize(("show_video", "show_audio", "audio_first", "logos", "has_audio", "stack"), [
    (True, True, False, ("v.png", "a.png"), True, (("v.png", "video"), ("a.png", "audio"))),
    (True, True, True, ("v.png", "a.png"), True, (("a.png", "audio"), ("v.png", "video"))),
    (True, True, False, ("v.png", ""), True, ()),          # all or nothing
    (True, True, False, ("", "a.png"), True, ()),
    (True, True, False, ("v.png", ""), False, (("v.png", "video"),)),   # a video without audio
    (True, True, True, ("v.png", "a.png"), False, (("v.png", "video"),)),
    (True, False, False, ("v.png", "a.png"), True, (("v.png", "video"),)),
    (False, True, False, ("v.png", "a.png"), True, (("a.png", "audio"),)),
    (False, True, False, ("v.png", ""), True, ()),
    (False, False, False, ("v.png", "a.png"), True, ()),
])
def test_a_mode_stacks_the_logos_it_is_set_to_show(show_video, show_audio, audio_first, logos,
                                                   has_audio, stack):
    mode = splash_settings.ModeSettings(show_video, show_audio, audio_first, 0, 0, 1.0, False)
    assert splash._mode_logos(mode, logos, has_audio) == stack


# --- Building blocks -------------------------------------------------------------

def test_an_image_is_scaled_for_its_box_and_tinted(monkeypatch):
    asked = []
    monkeypatch.setattr(splash_panel, "display_texture",
                        lambda path, w, h: asked.append((path, w, h)) or "/cache/HDR10_30x40.png")
    image = splash_panel._make_image("codecs/HDR10.png", 1, 2, 30, 40, "FF123456")
    assert asked == [(media("codecs/HDR10.png"), 30, 40)]
    assert image.args == (1, 2, 30, 40, "/cache/HDR10_30x40.png")
    assert image.kwargs == {"aspectRatio": splash_panel._ASPECT_KEEP, "colorDiffuse": "FF123456"}


def test_a_dot_is_centred_on_its_point():
    dot = splash_panel._make_dot(100, 50, 10, "FF81C784")
    assert dot.box == (95, 45, 10, 10)
    assert dot.texture == media("common/dot-circle.png") and dot.color == "FF81C784"


def test_a_solid_rectangle_is_never_smaller_than_a_pixel():
    solid = splash_panel._solid(5, 6, 0, -3, "FF000000")
    assert solid.box == (5, 6, 1, 1)
    assert solid.texture == media("common/dot-1x1.png")
    assert solid.kwargs["aspectRatio"] == splash_panel._ASPECT_STRETCH


def test_the_panel_pieces_tile_a_rounded_rectangle():
    pieces = splash_panel._panel_controls(10, 20, 100, 40, 8, "FA15181A")
    assert len(pieces) == 9
    assert bounds(pieces) == (10, 20, 110, 60)
    assert sum(p.box[2] * p.box[3] for p in pieces) == 100 * 40
    corners = {p.texture: p.box[:2] for p in pieces[5:]}
    assert corners == {media("splash/corner-tl.png"): (10, 20), media("splash/corner-tr.png"): (102, 20),
                       media("splash/corner-bl.png"): (10, 52), media("splash/corner-br.png"): (102, 52)}
    assert {p.color for p in pieces} == {"FA15181A"}


@pytest.mark.parametrize(("radius", "corner"), [(8, 8), (50, 20), (0, 1)])
def test_the_corner_radius_fits_the_panel(radius, corner):
    pieces = splash_panel._panel_controls(0, 0, 100, 40, radius, "FF000000")
    assert {p.box[2:] for p in pieces[5:]} == {(corner, corner)}


# --- Layout ------------------------------------------------------------------------

def test_no_logos_build_nothing():
    assert splash_panel.build_controls([], COLOURS, 0, 0, 1920, 1080) == ([], None)


def test_two_logos_stack_on_a_panel_with_a_divider_and_a_badge():
    controls, dot = splash_panel.build_controls(PAIR, COLOURS, 0, 0, 1920, 1080)
    c = COLOURS
    assert [x.color for x in controls] == [c["bg"]] * 9 + [c["divider"], c["video"], c["audio"],
                                                           c["convert_dot"]]
    panel, divider, video, audio = controls[:9], controls[9], controls[10], controls[11]
    assert (video.texture, audio.texture) == (media("codecs/HDR10.png"), media("audio/dts.png"))
    assert video.box[1] + video.box[3] < divider.box[1] < audio.box[1]
    assert dot is controls[-1] and dot.texture == media("common/dot-circle.png")
    left, top, right, bottom = bounds(panel)
    assert (left, top) == (35, 35)              # the inset at offset 0 %
    assert bounds(controls) == (left, top, right, bottom)
    # The badge sits in the panel's top-right corner.
    assert dot.box[0] > (left + right) / 2 and dot.box[1] + dot.box[3] < (top + bottom) / 2


def test_a_single_logo_has_no_divider():
    controls, dot = splash_panel.build_controls([("codecs/SDR.png", "video")], COLOURS, 0, 0, 1920, 1080)
    assert [x.color for x in controls] == [COLOURS["bg"]] * 9 + [COLOURS["video"],
                                                                 COLOURS["convert_dot"]]
    assert dot is controls[-1]


@pytest.mark.parametrize(("token", "colour"), [
    ("fel", COLOURS["fel"]), ("mel", COLOURS["mel"]), ("other", COLOURS["other"]),
    ("", None), ("hdr10", None),
])
def test_the_layer_pill_is_tinted_by_its_layer(token, colour):
    controls, _dot = splash_panel.build_controls(PAIR, COLOURS, 0, 0, 1920, 1080, layer_token=token)
    pills = [x for x in controls if x.texture == media("common/pill.png")]
    assert [p.color for p in pills] == ([colour] if colour else [])


@pytest.mark.parametrize("at_top", [False, True])
def test_the_pill_sits_in_the_panel_padding_above_or_below_the_logos(at_top):
    controls, _dot = splash_panel.build_controls(PAIR, COLOURS, 0, 0, 1920, 1080,
                                            layer_token="fel", pill_at_top=at_top)
    _left, top, _right, bottom = bounds(controls[:9])
    video, audio, pill = controls[10], controls[11], controls[-1]
    pill_top, pill_bottom = pill.box[1], pill.box[1] + pill.box[3]
    if at_top:
        assert top < pill_top and pill_bottom <= video.box[1]
    else:
        assert audio.box[1] + audio.box[3] <= pill_top and pill_bottom < bottom


def test_offsets_move_the_panel_from_the_top_left_inset_to_the_bottom_right_edge():
    near, _dot = splash_panel.build_controls(PAIR, COLOURS, 0, 0, 1920, 1080)
    far, _dot = splash_panel.build_controls(PAIR, COLOURS, 100, 100, 1920, 1080)
    assert bounds(near[:9])[:2] == (35, 35)
    assert bounds(far[:9])[2:] == (1920 - 35, 1080 - 35)


@pytest.mark.parametrize(("offset", "clamped"), [(-20, 0), (150, 100)])
def test_offsets_are_clamped_to_the_screen(offset, clamped):
    beyond, _dot = splash_panel.build_controls(PAIR, COLOURS, offset, offset, 1920, 1080)
    edge, _dot = splash_panel.build_controls(PAIR, COLOURS, clamped, clamped, 1920, 1080)
    assert [x.box for x in beyond] == [x.box for x in edge]


def test_the_user_scale_resizes_the_panel():
    small, _dot = splash_panel.build_controls(PAIR, COLOURS, 0, 0, 1920, 1080, user_scale=0.8)
    large, _dot = splash_panel.build_controls(PAIR, COLOURS, 0, 0, 1920, 1080, user_scale=1.3)
    # Both start at the inset; the larger one reaches further.
    assert bounds(large[:9])[:2] == bounds(small[:9])[:2] == (35, 35)
    (_l, _t, large_right, large_bottom), (_l, _t, small_right, small_bottom) = (
        bounds(large[:9]), bounds(small[:9]))
    assert large_right > small_right and large_bottom > small_bottom
    assert large[10].box[2] > small[10].box[2] and large[10].box[3] > small[10].box[3]


class Sized:
    def __init__(self, size):
        self.size = size

    def getWidth(self):
        if self.size is None:
            raise RuntimeError("window not created")
        return self.size[0]

    def getHeight(self):
        return self.size[1]


@pytest.mark.parametrize(("size", "dims"), [
    ((1280, 720), (1280, 720)),
    ((3840, 2160), (3840, 2160)),
    ((0, 0), (2560, 1440)),          # no size yet: the screen's
    ((800, 400), (2560, 1440)),      # too small to be the real space
    (None, (2560, 1440)),            # the window cannot tell
])
def test_controls_are_laid_out_in_the_windows_own_space(monkeypatch, size, dims):
    monkeypatch.setattr(xbmcgui, "getScreenWidth", lambda: 2560)
    monkeypatch.setattr(xbmcgui, "getScreenHeight", lambda: 1440)
    assert splash_panel.window_dims(Sized(size)) == dims


# --- Settings and colours ---------------------------------------------------------

def test_the_settings_are_read_per_mode():
    use(splash_enabled=True, splash_show_on_osd=False, splash_show_on_tinyppi=True,
        splash_duration=5, splash_osd_show_video=False, splash_osd_order=1,
        splash_osd_offset_x=10, splash_osd_offset_y=20, splash_osd_scale=120,
        splash_osd_pill_position=1)
    config = splash_settings.read_settings(xbmcaddon.Addon())
    assert (config.show_on_start, config.show_on_osd, config.show_on_tinyppi, config.duration) == (
        True, False, True, 5)
    assert config.modes["osd"] == splash_settings.ModeSettings(
        show_video=False, show_audio=True, audio_first=True, offset_x=10, offset_y=20,
        scale=1.2, pill_at_top=True)
    assert config.modes["start"] == config.modes["tinyppi"] == splash_settings.ModeSettings(
        True, True, False, 0, 0, 1.0, False)


@pytest.mark.parametrize(("stored", "scale"), [
    ("100", 1.0), ("115", 1.15), ("80", 0.8), ("50", 0.8), ("130", 1.3), ("200", 1.3), ("big", 1.0),
])
def test_the_mode_size_is_clamped(stored, scale):
    use(splash_tinyppi_scale=stored)
    assert splash_settings._mode_scale(xbmcaddon.Addon(), "tinyppi") == pytest.approx(scale)


def test_an_unknown_mode_has_the_normal_size():
    assert splash_settings._mode_scale(xbmcaddon.Addon(), "pip") == 1.0


def test_mode_colours_come_from_the_theme_with_fallbacks():
    home = xbmcgui.Window(HOME)
    home.setProperty("TinyPPI.SplashOsdBgColor", "80102030")
    home.setProperty("TinyPPI.SplashOsdFelColor", "FF00FF00")
    home.setProperty("TinyPPI.SplashStartVideoColor", "FFFF0000")   # another mode's
    assert splash._mode_colors(home, "osd") == {
        "bg": "80102030", "video": "FFEDEDED", "audio": "FFEDEDED", "divider": "59FFFFFF",
        "convert_dot": "FF81C784", "fel": "FF00FF00", "mel": "FFFFB74D", "other": "FFEDEDED",
    }


# --- Visibility conditions --------------------------------------------------------

@pytest.mark.parametrize(("mode", "suppress", "run", "parts"), [
    ("start", False, "", [
        is_true("TinyPPI.SplashVisible"), is_true("TinyPPI.SplashStartVisible"),
        "!" + is_true("TinyPPI.Running"), "!" + is_true("TinyPPI.DialogMode")]),
    ("start", True, "7-1", [
        is_true("TinyPPI.SplashVisible"), is_true("TinyPPI.SplashStartVisible"),
        "String.IsEqual(Window(10000).Property(TinyPPI.SplashRun),7-1)",
        "!" + is_true("TinyPPI.Running"), "!" + is_true("TinyPPI.DialogMode"),
        "!Window.IsVisible(videoosd)"]),
    ("osd", True, "", [
        is_true("TinyPPI.SplashVisible"), is_true("TinyPPI.SplashOsdVisible"),
        "Window.IsVisible(videoosd)",
        "!" + is_true("TinyPPI.Running"), "!" + is_true("TinyPPI.DialogMode")]),
    ("tinyppi", False, "", [
        is_true("TinyPPI.SplashVisible"), is_true("TinyPPI.SplashTinyPPIVisible"),
        is_true("TinyPPI.Active"), "!" + is_true("TinyPPI.DialogMode")]),
])
def test_each_mode_has_its_own_visibility_condition(mode, suppress, run, parts):
    assert splash._visible_condition(mode, suppress, run).split(" + ") == parts


def test_a_mode_without_rules_of_its_own_needs_only_the_visibility_properties(monkeypatch):
    monkeypatch.setitem(splash._MODE_VISIBLE_PROPS, "pip", "TinyPPI.SplashPipVisible")
    assert splash._visible_condition("pip").split(" + ") == [
        is_true("TinyPPI.SplashVisible"), is_true("TinyPPI.SplashPipVisible")]


def test_mode_visibility_is_cleared_for_one_mode_or_all():
    home = xbmcgui.Window(HOME)
    for prop in (*VISIBLE.values(), "TinyPPI.Active"):
        home.setProperty(prop, "true")
    splash._clear_mode_visibility(home, "osd")
    assert set(xbmcgui.PROPERTIES[HOME]) == {VISIBLE["start"], VISIBLE["tinyppi"], "TinyPPI.Active"}
    splash._clear_mode_visibility(home)
    assert set(xbmcgui.PROPERTIES[HOME]) == {"TinyPPI.Active"}


# --- Fades ---------------------------------------------------------------------------

class Steps:
    """A video window and a monitor that note what had happened at each step."""

    def __init__(self, controls, aborting=False):
        self.controls, self.aborting = controls, aborting
        self.log, self.removed = [], []

    def addControls(self, controls):
        self.log.append(("add", [list(c.calls) for c in controls]))

    def removeControls(self, controls):
        self.removed.extend(controls)

    def waitForAbort(self, timeout):
        self.log.append(("wait", timeout, [len(c.calls) for c in self.controls],
                         dict(xbmcgui.PROPERTIES[HOME])))
        return self.aborting


def test_fading_in_hides_adds_binds_then_shows_and_finally_plays_the_fade():
    home = xbmcgui.Window(HOME)
    home.setProperty(VISIBLE["osd"], "true")        # left over from the previous run
    controls = [splash_panel._solid(0, 0, 10, 10, "FF000000") for _ in range(3)]
    dot = controls[2]
    steps = Steps(controls)
    splash._fade_in(steps, home, steps, "osd", controls, "COND", dot)

    hidden = [("setVisible", (False,))]
    assert steps.log == [
        ("add", [hidden, hidden, hidden]),
        ("wait", TICK, [2, 2, 2], {}),              # conditions bound, nothing published yet
        ("wait", TICK, [4, 4, 4], {}),              # animations armed and unhidden
    ]
    anims = ("setAnimations", ([splash._ANIM_IN, splash._ANIM_OUT],))
    assert controls[0].calls == [*hidden, ("setVisibleCondition", ("COND", False)), anims,
                                 ("setVisible", (True,))]
    assert dot.condition == "COND + " + is_true(CONVERTING)
    assert xbmcgui.PROPERTIES[HOME] == {"TinyPPI.SplashVisible": "true", VISIBLE["osd"]: "true"}


@pytest.mark.parametrize("aborting", [False, True])
def test_fading_out_hides_the_mode_and_removes_it_unless_kodi_stops(aborting):
    home = xbmcgui.Window(HOME)
    home.setProperty(VISIBLE["start"], "true")
    controls = [splash_panel._solid(0, 0, 10, 10, "FF000000")]
    steps = Steps(controls, aborting)
    splash._fade_out(steps, home, steps, "start", controls)
    assert steps.log == [("wait", FADE_OUT, [0], {})]
    assert steps.removed == ([] if aborting else controls)


def test_removing_from_a_window_that_is_gone_is_ignored():
    class Gone:
        tried = []

        def removeControls(self, controls):
            self.tried.append(controls)
            raise RuntimeError("window does not exist")

    controls = [splash_panel._solid(0, 0, 1, 1, "FF000000")]
    splash._remove_controls(Gone(), controls)       # does not raise
    assert Gone.tried == [controls]


# --- Settings handle -------------------------------------------------------------------

def test_the_settings_handle_is_used_once_it_reads(monkeypatch):
    handle = xbmcaddon.Addon()
    monkeypatch.setattr(splash.settings, "addon", lambda: handle)
    assert splash._safe_addon() is handle


class HalfLoaded(xbmcaddon.Addon):
    """A handle loaded without settings, as during an add-on update."""

    def getSettingBool(self, key):
        raise TypeError("no settings")


def unregistered():
    raise RuntimeError("unknown add-on id")


@pytest.mark.parametrize("handle", [unregistered, HalfLoaded])
def test_no_settings_handle_while_the_addon_updates(monkeypatch, handle):
    monkeypatch.setattr(splash.settings, "addon", handle)
    assert splash._safe_addon() is None


# --- The controller ----------------------------------------------------------------------

class RecordingWindow(xbmcgui.Window):
    """The stub window, noting property writes and control changes in order."""

    def __init__(self, window_id, kodi):
        super().__init__(window_id)
        self.kodi = kodi

    def setProperty(self, key, value):
        self.kodi.events.append(("set", key, value))
        super().setProperty(key, value)

    def clearProperty(self, key):
        self.kodi.events.append(("clear", key))
        super().clearProperty(key)

    def addControls(self, controls):
        self.kodi.events.append(("add", tuple(controls)))
        self.kodi.added_at.append(self.kodi.clock)
        if self.kodi.stop_when_drawn:
            self.kodi.playing = False
        super().addControls(controls)

    def removeControls(self, controls):
        self.kodi.events.append(("remove", tuple(controls)))
        super().removeControls(controls)


class Kodi:
    """Plays a video for the splash controller and records what it does.

    ``at(n, change)`` runs *change* when the controller asks for the n-th
    time whether a video plays (0 before its loop, then once per poll).  The
    clock moves only while the controller waits; a wait of ``abort_on``
    seconds makes Kodi ask the add-on to stop.
    """

    def __init__(self, monkeypatch):
        self.clock = 0.0
        self.abort = False
        self.abort_on = None
        self.playing = True
        self.stop_when_drawn = False
        self.polls = 0
        self.hooks = {}
        self.waits, self.events, self.added_at = [], [], []
        self.windows = {}
        self.addon = xbmcaddon.Addon()
        self.gamut = "SDR BT709"
        self.hdr_type = self.el_type = ""
        self.logos = ("codecs/SDR.png", "audio/aac.png")
        self.has_audio = True
        self.format_reads, self.el_reads, self.themes = [], 0, 0
        self.theme_handles = []
        self.theme = {}
        xbmc.CONDITIONS[FULLSCREEN] = True
        monkeypatch.setattr(splash.settings, "addon", self._settings)
        monkeypatch.setattr(xbmc, "Player", lambda: SimpleNamespace(isPlayingVideo=self._poll))
        monkeypatch.setattr(xbmc, "Monitor", lambda: SimpleNamespace(
            abortRequested=lambda: self.abort, waitForAbort=self._wait))
        monkeypatch.setattr(xbmcgui, "Window", self._window)
        monkeypatch.setattr(splash, "time", SimpleNamespace(
            monotonic=lambda: self.clock, monotonic_ns=lambda: int(self.clock * 1e9)))
        monkeypatch.setattr(splash, "get_hdr_format", self._hdr_format)
        monkeypatch.setattr(splash, "get_dv_el_type_raw", self._el_type)
        monkeypatch.setattr(splash, "current_logos", lambda token: self.logos)
        monkeypatch.setattr(splash, "video_has_audio", lambda player: self.has_audio)
        monkeypatch.setattr(splash, "apply_theme", self._apply_theme)
        # Draw on the first poll; the settle tests restore the real wait.
        monkeypatch.setattr(splash, "_SETTLE_SECONDS", 0.0)

    @property
    def gamut(self):
        return xbmc.INFO.get(GAMUT, "")

    @gamut.setter
    def gamut(self, value):
        xbmc.INFO[GAMUT] = value

    def at(self, poll, change):
        self.hooks[poll] = change

    def stop_at(self, poll):
        self.at(poll, lambda: setattr(self, "playing", False))

    def run(self):
        splash.open_splash()

    # Kodi's side.
    def _settings(self):
        if isinstance(self.addon, Exception):
            raise self.addon
        return self.addon

    def _poll(self):
        poll, self.polls = self.polls, self.polls + 1
        assert poll < 200, "the controller did not stop"
        self.hooks.pop(poll, lambda: None)()
        return self.playing

    def _wait(self, timeout):
        self.waits.append(timeout)
        self.clock += timeout
        if timeout == self.abort_on:
            self.abort = True
        return self.abort

    def _window(self, window_id=HOME):
        return self.windows.setdefault(window_id, RecordingWindow(window_id, self))

    def _hdr_format(self):
        self.format_reads.append(self.clock)
        return self.hdr_type

    def _el_type(self):
        self.el_reads += 1
        return self.el_type

    def _apply_theme(self, home, addon):
        self.themes += 1
        self.theme_handles.append(addon)
        for prop, value in self.theme.items():
            home.setProperty(prop, value)

    # What the controller did.
    @property
    def home(self):
        return xbmcgui.PROPERTIES.get(HOME, {})

    def drawn(self, mode=None):
        return [c for kind, c, *_ in self.events if kind == "add" and mode in (None, mode_of(c))]

    def timeline(self):
        return [(event[0], mode_of(event[1])) for event in self.events
                if event[0] in ("add", "remove")]

    def run_token(self):
        return next(value for kind, key, *value in self.events
                    if kind == "set" and key == splash.PROP_SPLASH_RUN)[0]

    def splash_props(self):
        return sorted(key for key in self.home if key.startswith("TinyPPI.Splash"))


def mode_of(controls):
    return next(mode for mode, prop in VISIBLE.items() if is_true(prop) in controls[0].condition)


def textures(controls):
    return [c.texture for c in controls]


@pytest.fixture
def kodi(monkeypatch):
    return Kodi(monkeypatch)


def nothing_enabled(kodi):
    use(splash_enabled=False)


def addon_updating(kodi):
    kodi.addon = RuntimeError("unknown add-on id")


def no_video(kodi):
    kodi.playing = False


def no_audio_logo(kodi):
    kodi.logos = ("codecs/SDR.png", "")      # both logos on: all or nothing


def another_splash_runs(kodi):
    xbmcgui.PROPERTIES[HOME] = {splash.PROP_SPLASH_ACTIVE: "true"}


@pytest.mark.parametrize("situation", [
    nothing_enabled, addon_updating, no_video, no_audio_logo, another_splash_runs,
])
def test_the_controller_returns_at_once_when_there_is_nothing_to_show(kodi, situation):
    use(splash_enabled=True)
    situation(kodi)
    kodi.run()
    assert kodi.events == [] and kodi.waits == []
    assert splash.WINDOW_FULLSCREEN_VIDEO not in kodi.windows
    if situation is another_splash_runs:
        assert kodi.home == {splash.PROP_SPLASH_ACTIVE: "true"}


def test_the_start_logos_show_for_the_set_duration_then_the_controller_ends(kodi):
    use(splash_enabled=True, splash_duration=1)
    kodi.run()

    assert kodi.timeline() == [("add", "start"), ("remove", "start")]
    assert kodi.playing and kodi.abort is False          # it ended by itself
    (controls,) = kodi.drawn()
    assert len(controls) == 13                           # panel, divider, two logos, badge
    assert textures(controls)[10:12] == [media("codecs/SDR.png"), media("audio/aac.png")]
    assert [c.color for c in controls[10:12]] == ["FFEDEDED", "FFEDEDED"]   # theme fallbacks

    run = kodi.run_token()
    assert run == f"{os.getpid()}-0"
    condition = " + ".join([
        is_true("TinyPPI.SplashVisible"), is_true(VISIBLE["start"]),
        f"String.IsEqual(Window(10000).Property(TinyPPI.SplashRun),{run})",
        "!" + is_true("TinyPPI.Running"), "!" + is_true("TinyPPI.DialogMode"),
    ])
    assert {c.condition for c in controls[:-1]} == {condition}
    assert controls[-1].condition == condition + " + " + is_true(CONVERTING)

    shown = kodi.events.index(("set", VISIBLE["start"], "true"))
    hidden = kodi.events.index(("clear", VISIBLE["start"]), shown)
    assert kodi.events.index(("add", controls)) < shown < hidden
    assert kodi.events.index(("remove", controls)) == hidden + 1
    # The last poll waits only for what is left of the start window.
    assert pytest.approx(0.15) in kodi.waits
    assert kodi.waits[-1] == FADE_OUT
    assert kodi.splash_props() == []


def test_the_osd_and_overlay_logos_follow_the_fullscreen_window(kodi):
    use(splash_show_on_osd=True, splash_show_on_tinyppi=True)
    kodi.at(2, lambda: xbmc.CONDITIONS.update({FULLSCREEN: False}))
    kodi.at(3, lambda: xbmc.CONDITIONS.update({FULLSCREEN: True}))
    kodi.stop_at(4)
    kodi.run()

    assert kodi.timeline() == [
        ("add", "osd"), ("add", "tinyppi"),
        ("remove", "osd"), ("remove", "tinyppi"),        # left fullscreen
        ("add", "osd"), ("add", "tinyppi"),              # back again
        ("remove", "osd"), ("remove", "tinyppi"),        # playback ended
    ]
    osd, tinyppi = kodi.drawn()[:2]
    assert "+ Window.IsVisible(videoosd) +" in osd[0].condition
    assert is_true("TinyPPI.Active") in tinyppi[0].condition
    # Both fade out together: one wait, then both are removed.
    first_remove = kodi.events.index(("remove", osd))
    assert kodi.events[first_remove - 2:first_remove] == [
        ("clear", VISIBLE["osd"]), ("clear", VISIBLE["tinyppi"])]
    assert kodi.waits.count(FADE_OUT) == 1
    assert kodi.splash_props() == []


def test_a_video_without_audio_shows_its_video_logo_alone(kodi):
    use(splash_enabled=True)
    kodi.logos, kodi.has_audio = ("codecs/SDR.png", ""), False
    kodi.stop_at(2)
    kodi.run()

    (start,) = kodi.drawn()
    assert textures(start)[9] == media("codecs/SDR.png") and len(start) == 11


def test_outside_fullscreen_the_controller_keeps_polling_for_the_osd_logos(kodi):
    use(splash_show_on_osd=True)
    kodi.gamut, kodi.hdr_type = "HDR10 BT2020", "hdr10"
    xbmc.CONDITIONS[FULLSCREEN] = False
    kodi.at(10, lambda: xbmc.CONDITIONS.update({FULLSCREEN: True}))
    kodi.stop_at(11)
    kodi.run()

    assert kodi.timeline() == [("add", "osd"), ("remove", "osd")]
    assert kodi.waits[:9] == [POLL] * 9
    # Polls every 0.25 s outside fullscreen: the known format is re-read on the second.
    assert kodi.format_reads == [0.0, 1.0, 2.0]


def test_a_mode_without_logos_draws_nothing_while_the_others_show(kodi):
    use(splash_enabled=True, splash_start_show_audio=False,
        splash_show_on_osd=True, splash_osd_show_video=False)
    kodi.logos = ("codecs/SDR.png", "")
    kodi.stop_at(2)
    kodi.run()

    assert kodi.timeline() == [("add", "start"), ("remove", "start")]
    (start,) = kodi.drawn()
    assert textures(start)[9] == media("codecs/SDR.png") and len(start) == 11
    # The OSD is on, so the start logos make way for it.
    assert start[0].condition.endswith(" + !Window.IsVisible(videoosd)")


def test_a_new_audio_track_redraws_the_logos(kodi):
    use(splash_enabled=True, splash_show_on_osd=True)
    kodi.gamut, kodi.hdr_type = "HDR10 BT2020", "hdr10"
    kodi.logos = ("codecs/HDR10.png", "audio/aac.png")
    kodi.at(2, lambda: setattr(kodi, "logos", ("codecs/HDR10.png", "audio/truehd.png")))
    kodi.stop_at(3)
    kodi.run()

    assert kodi.timeline() == [
        ("add", "start"), ("add", "osd"),
        ("remove", "start"), ("add", "start"), ("remove", "osd"), ("add", "osd"),
        ("remove", "start"), ("remove", "osd"),
    ]
    old_start, old_osd, new_start, new_osd = kodi.drawn()
    assert media("audio/truehd.png") in textures(new_start)
    assert media("audio/truehd.png") in textures(new_osd)
    assert kodi.events[-2:] == [("remove", new_start), ("remove", new_osd)]
    lines = [line for _level, line in xbmc.LOG]
    for mode in ("start", "osd"):
        assert f"TinyPPI [splash]: {mode} redrawn for output 'HDR10 BT2020', source 'hdr10'" in lines


def test_changed_settings_redraw_with_the_new_theme_and_position(kodi):
    use(splash_enabled=True)
    kodi.theme = {"TinyPPI.SplashStartVideoColor": "FF102030"}

    def change_settings():
        use(splash_start_offset_x=100)
        kodi.theme = {"TinyPPI.SplashStartVideoColor": "FF405060"}
        kodi.addon = xbmcaddon.Addon()              # Kodi hands out a new handle

    first = kodi.addon
    kodi.at(3, change_settings)
    kodi.stop_at(5)
    kodi.run()

    before, after = kodi.drawn()
    assert kodi.themes == 2                         # once per settings change, not per poll
    # Each time from the handle the settings were read from.
    assert kodi.theme_handles[0] is first and kodi.theme_handles[1] is kodi.addon
    assert (before[10].color, after[10].color) == ("FF102030", "FF405060")
    assert before[11].color == "FFEDEDED"
    assert bounds(before[:9])[0] == 35 and bounds(after[:9])[2] == 1920 - 35


def test_the_conversion_badge_follows_the_output(kodi):
    use(splash_show_on_osd=True)
    kodi.gamut, kodi.hdr_type = "DV-STD BT2020", "hdr10"         # HDR10 shown as DV
    kodi.at(3, lambda: setattr(kodi, "gamut", "HDR10 BT2020"))   # passed through
    kodi.stop_at(5)
    kodi.run()

    assert [e for e in kodi.events if e[1:2] == (CONVERTING,)] == [
        ("set", CONVERTING, "true"), ("set", CONVERTING, "false"), ("clear", CONVERTING)]
    first, second = kodi.drawn()
    assert first[-2].condition.endswith(" + " + is_true(CONVERTING))
    # Shown as DV, the panel has a pill; as HDR10, none.
    assert textures(first)[-1] == media("common/pill.png")
    assert media("common/pill.png") not in textures(second)


@pytest.mark.parametrize(("gamut", "source", "el_type", "pill"), [
    ("DV-STD BT2020", "dolbyvision", "FEL", "FF81C784"),
    ("DV-STD BT2020", "dolbyvision", "MEL", "FFFFB74D"),
    ("DV-STD BT2020", "dolbyvision", "", "FFEDEDED"),      # profile 5 or 8
    ("HDR10 BT2020", "hdr10", "FEL", None),
])
def test_the_layer_pill_shows_the_dolby_vision_layer(kodi, gamut, source, el_type, pill):
    use(splash_show_on_osd=True)
    kodi.gamut, kodi.hdr_type, kodi.el_type = gamut, source, el_type
    kodi.stop_at(2)
    kodi.run()

    (controls,) = kodi.drawn()
    pills = [c.color for c in controls if c.texture == media("common/pill.png")]
    assert pills == ([pill] if pill else [])
    # The layer is read only for a Dolby Vision source.
    assert (kodi.el_reads > 0) is (source == "dolbyvision")


def test_a_known_source_format_is_read_once_a_second_or_when_the_output_changes(kodi):
    use(splash_show_on_osd=True)
    kodi.gamut, kodi.hdr_type = "HDR10 BT2020", "hdr10"
    kodi.at(7, lambda: setattr(kodi, "gamut", "HLG BT2020"))
    kodi.stop_at(10)
    kodi.run()

    # Polls at 0, 0.35, 0.6, ... (the first drawing takes two render ticks).
    assert kodi.format_reads == pytest.approx([0.0, 1.1, 1.6])
    assert len(kodi.drawn()) == 1                    # same logos: nothing redrawn


@pytest.mark.parametrize(("source", "outputs", "settled", "gamut"), [
    ("", {}, 1.0, "SDR BT709"),
    ("hdr10", {}, 3.0, "SDR BT709"),                       # never switches: believed at last
    ("hdr10", {7: "HDR10 BT2020"}, 2.5, "HDR10 BT2020"),   # switches at 1.5 s
    ("dolbyvision", {3: "DV-STD BT2020", 4: "SDR BT709", 5: "DV-STD BT2020"}, 2.0,
     "DV-STD BT2020"),                                     # flickers until 1.0 s
])
def test_nothing_is_drawn_until_the_output_has_settled(kodi, monkeypatch, source, outputs,
                                                       settled, gamut):
    monkeypatch.setattr(splash, "_SETTLE_SECONDS", 1.0)
    use(splash_enabled=True)
    kodi.hdr_type = source
    for poll, output in outputs.items():
        kodi.at(poll, lambda output=output: setattr(kodi, "gamut", output))
    kodi.stop_when_drawn = True
    kodi.run()

    assert kodi.added_at == [pytest.approx(settled)]
    assert (f"TinyPPI [splash]: output settled after {settled:.1f}s at {gamut!r}, "
            f"source {source or 'sdr'!r}") in [line for _level, line in xbmc.LOG]
    assert kodi.timeline() == [("add", "start"), ("remove", "start")]


@pytest.mark.parametrize("poll", [0, 2])
def test_kodi_stopping_before_anything_is_drawn_frees_the_guard(kodi, monkeypatch, poll):
    monkeypatch.setattr(splash, "_SETTLE_SECONDS", 1.0)
    use(splash_enabled=True)
    kodi.at(poll, lambda: setattr(kodi, "abort", True))
    kodi.run()

    assert kodi.drawn() == []
    assert kodi.waits == [POLL] * poll
    assert ("set", splash.PROP_SPLASH_ACTIVE, "true") in kodi.events
    assert kodi.splash_props() == []


def redraw(kodi):
    kodi.logos = ("codecs/SDR.png", "audio/truehd.png")


def leave_fullscreen(kodi):
    xbmc.CONDITIONS[FULLSCREEN] = False


@pytest.mark.parametrize(("change", "abort_on"), [
    (redraw, FADE_OUT),             # while the old logos fade out
    (leave_fullscreen, FADE_OUT),   # while the mode fades out
    (redraw, 0),                    # just before the new logos are added
    (lambda kodi: None, POLL),      # while the logos are on screen
])
def test_kodi_stopping_leaves_the_controls_hidden_by_their_run_token(kodi, change, abort_on):
    use(splash_show_on_osd=True)

    def stop():
        change(kodi)
        kodi.abort_on = abort_on
        kodi.abort = abort_on == 0

    kodi.at(2, stop)
    kodi.run()

    # Removing controls waits on Kodi's GUI thread, which no longer answers.
    assert kodi.timeline() == [("add", "osd")]
    (controls,) = kodi.drawn()
    assert kodi.run_token() in controls[0].condition
    assert {e[1] for e in kodi.events if e[0] == "clear"} >= {
        splash.PROP_SPLASH_RUN, splash.PROP_SPLASH_VISIBLE, VISIBLE["osd"]}
    assert kodi.splash_props() == []


def test_kodi_stopping_while_one_mode_fades_in_draws_no_other(kodi):
    use(splash_show_on_osd=True, splash_show_on_tinyppi=True)
    kodi.abort_on = TICK
    kodi.run()

    assert kodi.timeline() == [("add", "osd")]
    assert kodi.splash_props() == []


class NoSettings(xbmcaddon.Addon):
    """Verifies, but its settings vanish on the next read (add-on update)."""

    def getSettingInt(self, key):
        raise TypeError("settings vanished")


@pytest.mark.parametrize("handle", [RuntimeError("unknown add-on id"), NoSettings()])
def test_settings_vanishing_mid_run_still_cleans_up(kodi, handle):
    use(splash_show_on_osd=True)
    kodi.at(3, lambda: setattr(kodi, "addon", handle))
    kodi.run()

    assert kodi.timeline() == [("add", "osd"), ("remove", "osd")]
    assert kodi.playing and kodi.polls == 4
    assert kodi.splash_props() == []


def test_a_redraw_at_the_end_of_the_start_window_never_waits_a_negative_time(kodi):
    use(splash_enabled=True, splash_duration=1)
    kodi.at(4, lambda: redraw(kodi))      # at 0.85 s; the redraw takes 0.31 s
    kodi.run()

    assert kodi.timeline() == [("add", "start"), ("remove", "start"), ("add", "start"),
                               ("remove", "start")]
    assert min(kodi.waits) > 0
    assert kodi.waits[-2:] == [POLL, FADE_OUT]
