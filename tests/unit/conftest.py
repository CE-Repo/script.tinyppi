# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Fixtures shared by the unit tests."""

import pytest

from dashboard_server import serve
from web import mdblist


@pytest.fixture(autouse=True)
def no_chart(monkeypatch):
    """The IMDb Top 250 is never asked for over the network: it stays out,
    and the library's place stands (test_mdblist asks for it of its own)."""
    monkeypatch.setattr(mdblist._CHART, "_start", lambda work: None)
    monkeypatch.setattr(mdblist._CHART, "_places", {})
    monkeypatch.setattr(mdblist._CHART, "_until", 0.0)
    monkeypatch.setattr(mdblist._CHART, "_asking", False)


@pytest.fixture
def dashboard():
    """A running dashboard server with nothing playing."""
    srv, close = serve()
    yield srv
    close()
