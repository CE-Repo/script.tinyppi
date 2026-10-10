# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""VS10 switching against a simulated Dolby Vision driver (core/vs10.py).

The driver's sysfs nodes are real files in a scratch folder.  The simulated
driver applies what was written whenever the code waits (``delay``), as the
real one does a moment after a write: the output mode follows dv_mode while
the policy forces an output, and the DV core runs while it sends DV.
"""

import pytest

import xbmc
import xbmcgui
from core import vs10

NODES = {
    "_POLICY": "1", "_ENABLE": "N", "_DVMODE": "0", "_LL_POLICY": "0",
    "_DV_STATUS": "0", "_DV_OUTPUT": "5",
}


class Driver:
    def __init__(self, folder):
        self.paths = {}
        for name, value in NODES.items():
            path = folder / name.strip("_").lower()
            path.write_text(value)
            self.paths[name] = path
        self.frozen = False          # a driver that ignores every write
        self.ticks = 0

    def read(self, name):
        return self.paths[name].read_text().strip()

    def set(self, name, value):
        self.paths[name].write_text(value)

    def tick(self, _ms=0):
        self.ticks += 1
        if self.frozen:
            return
        forced = self.read("_ENABLE") == "Y" and self.read("_POLICY") == "2"
        output = str((int(self.read("_DVMODE")) - 1) % 6) if forced else "5"
        self.set("_DV_OUTPUT", output)
        self.set("_DV_STATUS", "1" if output in ("0", "1") else "0")


class Kodi:
    """JSON-RPC answers for the two probes, and whether a video plays."""

    def __init__(self):
        self.native = False
        self.led = 0                 # 0 TV-LED, 1 Player-LED, None unreadable
        self.native_effect = None    # what a vs10.* action does to the driver

    def __call__(self, request):
        setting = request.get("params", {}).get("setting")
        if setting == vs10._VS10_PROBE_SETTING:
            return {"result": {"value": True}} if self.native else {"error": {"code": -32602}}
        if setting == "coreelec.amlogic.dolbyvisionled":
            return {"error": {}} if self.led is None else {"result": {"value": self.led}}
        return {"result": "OK"}


@pytest.fixture
def driver(tmp_path, monkeypatch):
    fake = Driver(tmp_path)
    for name, path in fake.paths.items():
        monkeypatch.setattr(vs10, name, str(path))
    monkeypatch.setattr(vs10, "delay", fake.tick)
    return fake


@pytest.fixture
def kodi(monkeypatch, driver):
    fake = Kodi()
    xbmc.RPC = fake
    vs10._vs10_actions_available.cache_clear()
    monkeypatch.setattr(vs10, "_is_playing_video", lambda: True)
    resets = []
    monkeypatch.setattr(vs10.display, "reset", resets.append)
    fake.resets = resets

    def builtin(command, wait=False):
        xbmc.BUILTINS.append(command)
        if fake.native_effect:
            fake.native_effect(driver)
    monkeypatch.setattr(xbmc, "executebuiltin", builtin)
    yield fake
    vs10._vs10_actions_available.cache_clear()


def writes(driver):
    """The sysfs writes in order, as (node, value) by node name."""
    by_path = {str(path): name for name, path in driver.paths.items()}
    found = []
    for _level, line in xbmc.LOG:
        if " = " in line and line.startswith("TinyPPI: /"):
            path, value = line[len("TinyPPI: "):].split(" = ", 1)
            found.append((by_path.get(path, path), value))
    return found


# --- The sysfs sequences ----------------------------------------------------

@pytest.mark.parametrize(("mode", "dvmode", "output"), [
    ("hdr10", "3", "2"), ("sdr10", "4", "3"), ("sdr8", "5", "4"),
])
def test_conversion_modes(driver, kodi, mode, dvmode, output):
    vs10.set_mode(mode)
    assert writes(driver) == [("_ENABLE", "Y"), ("_POLICY", "2"), ("_DVMODE", dvmode)]
    assert driver.read("_DV_OUTPUT") == output
    assert kodi.resets == [f"VS10 output switched to '{mode}'"]
    assert any(f"mode '{mode}' set via built-in TinyPPI VS10 (sysfs)" in line
               for _level, line in xbmc.LOG)


@pytest.mark.parametrize(("led", "dvmode", "ll_policy"), [(0, "2", "0"), (1, "1", "1"), ("0", "2", "0")])
def test_dolby_vision_follows_the_led_mode(driver, kodi, led, dvmode, ll_policy):
    kodi.led = led
    vs10.set_mode("dv")
    # Enabled before the policy forces an output.
    assert writes(driver) == [("_ENABLE", "Y"), ("_POLICY", "2"),
                              ("_LL_POLICY", ll_policy), ("_DVMODE", dvmode)]
    assert driver.read("_DV_OUTPUT") in ("0", "1")
    assert kodi.resets == ["VS10 output switched to Dolby Vision"]


def test_the_led_mode_falls_back_to_the_driver(driver, kodi):
    kodi.led = None
    driver.set("_LL_POLICY", "1")
    assert vs10._player_led_mode() is True
    driver.set("_LL_POLICY", "0")
    assert vs10._player_led_mode() is False


def test_bypass_releases_the_core_before_disabling(driver, kodi):
    vs10.set_mode("dv")
    xbmc.LOG.clear()
    kodi.resets.clear()
    vs10.set_mode("original_sdr")
    assert writes(driver) == [("_POLICY", "1"), ("_DVMODE", "0"), ("_ENABLE", "N")]
    assert driver.read("_DV_STATUS") == "0" and driver.read("_DV_OUTPUT") == "5"
    assert kodi.resets == ["VS10 output switched from Dolby Vision"]


def test_hlg_turns_vs10_off(driver, kodi):
    vs10.set_mode("hdr10")
    xbmc.LOG.clear()
    vs10.set_mode("original_hlg")
    assert writes(driver) == [("_POLICY", "1"), ("_ENABLE", "N")]


# --- Through SDR ----------------------------------------------------------------

@pytest.mark.parametrize(("start", "target", "dvmodes"), [
    ("hdr10", "dv", ["3", "4", "2"]),
    ("dv", "hdr10", ["2", "4", "3"]),
])
def test_hdr10_and_dolby_vision_go_through_sdr(driver, kodi, start, target, dvmodes):
    vs10.set_mode(start)
    vs10.set_mode(target)
    assert [value for node, value in writes(driver) if node == "_DVMODE"] == dvmodes
    assert any("going through SDR first" in line for _level, line in xbmc.LOG)


def test_other_switches_are_direct(driver, kodi):
    vs10.set_mode("sdr8")
    vs10.set_mode("dv")
    assert [value for node, value in writes(driver) if node == "_DVMODE"] == ["5", "2"]


def test_nothing_is_staged_without_a_video(driver, kodi, monkeypatch):
    vs10.set_mode("hdr10")
    monkeypatch.setattr(vs10, "_is_playing_video", lambda: False)
    kodi.resets.clear()
    vs10.set_mode("dv")
    assert [value for node, value in writes(driver) if node == "_DVMODE"] == ["3", "2"]
    assert kodi.resets == []           # the display is only reset during playback


# --- The display reset --------------------------------------------------------

def test_no_reset_when_the_driver_does_not_move(driver, kodi):
    driver.frozen = True
    vs10.set_mode("hdr10")
    assert kodi.resets == []
    assert any("did not move the driver's output mode" in line for _level, line in xbmc.LOG)


# --- Native actions ---------------------------------------------------------

def test_native_actions_are_preferred(driver, kodi):
    kodi.native = True
    kodi.native_effect = lambda drv: (drv.set("_ENABLE", "Y"), drv.set("_POLICY", "2"),
                                      drv.set("_DVMODE", "3"))
    vs10.set_mode("hdr10")
    assert xbmc.BUILTINS == ["Action(vs10.hdr10)"]
    assert writes(driver) == []
    assert kodi.resets == []           # native actions reset the display themselves


def test_a_native_action_crossing_the_dv_line_is_reset(driver, kodi):
    kodi.native = True
    kodi.native_effect = lambda drv: (drv.set("_ENABLE", "Y"), drv.set("_POLICY", "2"),
                                      drv.set("_DVMODE", "2"))
    vs10.set_mode("dv")
    assert xbmc.BUILTINS == ["Action(vs10.dv)"]
    assert kodi.resets == ["VS10 output switched to Dolby Vision"]


def test_a_native_action_without_effect_falls_back_to_sysfs(driver, kodi):
    kodi.native = True
    vs10.set_mode("sdr10")
    assert xbmc.BUILTINS == ["Action(vs10.sdr)"]
    assert writes(driver)[-1] == ("_DVMODE", "4")
    assert any("had no effect on the DV driver" in line for _level, line in xbmc.LOG)


def test_sdr8_always_uses_sysfs(driver, kodi):
    kodi.native = True
    vs10.set_mode("sdr8")
    assert xbmc.BUILTINS == []
    assert writes(driver)[-1] == ("_DVMODE", "5")


def test_native_actions_need_a_video(driver, kodi, monkeypatch):
    kodi.native = True
    monkeypatch.setattr(vs10, "_is_playing_video", lambda: False)
    vs10.set_mode("hdr10")
    assert xbmc.BUILTINS == []
    assert writes(driver)[-1] == ("_DVMODE", "3")


def test_the_probe_runs_once(driver, kodi):
    asked = []
    original = kodi.__call__
    xbmc.RPC = lambda request: (asked.append(request["method"]), original(request))[1]
    vs10.set_mode("hdr10")
    vs10.set_mode("sdr10")
    assert asked.count("Settings.GetSettingValue") == 1


# --- Failures ---------------------------------------------------------------

def test_failed_writes_are_reported(driver, kodi, tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.mkdir()                       # writing a directory fails
    monkeypatch.setattr(vs10, "_DVMODE", str(blocked))
    vs10.set_mode("hdr10")
    errors = [line for level, line in xbmc.LOG if level == xbmc.LOGERROR]
    assert any("FAILED" in line for line in errors)
    assert any("mode 'hdr10' NOT set" in line for line in errors)
    assert not any("mode 'hdr10' set via" in line for _level, line in xbmc.LOG)


def test_unknown_modes_do_nothing(driver, kodi):
    vs10.set_mode("rainbow")
    assert writes(driver) == []
    assert (xbmc.LOGERROR, "TinyPPI: Unknown mode 'rainbow'") in xbmc.LOG


def test_hybrid_grades_are_switched_with_a_warning(driver, kodi):
    home = xbmcgui.Window(10000)
    home.setProperty("TinyPPI.HdrType", "dolbyvision")
    home.setProperty(vs10.PROP_HDR10PLUS_PRESENT, "1")
    vs10.set_mode("sdr10")
    assert any("also carries HDR10+" in line for level, line in xbmc.LOG
               if level == xbmc.LOGWARNING)
    assert writes(driver)[-1] == ("_DVMODE", "4")


def test_a_broken_probe_answer(driver, kodi, monkeypatch):
    monkeypatch.setattr(xbmc, "executeJSONRPC", lambda _request: "garbage")
    assert vs10._probe_vs10_actions() is False
    assert vs10._probe_dv_Player_LED_setting() is None
    monkeypatch.setattr(xbmc, "executeJSONRPC", lambda _request: '{"result": "OK"}')
    assert vs10._probe_dv_Player_LED_setting() is None
