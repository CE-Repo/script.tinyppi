# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Every TinyPPI setting with an effect on a desktop Kodi 22, set live and
measured: properties, behaviour, and the panels on screen.

The picture is plain gray and the panels are painted in signal colours, so
each panel is the bounding box of its colour in a screenshot.  The ten
settings that only act with Dolby Vision or on Amlogic hardware are covered
by tests/unit/test_settings_logic.py.  ``python3 run_settings.py splash``
runs the codec-logo part alone.
"""

import json
import os
import sys
import time
import traceback
import xml.etree.ElementTree as ET

import config
import driver as kodi
import screen
from driver import props, set_settings, wait
from report import Report
from screen import BLUE, CYAN, GREEN, MAGENTA, RED, YELLOW, hexcolor

# The add-on's own modules give the expected values (Kodi stubbed out).
sys.path[:0] = [os.path.join(config.REPO, "tests", "stubs"), os.path.join(config.REPO, "resources", "lib")]
from ui import splash as S  # noqa: E402
from ui import theme  # noqa: E402

HDR = config.GRAY_HDR10
SDR = config.GRAY_SDR
TOKEN = config.TOKEN
REPORT = Report("settings")
check = REPORT.check
section = REPORT.section
ONLY = sys.argv[1:]


def running():
    return props("TinyPPI.Running")["TinyPPI.Running"] == "true"


def open_overlay(settle=2.0):
    if running():
        close_overlay()
    kodi.rpc("JSONRPC.NotifyAll", {"sender": "script.tinyppi", "message": "open_overlay"})
    ok = wait(running, 10)
    time.sleep(settle)
    return bool(ok)


def close_overlay():
    if running():
        kodi.rpc("Input.Back")
        wait(lambda: not running(), 8)
        time.sleep(0.8)


def size(box):
    return (box[2] - box[0], box[3] - box[1]) if box else None


def capture(name, rgb, tol=45):
    path = kodi.shot(name)
    return path, screen.bbox(path, rgb, tol)


def dialog_open(settle=2.5):
    kodi.rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi", "params": ["dialog"]})
    wait(lambda: "dialog" in os.path.basename(kodi.xmlfile()), 10)
    time.sleep(settle)
    return os.path.basename(kodi.xmlfile())


def dialog_close():
    if "tinyppi-dialog" in kodi.xmlfile():
        kodi.rpc("Input.Back")
        wait(lambda: "tinyppi-dialog" not in kodi.xmlfile(), 6)
        time.sleep(0.8)


def jget(path, token=None, port=config.DASHBOARD_PORT):
    headers = {"X-TinyPPI-Token": token} if token else {}
    status, _, body = kodi.http(path, headers=headers, port=port)
    try:
        return status, json.loads(body)
    except Exception:
        return status, None


def post(path, body, token=TOKEN, port=config.DASHBOARD_PORT):
    status, _, raw = kodi.http(path, method="POST", body=body, headers={"X-TinyPPI-Token": token}, port=port)
    return status


def port_open(port):
    try:
        return kodi.http("/api/hello", port=port, timeout=2)[0] == 200
    except Exception:
        return False


def defaults():
    tree = ET.parse(os.path.join(config.REPO, "resources", "settings.xml")).getroot()
    return {s.get("id"): s.findtext("default") for s in tree.iter("setting") if s.findtext("default") is not None}


DEFAULTS = defaults()
BASE = {  # colours that make the panels measurable on a gray picture
    "background_color": hexcolor(RED), "background_opacity": 100,
    "global_background_opacity": 0,
    "dialog_background_color": hexcolor(GREEN), "dialog_background_opacity": 100,
    "dialog_global_background_opacity": 0,
    "splash_start_bg_color": hexcolor(BLUE), "splash_start_bg_opacity": 100,
    "splash_osd_bg_color": hexcolor(BLUE), "splash_osd_bg_opacity": 100,
    "splash_tinyppi_bg_color": hexcolor(BLUE), "splash_tinyppi_bg_opacity": 100,
}


def theme_tests():
    section("colours and opacities (all colour settings)")
    entries = theme._THEME_PROPERTIES
    values, expected = {}, {}
    for i, (prop, _palette, sid) in enumerate(entries):
        rgb = ((i * 37 + 11) % 256, (i * 91 + 23) % 256, (i * 53 + 17) % 256)
        opacity = (i * 13 + 5) % 101
        values[sid] = hexcolor(rgb)
        values[theme._opacity_setting(sid)] = opacity
        expected[prop] = f"{int(opacity * 255 / 100 + 0.5):02X}" + "".join(f"{c:02X}" for c in rgb)
    set_settings(**values)
    open_overlay(1.0)
    got = props(*expected)
    wrong = {p: (got[p], e) for p, e in expected.items() if got[p] != e}
    check(f"every colour setting ({len(entries)}) with its opacity slider reaches its skin property (HEX colours)",
          not wrong, wrong, settings=list(values))
    close_overlay()

    values, expected = {}, {}
    for i, (prop, _palette, sid) in enumerate(entries):
        spec = theme._COLOR_SETTINGS[sid]
        index = (i % (len(spec.names) - 1)) + 1 if len(spec.names) > 1 else 0
        values[sid] = theme._encode(spec, index)
        values[theme._opacity_setting(sid)] = 50
        expected[prop] = "80" + spec.palette[index][2:]
    set_settings(**values)
    open_overlay(1.0)
    got = props(*expected)
    wrong = {p: (got[p], e) for p, e in expected.items() if got[p] != e}
    check("every colour setting resolves palette entries (as the picker stores them)", not wrong, wrong)
    close_overlay()

    values = {}
    expected = {}
    for prop, _palette, sid in entries:
        spec = theme._COLOR_SETTINGS[sid]
        values[sid] = DEFAULTS[sid]
        op_id = theme._opacity_setting(sid)
        values[op_id] = DEFAULTS[op_id]
        expected[prop] = f"{int(int(DEFAULTS[op_id]) * 255 / 100 + 0.5):02X}" + spec.palette[spec.default][2:]
    set_settings(**values)
    open_overlay(1.0)
    got = props(*expected)
    wrong = {p: (got[p], e) for p, e in expected.items() if got[p] != e}
    check("the out-of-the-box values give the default palette", not wrong, wrong)
    path = kodi.shot("theme-defaults")
    close_overlay()

    labels = {}
    for value in (0, 1, 2):
        set_settings(unit_type=value)
        open_overlay(0.8)
        labels[value] = props("TinyPPI.UnitLabel")["TinyPPI.UnitLabel"]
        close_overlay()
    want = {v: theme._pick(theme._UNIT_LABELS, str(v)) for v in labels}
    check("unit_type: each choice publishes its unit label", labels == want and len(set(labels.values())) == 3,
          labels, settings=["unit_type"])
    set_settings(unit_type=0)

    section("colours on screen (end to end)")
    set_settings(**BASE, title_color=hexcolor(YELLOW), title_opacity=100, description_color=hexcolor(CYAN),
                 description_opacity=100)
    open_overlay(2.0)
    path, box = capture("overlay-colours", RED)
    check("background_color + background_opacity paint the overlay panel", box and size(box)[0] > 1000, box,
          settings=["background_color", "background_opacity"])
    inside = screen.pixels(path, YELLOW, 60)
    check("title_color paints the title", inside > 300, f"{inside} px", settings=["title_color", "title_opacity"])
    inside = screen.pixels(path, CYAN, 60)
    check("description_color paints the row labels", inside > 1000, f"{inside} px",
          settings=["description_color", "description_opacity"])
    close_overlay()
    set_settings(global_background_color=hexcolor(MAGENTA), global_background_opacity=100)
    open_overlay(2.0)
    path = kodi.shot("overlay-global-bg")
    count = screen.pixels(path, MAGENTA)
    check("global_background_color + opacity dim the whole picture", count > 500000, f"{count} px",
          settings=["global_background_color", "global_background_opacity"])
    close_overlay()
    set_settings(**BASE, title_color=DEFAULTS["title_color"], description_color=DEFAULTS["description_color"])


def general_tests():
    section("general / overlay")
    for value, want in ((False, "0"), (True, "1")):
        set_settings(show_l5_icon=value)
        open_overlay(0.8)
        got = props("TinyPPI.ShowL5Icon")["TinyPPI.ShowL5Icon"]
        check(f"show_l5_icon={value} -> ShowL5Icon {want}", got == want, got, settings=["show_l5_icon"])
        close_overlay()

    for value in (True, False):
        set_settings(filename=value)
        open_overlay(1.0)
        got = props("TinyPPI.Filename")["TinyPPI.Filename"]
        state = jget("/api/state")[1] or {}
        sent = state.get("filename", "")
        check(f"filename={value}: overlay row {'on' if value else 'off'}, dashboard {'sends' if value else 'withholds'} the path",
              got == ("true" if value else "false") and (("gray_hdr10" in sent) == value), (got, sent), settings=["filename"])
        close_overlay()

    set_settings(background_opacity=0)
    open_overlay(1.5)
    got = props("TinyPPI.ShowLine", "TinyPPI.ShowHeaderTitle", "TinyPPI.ShowHeaderIcon")
    path, box = capture("overlay-transparent", RED)
    check("background_opacity 0: transparent panel, no header or lines", set(got.values()) == {"0"} and box is None,
          (got, box), settings=["background_opacity"])
    close_overlay()
    set_settings(background_opacity=100)

    set_settings(auto_hide=3)
    open_overlay(0.2)
    start = time.time()
    hidden = wait(lambda: not running(), 12, 0.3)
    took = time.time() - start
    check("auto_hide 3 s closes the overlay by itself", hidden and 2.0 <= took <= 6.0, f"{took:.1f} s", settings=["auto_hide"])
    set_settings(auto_hide=0)
    open_overlay(6.0)
    check("auto_hide 0 keeps it open", running(), settings=["auto_hide"])
    close_overlay()

    set_settings(launch_mode=1)
    kodi.rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi"})
    xml = wait(lambda: (lambda x: x if "tinyppi-dialog" in x else None)(kodi.xmlfile()), 10)
    check("launch_mode 1: the launch opens the VS10 dialog", xml, xml, settings=["launch_mode"])
    dialog_close()
    set_settings(launch_mode=0)
    kodi.rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi"})
    check("launch_mode 0: the launch opens the overlay", wait(running, 10), settings=["launch_mode"])
    close_overlay()

    boxes = {}
    for y in (0, 100):
        set_settings(offset_y=y)
        open_overlay(1.5)
        boxes[y] = capture(f"overlay-offset-y{y}", RED)[1]
        close_overlay()
    check("offset_y moves the overlay up", boxes[0] and boxes[100] and boxes[100][1] < boxes[0][1] - 100, boxes,
          settings=["offset_y"])
    set_settings(offset_y=0)

    set_settings(nudge_position=True)
    open_overlay(1.5)
    before = capture("nudge-before", RED)[1]
    for _ in range(5):
        kodi.rpc("Input.Up")
        time.sleep(0.25)
    time.sleep(1.0)
    after = capture("nudge-after", RED)[1]
    check("nudge_position on: arrow keys move the overlay", before and after and after[1] < before[1] - 30,
          (before, after), settings=["nudge_position"])
    close_overlay()
    open_overlay(1.5)
    reopened = capture("nudge-reopened", RED)[1]
    check("a nudge is not saved (reopened at the configured place)", reopened and abs(reopened[1] - before[1]) <= 2,
          (before, reopened), settings=["nudge_position"])
    close_overlay()
    set_settings(nudge_position=False)
    open_overlay(1.5)
    before = capture("nudge-off-before", RED)[1]
    for _ in range(5):
        kodi.rpc("Input.Up")
        time.sleep(0.25)
    time.sleep(1.0)
    after = capture("nudge-off-after", RED)[1]
    check("nudge_position off: arrow keys leave it in place", before == after, (before, after), settings=["nudge_position"])
    close_overlay()


def sdr_overlay_tests():
    section("overlay on an SDR title")
    boxes = {}
    for x in (0, 100):
        set_settings(offset_x=x)
        open_overlay(1.5)
        boxes[x] = capture(f"overlay-sdr-offset-x{x}", RED)[1]
        close_overlay()
    check("offset_x moves the narrow (SDR) overlay right", boxes[0] and boxes[100] and boxes[100][0] > boxes[0][0] + 300,
          boxes, settings=["offset_x"])
    set_settings(offset_x=0)
    channels("sdr")


def channels(kind):
    setting = f"channels_{kind}"
    counts = {}
    for value in (True, False):
        set_settings(**{setting: value, "channel_icon_color": hexcolor(MAGENTA), "channel_icon_opacity": 100,
                        "channel_layout_color": hexcolor(CYAN), "channel_layout_opacity": 100})
        open_overlay(2.0)
        shown = props("TinyPPI.ShowChannelIcon")["TinyPPI.ShowChannelIcon"]
        path = kodi.shot(f"channels-{kind}-{value}")
        counts[value] = (shown, screen.pixels(path, MAGENTA, 60), screen.pixels(path, CYAN, 60))
        close_overlay()
    on, off = counts[True], counts[False]
    check(f"{setting}: speaker graphic on/off, in its icon and layout colours", on[0] == "1" and off[0] == "0"
          and on[1] > 300 and off[1] < 50 and on[2] > 300, counts,
          settings=[setting, "channel_icon_color", "channel_icon_opacity", "channel_layout_color", "channel_layout_opacity"])
    set_settings(**{setting: False})


def dialog_tests():
    section("VS10 dialog")
    seen = {}
    for mode in (2, 1, 0):
        set_settings(dialog_mode=mode)
        xml = dialog_open()
        box = capture(f"dialog-mode{mode}", GREEN)[1]
        seen[mode] = (xml, size(box))
        dialog_close()
    want = {0: ("script-tinyppi-dialog.xml", (471, 546)), 1: ("script-tinyppi-dialog-bar.xml", (1702, 206)),
            2: ("script-tinyppi-dialog-single.xml", (700, 216))}
    ok = all(seen[m][0] == want[m][0] and seen[m][1] and abs(seen[m][1][0] - want[m][1][0]) <= 6
             and abs(seen[m][1][1] - want[m][1][1]) <= 6 for m in want)
    check("dialog_mode: single / bar / dialog layouts at their sizes", ok, seen, settings=["dialog_mode"])
    set_settings(dialog_mode=2)

    boxes = {}
    for x in (0, 100):
        set_settings(dialog_position_x=x)
        dialog_open()
        boxes[x] = capture(f"dialog-x{x}", GREEN)[1]
        dialog_close()
    check("dialog_position_x moves the dialog across", boxes[0] and boxes[100] and boxes[100][0] > boxes[0][0] + 500, boxes,
          settings=["dialog_position_x"])
    set_settings(dialog_position_x=50)
    boxes = {}
    for y in (0, 100):
        set_settings(dialog_position_y=y)
        dialog_open()
        boxes[y] = capture(f"dialog-y{y}", GREEN)[1]
        dialog_close()
    check("dialog_position_y moves the dialog up and down", boxes[0] and boxes[100] and boxes[100][1] > boxes[0][1] + 400, boxes,
          settings=["dialog_position_y"])
    set_settings(dialog_position_y=100)

    set_settings(dialog_global_background_color=hexcolor(MAGENTA), dialog_global_background_opacity=100,
                 dialog_focus_color=hexcolor(YELLOW), dialog_focus_opacity=100,
                 dialog_header_color=hexcolor(CYAN), dialog_header_opacity=100)
    dialog_open()
    path, box = capture("dialog-colours", GREEN)
    check("dialog_background_color paints the dialog", box is not None, box,
          settings=["dialog_background_color", "dialog_background_opacity"])
    check("dialog_global_background_color dims the picture", screen.pixels(path, MAGENTA) > 500000,
          screen.pixels(path, MAGENTA), settings=["dialog_global_background_color", "dialog_global_background_opacity"])
    check("dialog_focus_color paints the focused button", screen.pixels(path, YELLOW, 50) > 2000, screen.pixels(path, YELLOW, 50),
          settings=["dialog_focus_color", "dialog_focus_opacity"])
    check("dialog_header_color paints the heading", screen.pixels(path, CYAN, 60) > 200, screen.pixels(path, CYAN, 60),
          settings=["dialog_header_color", "dialog_header_opacity"])
    dialog_close()
    set_settings(dialog_global_background_opacity=0, dialog_focus_color=DEFAULTS["dialog_focus_color"],
                 dialog_focus_opacity=DEFAULTS["dialog_focus_opacity"], dialog_header_color=DEFAULTS["dialog_header_color"])


def splash_variants(mode, show, restart=None):
    """Check show/order/offset/scale of one splash mode while it is visible."""
    prefix = f"splash_{mode}_"
    visible_prop = S._MODE_VISIBLE_PROPS[mode]

    def grab(name, settle=2.5):
        time.sleep(settle)
        show()
        wait(lambda: props(visible_prop)[visible_prop] == "true", 8, 0.3)
        time.sleep(1.0)
        path = kodi.shot(f"splash-{mode}-{name}")
        return path, screen.bluish_bbox(path)

    path_a, a = grab("base", 0.5)
    check(f"{mode} logos shown on the configured colour", a is not None, a,
          settings=[prefix + "bg_color", prefix + "bg_opacity"])
    if not a:
        return
    set_settings(**{prefix + "show_video": False})
    _, b = grab("no-video")
    set_settings(**{prefix + "show_video": True, prefix + "show_audio": False})
    _, c = grab("no-audio")
    set_settings(**{prefix + "show_audio": True})
    check(f"{prefix}show_video / show_audio drop one logo", b and c and size(b)[1] < size(a)[1] * 0.75
          and size(c)[1] < size(a)[1] * 0.75, (size(a), size(b), size(c)),
          settings=[prefix + "show_video", prefix + "show_audio"])
    set_settings(**{prefix + "order": 1})
    path_d, d = grab("order")
    set_settings(**{prefix + "order": 0})
    diff = screen.difference(path_a, path_d, a) if d else 0
    check(f"{prefix}order swaps the logos", d and size(d) == size(a) and diff > 8, (size(a), size(d), round(diff, 1)),
          settings=[prefix + "order"])
    if restart:
        restart()   # a fresh start window for the second half
    set_settings(**{prefix + "offset_x": 100, prefix + "offset_y": 100})
    _, e = grab("offset")
    set_settings(**{prefix + "offset_x": 0, prefix + "offset_y": 0})
    check(f"{prefix}offset_x / offset_y move the logos", e and e[0] > a[0] + 600 and e[1] > a[1] + 300, (a, e),
          settings=[prefix + "offset_x", prefix + "offset_y"])
    sizes = {}
    for scale in (80, 130):
        set_settings(**{prefix + "scale": scale})
        sizes[scale] = size(grab(f"scale{scale}")[1])
    set_settings(**{prefix + "scale": 100})
    ratio = sizes[130][0] / sizes[80][0] if sizes[80] and sizes[130] else 0
    check(f"{prefix}scale resizes the logos", 1.45 <= ratio <= 1.80, (size(a), sizes, round(ratio, 2)),
          settings=[prefix + "scale"])


def splash_tests():
    section("codec logos: on playback start")
    set_settings(splash_enabled=True, splash_duration=30, splash_show_on_osd=False, splash_show_on_tinyppi=False)
    kodi.stop()
    kodi.play(SDR)
    visible = wait(lambda: props("TinyPPI.SplashStartVisible")["TinyPPI.SplashStartVisible"] == "true", 15, 0.3)
    check("splash_enabled shows the logos when a video starts", visible, settings=["splash_enabled"])
    def restart():
        kodi.stop()
        kodi.play(SDR)
        wait(lambda: props("TinyPPI.SplashStartVisible")["TinyPPI.SplashStartVisible"] == "true", 15, 0.3)
    splash_variants("start", lambda: None, restart)
    set_settings(splash_duration=90)
    held = kodi.get_settings("splash_duration")["splash_duration"]
    check("splash_duration keeps to its 1-30 s range (90 is refused, 30 stays)", held == "30", held,
          settings=["splash_duration"])
    set_settings(splash_duration=4)
    gone = wait(lambda: props("TinyPPI.SplashStartVisible")["TinyPPI.SplashStartVisible"] != "true", 8, 0.3)
    check("splash_duration: a shorter duration ends a running start window", gone, settings=["splash_duration"])
    kodi.stop()
    kodi.play(SDR)
    shown = wait(lambda: props("TinyPPI.SplashStartVisible")["TinyPPI.SplashStartVisible"] == "true", 15, 0.2)
    t0 = time.time()
    hidden = wait(lambda: props("TinyPPI.SplashStartVisible")["TinyPPI.SplashStartVisible"] != "true", 15, 0.2)
    span = time.time() - t0
    check("splash_duration 4 s: the logos stand about 4 s", shown and hidden and 3.0 <= span <= 6.0, f"{span:.1f} s",
          settings=["splash_duration"])
    set_settings(splash_enabled=False, splash_duration=8)
    kodi.stop()
    kodi.play(SDR)
    time.sleep(5)
    check("splash_enabled off: no logos at playback start",
          props("TinyPPI.SplashStartVisible")["TinyPPI.SplashStartVisible"] != "true", settings=["splash_enabled"])

    section("codec logos: with the video OSD")
    set_settings(splash_show_on_osd=True)

    def show_osd():
        if "VideoOSD" not in kodi.xmlfile():
            kodi.rpc("Input.ShowOSD")
            time.sleep(0.8)
    show_osd()
    visible = wait(lambda: props("TinyPPI.SplashOsdVisible")["TinyPPI.SplashOsdVisible"] == "true", 10, 0.3)
    check("splash_show_on_osd shows the logos with the OSD", visible, settings=["splash_show_on_osd"])
    splash_variants("osd", show_osd)
    if "VideoOSD" in kodi.xmlfile():
        kodi.rpc("Input.Back")
        time.sleep(1.5)
    time.sleep(1.5)
    path = kodi.shot("splash-osd-closed")
    check("... and hides them with it", "VideoOSD" not in kodi.xmlfile() and screen.bluish_bbox(path) is None,
          screen.bluish_bbox(path), settings=["splash_show_on_osd"])
    set_settings(splash_show_on_osd=False)

    section("codec logos: with the TinyPPI overlay")
    set_settings(splash_show_on_tinyppi=True)
    open_overlay(1.0)
    visible = wait(lambda: props("TinyPPI.SplashTinyPPIVisible")["TinyPPI.SplashTinyPPIVisible"] == "true", 10, 0.3)
    check("splash_show_on_tinyppi shows the logos with the overlay", visible, settings=["splash_show_on_tinyppi"])
    splash_variants("tinyppi", lambda: None)
    close_overlay()
    set_settings(splash_show_on_tinyppi=False)


def dashboard_tests():
    section("dashboard")
    set_settings(web_allow_control=False)
    time.sleep(1.0)
    hello = jget("/api/hello")[1]
    check("web_allow_control off: no control, no shelves, writes refused",
          hello["control"] is False and hello["library"] is False and post("/api/command", {"action": "mute"}) == 403
          and jget("/api/library")[0] == 403, hello, settings=["web_allow_control"])
    set_settings(web_allow_control=True)
    time.sleep(1.0)
    check("web_allow_control on: writes accepted", post("/api/command", {"action": "mute"}) == 200, settings=["web_allow_control"])
    post("/api/command", {"action": "mute"})
    for setting, route, flag in (("web_library", "/api/library", "library"), ("web_series", "/api/series", "series")):
        set_settings(**{setting: False})
        time.sleep(1.0)
        off = (jget("/api/hello")[1][flag], jget(route)[0])
        set_settings(**{setting: True})
        time.sleep(1.0)
        on = (jget("/api/hello")[1][flag], jget(route)[0])
        check(f"{setting} hides and shows its shelf", off == (False, 403) and on == (True, 200), (off, on), settings=[setting])
    set_settings(web_auth_read=True)
    time.sleep(1.0)
    off = (jget("/api/state")[0], jget("/api/state", TOKEN)[0])
    set_settings(web_auth_read=False)
    time.sleep(1.0)
    check("web_auth_read asks for the token to read", off == (401, 200) and jget("/api/state")[0] == 200, off,
          settings=["web_auth_read"])
    state = jget("/api/state")[1]
    check("web_metadata: snapshot carries the metadata list", "metadata" in state, list(state)[:5], settings=["web_metadata"])

    set_settings(web_token="NEWTOKEN")
    ok = wait(lambda: post("/api/command", {"action": "mute"}, token="NEWTOKEN") == 200, 10)
    post("/api/command", {"action": "mute"}, token="NEWTOKEN")
    check("web_token: a typed token replaces the old one", ok and post("/api/command", {"action": "mute"}, token=TOKEN) == 401,
          settings=["web_token"])
    before = kodi.get_settings("web_token")["web_token"]
    kodi.rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi", "params": ["web_token"]})
    new = wait(lambda: (lambda t: t if t != before else None)(kodi.get_settings("web_token")["web_token"]), 10)
    time.sleep(1.5)
    label = kodi.rpc("XBMC.GetInfoLabels", {"labels": ["Control.GetLabel(9)", "System.CurrentWindow"]})["result"]
    kodi.shot("web-token-new")
    kodi.rpc("Input.Back")
    time.sleep(1.0)
    good = new and len(new) == 8 and set(new) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    accepted = wait(lambda: post("/api/command", {"action": "mute"}, token=new) == 200, 10) if good else False
    post("/api/command", {"action": "mute"}, token=new)
    check("web_token_new: generates a fresh 8-character token the server takes", good and accepted
          and post("/api/command", {"action": "mute"}, token="NEWTOKEN") == 401, (before, new, label), settings=["web_token_new"])
    kodi.rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi", "params": ["web_info"]})
    time.sleep(2.5)
    text = kodi.rpc("XBMC.GetInfoLabels", {"labels": ["Control.GetLabel(5)"]})["result"]["Control.GetLabel(5)"]
    kodi.shot("web-info")
    kodi.rpc("Input.Back")
    time.sleep(1.0)
    check("web_info: shows the address and the current token", ":8099/" in text and new in text, text[:160],
          settings=["web_info"])
    set_settings(web_token=TOKEN)
    wait(lambda: post("/api/command", {"action": "mute"}) == 200, 10)
    post("/api/command", {"action": "mute"})

    set_settings(web_port=8123)
    moved = wait(lambda: port_open(8123) and not port_open(8099), 10)
    set_settings(web_port=8099)
    back = wait(lambda: port_open(8099) and not port_open(8123), 10)
    check("web_port moves the dashboard to the new port and back", moved and back, (moved, back), settings=["web_port"])
    set_settings(web_enabled=False)
    off = wait(lambda: not port_open(8099), 10)
    set_settings(web_enabled=True)
    on = wait(lambda: port_open(8099), 10)
    check("web_enabled switches the dashboard off and on", off and on, (off, on), settings=["web_enabled"])


def main():
    kodi.require_coreelec_marker()
    if ONLY and ONLY != ["splash"]:
        raise SystemExit("usage: run_settings.py [splash]")
    k = kodi.Kodi(kodi.make_home("settings"))
    print(f"Kodi answered after {k.start():.1f} s", flush=True)
    try:
        if not kodi.start_tinyppi(k):
            raise RuntimeError("TinyPPI did not start")
        set_settings(**BASE)
        if ONLY == ["splash"]:
            splash_tests()
        else:
            kodi.play(HDR)
            theme_tests()
            general_tests()
            channels("hdr")
            dialog_tests()
            kodi.stop()
            kodi.play(SDR)
            sdr_overlay_tests()
            splash_tests()
            dashboard_tests()
            kodi.stop()
    except Exception:
        check("the run finished without an exception in the harness", False, traceback.format_exc())
    finally:
        k.quit()
        k.stop_display()
    print(f"{len(REPORT.settings)} settings exercised live", flush=True)
    sys.exit(REPORT.finish())


if __name__ == "__main__":
    main()
