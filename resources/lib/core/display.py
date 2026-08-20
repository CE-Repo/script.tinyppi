"""Display reset for Dolby Vision output switches.

Kodi re-applies the display mode whenever the played stream's HDR type changes:
``CWinSystemAmlogicGLESContext::CreateNewWindow`` compares the new type against
the old one and, when they differ, forces a mode switch.  That forced switch is
what makes the HDMI output re-negotiate, and it is why a stream that starts as
Dolby Vision reaches the TV as Dolby Vision.

A VS10 output switch made while a stream is already playing never goes through
that path.  Neither the sysfs writes nor the native ``vs10.*`` actions tell Kodi
anything, so the Dolby Vision driver starts sending a different output format
while the HDMI output is still set up for the previous one -- the TV then never
switches to Dolby Vision and the picture comes out with the wrong colours, most
visibly in Player-LED mode.

Since kernel 5.15 the display mode can no longer be set through
``/sys/class/display/mode``; Amlogic disabled that and it now takes a DRM atomic
commit, which only the DRM master may perform.  Kodi is that master -- and
add-ons run inside the Kodi process, so its own DRM file descriptor is reachable
from here.  This module uses it for the one step Kodi's own forced mode switch
falls back to when the mode string itself does not change: setting the Amlogic
``UPDATE`` connector property, which makes the driver re-apply the current
output (``CAMLDRMUtils::aml_set_drmDevice_mode``).

Everything here is best effort.  A kernel without the property, a Kodi build
that does not use DRM, a descriptor that is not the master -- each just means no
reset, never a failed mode switch.
"""

import ctypes
import os

import xbmc

try:
    import fcntl
except ImportError:  # Not Linux (a dev box); every call below then no-ops.
    fcntl = None

# --- DRM ioctl plumbing ----------------------------------------------------
#
# Only the four calls libdrm would make for
# ``drmModeObjectSetProperty(fd, connector, "UPDATE", 1)``: list the connectors,
# ask one for its type and connection state, list its properties, set one.

_DRM_IOCTL_BASE = ord("d")

_DRM_MODE_OBJECT_CONNECTOR = 0xC0C0C0C0
_DRM_MODE_DISCONNECTED = 2
# HDMI-A and HDMI-B, the only connector types Dolby Vision can come out of.
_DRM_MODE_CONNECTOR_HDMI = (11, 12)

_UPDATE_PROPERTY = b"UPDATE"

# Length of drm_mode_modeinfo, allocated only so the kernel has somewhere to
# put a mode should it ever copy one; see _get_connector for why it must not
# be asked for zero modes.
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

# Connector and property id of the UPDATE property, once found.  Both are
# device-global and stable for as long as Kodi runs, so the scan happens once;
# None means "not probed yet", False means "probed, not available here".
_target: tuple[int, int] | None | bool = None


def _ioctl(fd: int, request: int, payload) -> bool:
    """Run one DRM ioctl on ``fd``, returning whether it succeeded."""
    if fcntl is None:
        return False
    try:
        fcntl.ioctl(fd, request, payload, True)
        return True
    except (OSError, OverflowError, ValueError):
        # OSError is the ordinary "this kernel/descriptor won't do that"; the
        # other two guard against a Python that refuses the request number.
        return False


def _drm_fds() -> list[int]:
    """Return the process' open descriptors for a DRM card node.

    Kodi opens ``/dev/dri/cardN`` and becomes its master; that descriptor lives
    in this very process, so it is reachable through ``/proc/self/fd``.  Read
    fresh every time -- a cached number could point at some unrelated file by
    the time it is used.
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
            # The descriptor list is a snapshot; entries can already be gone.
            continue
        if target.startswith("/dev/dri/card"):
            try:
                found.append(int(entry))
            except ValueError:
                continue
    return found


def _connector_ids(fd: int) -> list[int]:
    """Return the ids of every connector the DRM device exposes."""
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

    ``count_modes`` is deliberately non-zero: the kernel takes a zero there as
    a request to re-probe the connector, which re-reads the EDID and is not
    something to do behind Kodi's back mid-playback.  One mode's worth of room
    is passed along for the rare display that has exactly one, in which case
    the kernel does copy it.
    """
    modes = (ctypes.c_uint8 * _MODEINFO_SIZE)()
    conn = _GetConnector(
        connector_id=connector_id,
        modes_ptr=ctypes.cast(modes, ctypes.c_void_p).value,
        count_modes=1,
    )
    return conn if _ioctl(fd, _IOCTL_GETCONNECTOR, conn) else None


def _property_id(fd: int, connector_id: int, name: bytes) -> int | None:
    """Return the id of the named property on ``connector_id``, or None."""
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
        # Matched without regard to case, as Kodi's own set_drmProp does.
        if _ioctl(fd, _IOCTL_GETPROPERTY, prop) and prop.name.upper() == name:
            return prop_id
    return None


def _find_update_property(fd: int) -> tuple[int, int] | None:
    """Return ``(connector_id, prop_id)`` of the output to reset, or None.

    The HDMI connector is what Dolby Vision leaves the box through, so it wins;
    anything else carrying the property is kept as a fallback rather than
    dropped.  A connector reporting UNKNOWN is not skipped -- Kodi itself forces
    its connector to connected for a mode switch -- but a disconnected one is:
    there is no output to re-apply.
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

    Returns whether the reset was actually performed.  A first call scans for
    the ``UPDATE`` connector property and remembers the answer, including a
    negative one, so a kernel without it costs nothing from then on.
    """
    global _target

    if _target is False:
        return False

    note = f" ({reason})" if reason else ""

    for fd in _drm_fds():
        target = _target if isinstance(_target, tuple) else _find_update_property(fd)
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
            # Only a descriptor that is the DRM master gets this far, so cache
            # the ids now: they are what the next reset needs.
            _target = target
            xbmc.log(f"TinyPPI: display reset{note}", xbmc.LOGINFO)
            return True

        # Not the master (Kodi may hold more than one descriptor) -- try the
        # next one rather than giving up on the whole device.

    _target = False
    xbmc.log(
        f"TinyPPI: display reset{note} not available -- no DRM connector with "
        "an UPDATE property could be driven from this process",
        xbmc.LOGWARNING,
    )
    return False
