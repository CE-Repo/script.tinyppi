# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Fixtures shared by the unit tests."""

import pytest

from dashboard_server import serve


@pytest.fixture
def dashboard():
    """A running dashboard server with nothing playing."""
    srv, close = serve()
    yield srv
    close()
