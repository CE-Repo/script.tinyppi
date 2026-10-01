# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

import pytest

import kodi_stubs

kodi_stubs.install()


@pytest.fixture(autouse=True)
def kodi():
    """A fresh, idle Kodi for every test: no properties, no settings, nothing
    logged, and special:// paths of its own."""
    kodi_stubs.reset()
    return kodi_stubs.state
