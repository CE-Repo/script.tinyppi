# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Stand-in for Kodi's ``xbmc`` module, enough to import and drive the add-on.

Tests set ``INFO`` (InfoLabels), ``CONDITIONS`` and ``RPC`` (a function
answering JSON-RPC requests as dicts) and read ``LOG`` / ``BUILTINS``.
"""

import json
import time

import xbmcvfs

LOGDEBUG, LOGINFO, LOGWARNING, LOGERROR, LOGFATAL = 0, 1, 2, 3, 4
ISO_639_1, ISO_639_2, ENGLISH_NAME = 0, 1, 2

LOG: list[tuple[int, str]] = []
BUILTINS: list[str] = []
INFO: dict[str, str] = {}
CONDITIONS: dict[str, bool] = {}
RPC = None


def log(message, level=LOGDEBUG):
    LOG.append((level, message))


def getInfoLabel(label):
    return INFO.get(label, "")


def getCondVisibility(condition):
    return CONDITIONS.get(condition, False)


def executebuiltin(command, wait=False):
    BUILTINS.append(command)


def executeJSONRPC(request):
    answer = RPC(json.loads(request)) if RPC else {}
    return json.dumps(answer)


def sleep(milliseconds):
    time.sleep(milliseconds / 1000)


def getLocalizedString(string_id):
    return f"#{string_id}"


def getLanguage(form=ENGLISH_NAME, region=False):
    return "English"


def getSkinDir():
    return "skin.estuary"


def translatePath(path):
    return xbmcvfs.translatePath(path)


class Monitor:
    def abortRequested(self):
        return False

    def waitForAbort(self, timeout=None):
        time.sleep(timeout or 0)
        return False


class Player:
    def isPlaying(self):
        return False

    def isPlayingVideo(self):
        return False

    def getPlayingFile(self):
        raise RuntimeError("nothing is playing")


class Keyboard:
    def __init__(self, default="", heading="", hidden=False):
        self._text = default

    def doModal(self, autoclose=0):
        pass

    def isConfirmed(self):
        return False

    def getText(self):
        return self._text
