# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The display reset over DRM (core/display.py), against a simulated device."""

import ctypes
import importlib.util
import sys
import types

import pytest

import xbmc
from core import display

HDMI_A, COMPOSITE = 11, 5
CONNECTED, DISCONNECTED = 1, 2


class FakeDrm:
    """Answer the DRM ioctls the way the kernel fills the structures.

    *connectors* maps id -> (type, connection, {property id: name});
    *master* is the descriptor allowed to set properties.  ``refuse`` maps a
    request to the numbers (1-based) of its calls that fail, as a kernel
    refusing it would.
    """

    def __init__(self, connectors, master=7):
        self.connectors = connectors
        self.master = master
        self.calls = []
        self.updates = []
        self.refuse = {}

    def ioctl(self, fd, request, payload):
        self.calls.append(request)
        if self.calls.count(request) in self.refuse.get(request, ()):
            return False
        if request == display._IOCTL_GETRESOURCES:
            ids = list(self.connectors)
            if payload.connector_id_ptr:
                room = (ctypes.c_uint32 * payload.count_connectors).from_address(
                    payload.connector_id_ptr)
                for index, connector_id in enumerate(ids[:payload.count_connectors]):
                    room[index] = connector_id
            payload.count_connectors = len(ids)
        elif request == display._IOCTL_GETCONNECTOR:
            assert payload.count_modes, "zero modes would re-probe the display"
            kind, connection, _props = self.connectors[payload.connector_id]
            payload.connector_type, payload.connection = kind, connection
        elif request == display._IOCTL_OBJ_GETPROPERTIES:
            props = list(self.connectors[payload.obj_id][2])
            if payload.props_ptr:
                room = (ctypes.c_uint32 * payload.count_props).from_address(payload.props_ptr)
                for index, prop_id in enumerate(props[:payload.count_props]):
                    room[index] = prop_id
            payload.count_props = len(props)
        elif request == display._IOCTL_GETPROPERTY:
            names = {prop_id: name for _kind, _conn, props in self.connectors.values()
                     for prop_id, name in props.items()}
            payload.name = names[payload.prop_id]
        elif request == display._IOCTL_OBJ_SETPROPERTY:
            if fd != self.master:
                return False
            self.updates.append((payload.obj_id, payload.prop_id, payload.value))
        else:
            raise AssertionError(f"unexpected ioctl {request:#x}")
        return True


@pytest.fixture
def drm(monkeypatch):
    """Install a FakeDrm built from the given connectors, on descriptors 5 and 7."""
    def install(connectors, fds=(5, 7)):
        fake = FakeDrm(connectors)
        monkeypatch.setattr(display, "_ioctl", fake.ioctl)
        monkeypatch.setattr(display, "_drm_fds", lambda: list(fds))
        monkeypatch.setattr(display, "_target", display._Target())
        return fake
    return install


def test_the_ioctl_numbers_match_the_kernel():
    assert display._IOCTL_GETRESOURCES == 0xC04064A0
    assert display._IOCTL_GETCONNECTOR == 0xC05064A7
    assert display._IOCTL_GETPROPERTY == 0xC04064AA
    assert display._IOCTL_OBJ_GETPROPERTIES == 0xC02064B9
    assert display._IOCTL_OBJ_SETPROPERTY == 0xC01864BA


def test_hdmi_is_reset_through_the_master_descriptor(drm):
    fake = drm({
        31: (COMPOSITE, CONNECTED, {40: b"UPDATE"}),
        32: (HDMI_A, CONNECTED, {41: b"CRTC_ID", 42: b"update"}),
    })
    assert display.reset("VS10 switch")
    assert fake.updates == [(32, 42, 1)]
    # The ids are kept: the next reset goes straight to the property.
    fake.calls.clear()
    assert display.reset()
    assert fake.calls == [display._IOCTL_OBJ_SETPROPERTY] * 2  # fd 5 refused, fd 7 set


def test_another_connector_is_the_fallback(drm):
    fake = drm({
        31: (HDMI_A, DISCONNECTED, {40: b"UPDATE"}),
        32: (COMPOSITE, CONNECTED, {41: b"UPDATE"}),
    })
    assert display.reset()
    assert fake.updates == [(32, 41, 1)]


def test_without_the_property_there_is_no_reset_and_no_second_try(drm):
    fake = drm({32: (HDMI_A, CONNECTED, {41: b"CRTC_ID"})})
    assert not display.reset()
    fake.calls.clear()
    assert not display.reset()
    assert fake.calls == []


def test_without_drm_there_is_no_reset(drm):
    drm({}, fds=())
    assert not display.reset()


