# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Display reset for Dolby Vision output switches.

Kodi forces a display mode switch when the stream's HDR type changes
(``CWinSystemAmlogicGLESContext::CreateNewWindow``); that switch makes the
HDMI output renegotiate.  A VS10 switch during playback bypasses it: neither
the sysfs writes nor the ``vs10.*`` actions tell Kodi, so the driver sends a
new output format over a link set up for the old one.  The TV then stays out
of Dolby Vision and colours are wrong, most visibly in Player-LED mode.

Since kernel 5.15 the mode can only be changed by a DRM atomic commit from
the DRM master, which is Kodi.  Add-ons run inside Kodi's process, so its DRM
descriptor is reachable here.  This module sets the Amlogic ``UPDATE``
connector property, the same step Kodi uses when the mode string does not
change (``CAMLDRMUtils::aml_set_drmDevice_mode``), which re-applies the
current output.

Best effort only: without the property, without DRM, or without the master
descriptor there is simply no reset; the mode switch itself never fails.
"""

import ctypes
import os

import xbmc

from core.log import log

try:
    import fcntl
except ImportError:  # not Linux (a dev box): every call below is a no-op
    fcntl = None

# --- DRM ioctl plumbing ----------------------------------------------------
#
# The four calls libdrm makes for
# ``drmModeObjectSetProperty(fd, connector, "UPDATE", 1)``: list connectors,
# get a connector's type and state, list its properties, set one.

_DRM_IOCTL_BASE = ord("d")

_DRM_MODE_OBJECT_CONNECTOR = 0xC0C0C0C0
_DRM_MODE_DISCONNECTED = 2
# HDMI-A and HDMI-B, the only connectors Dolby Vision can leave through.
_DRM_MODE_CONNECTOR_HDMI = (11, 12)

_UPDATE_PROPERTY = b"UPDATE"

# Size of drm_mode_modeinfo: room for the one mode the kernel may copy (see
# _get_connector for why zero modes must not be requested).
_MODEINFO_SIZE = 68


def _iowr(nr: int, size: int) -> int:
    """Build an ``_IOWR('d', nr, size)`` request number."""
    return (3 << 30) | (size << 16) | (_DRM_IOCTL_BASE << 8) | nr


class _CardRes(ctypes.Structure):
    _fields_ = [
        ("fb_id_ptr", ctypes.c_uint64),
        ("crtc_id_ptr", ctypes.c_uint64),
        ("connector_id_ptr", ctypes.c_uint64),
        ("encoder_id_ptr", ctypes.c_uint64),
        ("count_fbs", ctypes.c_uint32),
        ("count_crtcs", ctypes.c_uint32),
        ("count_connectors", ctypes.c_uint32),
        ("count_encoders", ctypes.c_uint32),
        ("min_width", ctypes.c_uint32),
        ("max_width", ctypes.c_uint32),
        ("min_height", ctypes.c_uint32),
        ("max_height", ctypes.c_uint32),
    ]


class _GetConnector(ctypes.Structure):
    _fields_ = [
        ("encoders_ptr", ctypes.c_uint64),
        ("modes_ptr", ctypes.c_uint64),
        ("props_ptr", ctypes.c_uint64),
        ("prop_values_ptr", ctypes.c_uint64),
        ("count_modes", ctypes.c_uint32),
        ("count_props", ctypes.c_uint32),
        ("count_encoders", ctypes.c_uint32),
        ("encoder_id", ctypes.c_uint32),
        ("connector_id", ctypes.c_uint32),
        ("connector_type", ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection", ctypes.c_uint32),
        ("mm_width", ctypes.c_uint32),
        ("mm_height", ctypes.c_uint32),
        ("subpixel", ctypes.c_uint32),
        ("pad", ctypes.c_uint32),
    ]


class _ObjGetProperties(ctypes.Structure):
    _fields_ = [
        ("props_ptr", ctypes.c_uint64),
        ("prop_values_ptr", ctypes.c_uint64),
        ("count_props", ctypes.c_uint32),
        ("obj_id", ctypes.c_uint32),
        ("obj_type", ctypes.c_uint32),
    ]


class _GetProperty(ctypes.Structure):
    _fields_ = [
        ("values_ptr", ctypes.c_uint64),
        ("enum_blob_ptr", ctypes.c_uint64),
        ("prop_id", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("name", ctypes.c_char * 32),
        ("count_values", ctypes.c_uint32),
        ("count_enum_blobs", ctypes.c_uint32),
    ]


class _ObjSetProperty(ctypes.Structure):
    _fields_ = [
        ("value", ctypes.c_uint64),
        ("prop_id", ctypes.c_uint32),
        ("obj_id", ctypes.c_uint32),
        ("obj_type", ctypes.c_uint32),
    ]


_IOCTL_GETRESOURCES     = _iowr(0xA0, ctypes.sizeof(_CardRes))
_IOCTL_GETCONNECTOR     = _iowr(0xA7, ctypes.sizeof(_GetConnector))
_IOCTL_GETPROPERTY      = _iowr(0xAA, ctypes.sizeof(_GetProperty))
_IOCTL_OBJ_GETPROPERTIES = _iowr(0xB9, ctypes.sizeof(_ObjGetProperties))
_IOCTL_OBJ_SETPROPERTY  = _iowr(0xBA, ctypes.sizeof(_ObjSetProperty))

class _Target:
    """Connector and property id of UPDATE once found.

    Both are stable while Kodi runs, so the scan happens once.  ``ids`` is
    None while not probed yet and False when unavailable.
    """

    __slots__ = ("ids",)

    def __init__(self) -> None:
        self.ids: tuple[int, int] | None | bool = None


_target = _Target()


def _ioctl(fd: int, request: int, payload) -> bool:
    """Run one DRM ioctl on *fd* and return whether it succeeded."""
    if fcntl is None:
        return False
    try:
        fcntl.ioctl(fd, request, payload, True)
        return True
    except (OSError, OverflowError, ValueError):
        # OSError: unsupported by this kernel or descriptor.  The other two:
        # Python refusing the request number.
        return False


def _drm_fds() -> list[int]:
    """Return this process's open descriptors for DRM card nodes.

    Kodi opens ``/dev/dri/cardN`` as master in this same process, so the
    descriptor is visible in ``/proc/self/fd``.  Read fresh each time: a
    cached number could refer to another file by then.
    """
    found = []
    try:
        entries = os.listdir("/proc/self/fd")
    except OSError:
        return found

    for entry in entries:
        try:
            target = os.readlink(f"/proc/self/fd/{entry}")
        except OSError:
            # The listing is a snapshot; the descriptor may be gone.
            continue
        if target.startswith("/dev/dri/card"):
            try:
                found.append(int(entry))
            except ValueError:
                continue
    return found


def _connector_ids(fd: int) -> list[int]:
    """Return the ids of all connectors of the DRM device."""
    res = _CardRes()
    if not _ioctl(fd, _IOCTL_GETRESOURCES, res) or not res.count_connectors:
        return []

    count = res.count_connectors
    ids = (ctypes.c_uint32 * count)()
    res = _CardRes(
        connector_id_ptr=ctypes.cast(ids, ctypes.c_void_p).value,
        count_connectors=count,
    )
    if not _ioctl(fd, _IOCTL_GETRESOURCES, res):
        return []

    return list(ids)[: min(count, res.count_connectors)]


def _get_connector(fd: int, connector_id: int) -> _GetConnector | None:
    """Return the connector's type and connection state, or None.

    ``count_modes`` is deliberately non-zero: zero makes the kernel re-probe
    the connector and re-read the EDID, which must not happen behind Kodi's
    back during playback.  Room for one mode is passed in case the display
    has exactly one and the kernel copies it.
    """
    modes = (ctypes.c_uint8 * _MODEINFO_SIZE)()
    conn = _GetConnector(
        connector_id=connector_id,
        modes_ptr=ctypes.cast(modes, ctypes.c_void_p).value,
        count_modes=1,
    )
    return conn if _ioctl(fd, _IOCTL_GETCONNECTOR, conn) else None


def _property_id(fd: int, connector_id: int, name: bytes) -> int | None:
    """Return the id of property *name* on *connector_id*, or None."""
    props = _ObjGetProperties(
        obj_id=connector_id, obj_type=_DRM_MODE_OBJECT_CONNECTOR
    )
    if not _ioctl(fd, _IOCTL_OBJ_GETPROPERTIES, props) or not props.count_props:
        return None

    count = props.count_props
    prop_ids = (ctypes.c_uint32 * count)()
    values = (ctypes.c_uint64 * count)()
    props = _ObjGetProperties(
        props_ptr=ctypes.cast(prop_ids, ctypes.c_void_p).value,
        prop_values_ptr=ctypes.cast(values, ctypes.c_void_p).value,
        count_props=count,
        obj_id=connector_id,
        obj_type=_DRM_MODE_OBJECT_CONNECTOR,
    )
    if not _ioctl(fd, _IOCTL_OBJ_GETPROPERTIES, props):
        return None

    for prop_id in list(prop_ids)[: min(count, props.count_props)]:
        prop = _GetProperty(prop_id=prop_id)
        # Case-insensitive, like Kodi's own set_drmProp.
        if _ioctl(fd, _IOCTL_GETPROPERTY, prop) and prop.name.upper() == name:
            return prop_id
    return None


def _find_update_property(fd: int) -> tuple[int, int] | None:
    """Return ``(connector_id, prop_id)`` of the output to reset, or None.

    HDMI is preferred, since Dolby Vision leaves through it; another
    connector with the property is the fallback.  Connectors reporting
    UNKNOWN are kept (Kodi forces its connector to connected for a mode
    switch), disconnected ones are skipped.
    """
    fallback = None
    for connector_id in _connector_ids(fd):
        conn = _get_connector(fd, connector_id)
        if conn is None or conn.connection == _DRM_MODE_DISCONNECTED:
            continue

        prop_id = _property_id(fd, connector_id, _UPDATE_PROPERTY)
        if prop_id is None:
            continue
        if conn.connector_type in _DRM_MODE_CONNECTOR_HDMI:
            return connector_id, prop_id
        if fallback is None:
            fallback = (connector_id, prop_id)

    return fallback


def reset(reason: str = "") -> bool:
    """Ask the display driver to re-apply the current output.

    Returns whether the reset was performed.  The first call looks for the
    ``UPDATE`` property and caches the result, including a negative one, so
    a kernel without it costs nothing afterwards.
    """
    if _target.ids is False:
        return False

    note = f" ({reason})" if reason else ""

    for fd in _drm_fds():
        target = (_target.ids if isinstance(_target.ids, tuple)
                  else _find_update_property(fd))
        if target is None:
            continue

        connector_id, prop_id = target
        request = _ObjSetProperty(
            value=1,
            prop_id=prop_id,
            obj_id=connector_id,
            obj_type=_DRM_MODE_OBJECT_CONNECTOR,
        )
        if _ioctl(fd, _IOCTL_OBJ_SETPROPERTY, request):
            # Only the DRM master's descriptor gets here; cache its ids.
            _target.ids = target
            log(f"display reset{note}", xbmc.LOGINFO)
            return True

        # Not the master (Kodi may hold several descriptors): try the next.

    _target.ids = False
    log(
        f"display reset{note} not available -- no DRM connector with "
        "an UPDATE property could be driven from this process",
        xbmc.LOGWARNING,
    )
    return False
