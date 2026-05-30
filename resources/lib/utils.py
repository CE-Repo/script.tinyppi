"""
utils.py – Generic Kodi API wrappers used throughout TinyPPI.
"""

import xbmc


def _cond(condition: str) -> bool:
    """Return True when the given Kodi condition string is satisfied."""
    return xbmc.getCondVisibility(condition)


def _info(label: str) -> str:
    """Return the current value of a Kodi InfoLabel (never None)."""
    return xbmc.getInfoLabel(label)


def _clean(val) -> str:
    """Strip commas that Kodi inserts as thousands separators."""
    if val is None:
        return ""
    return str(val).replace(",", "")
