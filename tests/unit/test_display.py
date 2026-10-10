# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The display reset over DRM (core/display.py), against a simulated device."""

import ctypes

import pytest

from core import display

HDMI_A, COMPOSITE = 11, 5
CONNECTED, DISCONNECTED = 1, 2


class FakeDrm:
    """Answer the DRM ioctls the way the kernel fills the structures.

    *connectors* maps id -> (type, connection, {property id: name});
    *master* is the descriptor allowed to set properties.
    """

    def __init__(self, connectors, master=7):
        self.connectors = connectors
        self.master = master
        self.calls = []
        self.updates = []

    def ioctl(self, fd, request, payload):
        self.calls.append(request)
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