def test_the_ioctl_wrapper_never_raises(monkeypatch):
    class Refusing:
        @staticmethod
        def ioctl(*_args):
            raise OSError("not supported")
    monkeypatch.setattr(display, "fcntl", Refusing)
    assert not display._ioctl(3, display._IOCTL_GETRESOURCES, display._CardRes())
    monkeypatch.setattr(display, "fcntl", None)
    assert not display._ioctl(3, display._IOCTL_GETRESOURCES, display._CardRes())


def test_a_successful_ioctl_passes_the_structure_for_the_kernel_to_fill(monkeypatch):
    seen = []
    monkeypatch.setattr(display, "fcntl", types.SimpleNamespace(
        ioctl=lambda *args: seen.append(args)))
    payload = display._CardRes()
    assert display._ioctl(3, display._IOCTL_GETRESOURCES, payload) is True
    assert seen == [(3, display._IOCTL_GETRESOURCES, payload, True)]


def test_without_fcntl_the_module_still_loads_and_does_nothing(monkeypatch):
    # A dev box without fcntl: load a second copy of the module, leaving core.display alone.
    monkeypatch.setitem(sys.modules, "fcntl", None)
    spec = importlib.util.spec_from_file_location("display_without_fcntl", display.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.fcntl is None
    assert module._ioctl(3, module._IOCTL_GETRESOURCES, module._CardRes()) is False
    assert display.fcntl is not None


def test_only_card_nodes_open_in_this_process_count(monkeypatch):
    links = {"0": "/dev/pts/0", "3": "/dev/dri/card0", "5": "/dev/dri/renderD128",
             "9": "/dev/dri/card1", "self": "/dev/dri/card2"}

    def readlink(path):
        entry = path.rsplit("/", 1)[1]
        if entry not in links:
            raise FileNotFoundError(path)       # closed since the listing
        return links[entry]
    monkeypatch.setattr(display, "os", types.SimpleNamespace(
        listdir=lambda _path: ["0", "3", "4", "5", "9", "self"], readlink=readlink))
    assert display._drm_fds() == [3, 9]


def test_no_descriptors_when_proc_is_unreadable(monkeypatch):
    def refused(path):
        raise PermissionError(path)
    monkeypatch.setattr(display, "os", types.SimpleNamespace(listdir=refused))
    assert display._drm_fds() == []


@pytest.mark.parametrize("refused", [{1}, {2}])
def test_a_device_that_will_not_list_its_connectors_is_not_reset(drm, refused):
    fake = drm({32: (HDMI_A, CONNECTED, {42: b"UPDATE"})}, fds=(7,))
    fake.refuse = {display._IOCTL_GETRESOURCES: refused}
    assert display._connector_ids(7) == []
    fake.calls.clear()
    assert not display.reset()
    assert fake.updates == []


def test_a_device_without_connectors_is_not_reset(drm):
    fake = drm({}, fds=(7,))
    assert display._connector_ids(7) == []
    assert not display.reset("VS10 switch")
    assert fake.updates == []
    assert xbmc.LOG == [(xbmc.LOGWARNING,
                         "TinyPPI: display reset (VS10 switch) not available -- no DRM connector "
                         "with an UPDATE property could be driven from this process")]


@pytest.mark.parametrize("refused", [{1}, {2}])
def test_a_connector_whose_properties_cannot_be_listed_is_skipped(drm, refused):
    fake = drm({32: (HDMI_A, CONNECTED, {42: b"UPDATE"})}, fds=(7,))
    fake.refuse = {display._IOCTL_OBJ_GETPROPERTIES: refused}
    assert display._property_id(7, 32, b"UPDATE") is None


def test_a_connector_without_properties_has_no_update(drm):
    drm({32: (HDMI_A, CONNECTED, {})}, fds=(7,))
    assert display._property_id(7, 32, b"UPDATE") is None


def test_unreadable_connectors_and_properties_are_passed_over(drm):
    fake = drm({
        31: (HDMI_A, CONNECTED, {40: b"UPDATE"}),
        32: (HDMI_A, CONNECTED, {41: b"UPDATE", 42: b"UPDATE"}),
    }, fds=(7,))
    fake.refuse = {display._IOCTL_GETCONNECTOR: {1},      # connector 31
                   display._IOCTL_GETPROPERTY: {1}}       # property 41
    assert display.reset()
    assert fake.updates == [(32, 42, 1)]


def test_the_first_of_several_other_connectors_is_the_fallback(drm):
    fake = drm({
        31: (COMPOSITE, CONNECTED, {40: b"UPDATE"}),
        32: (COMPOSITE, CONNECTED, {41: b"UPDATE"}),
    }, fds=(7,))
    assert display.reset("test")
    assert fake.updates == [(31, 40, 1)]
    assert xbmc.LOG == [(xbmc.LOGINFO, "TinyPPI: display reset (test)")]
