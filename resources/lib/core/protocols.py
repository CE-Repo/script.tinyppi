# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Structural types for the objects the add-on passes around."""

from typing import Protocol


class PropertyTarget(Protocol):
    """Holds string properties: a Kodi window, or ``web.snapshot.PropertySink``."""

    def getProperty(self, key: str) -> str: ...

    def setProperty(self, key: str, value: str) -> None: ...

    def clearProperty(self, key: str) -> None: ...
