# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Run the add-on's code outside Kodi: the stubs stand in for Kodi's modules.

The Kodi 22 integration suite in ``tests/kodi`` drives a real Kodi and is
run on its own (see tests/README.md), never collected here.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.join(ROOT, "resources", "lib")]

collect_ignore = ["kodi"]


@pytest.fixture(autouse=True)
def kodi_state():
    """Give every test fresh settings, properties, InfoLabels and log."""
    import xbmc
    import xbmcaddon
    import xbmcgui
    xbmcaddon.SETTINGS.clear()
    xbmcgui.PROPERTIES.clear()
    xbmc.INFO.clear()
    xbmc.CONDITIONS.clear()
    xbmc.LOG.clear()
    xbmc.BUILTINS.clear()
    xbmc.RPC = None
    yield
