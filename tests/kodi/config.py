# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Where the Kodi 22 test suite keeps Kodi, its profiles, media and results.

Everything lives under ``KODI_TEST_ROOT`` (default ``/opt/kodi-test``);
nothing is written into the checkout.
"""

import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.environ.get("KODI_TEST_ROOT", "/opt/kodi-test")
KODI_BIN = os.environ.get("KODI_BIN", "/opt/kodi/bin/kodi")
DISPLAY = os.environ.get("KODI_TEST_DISPLAY", ":99")

MEDIA = os.path.join(ROOT, "media")
SHOTS = os.path.join(ROOT, "shots")
RESULTS = os.path.join(ROOT, "results")
TEMPLATE = os.path.join(ROOT, "home-template")
HOMES = os.path.join(ROOT, "homes")
HELPER_OUT = os.path.join(ROOT, "helper-out.json")

# The original code for the scan comparison (optional), e.g. "main".
BASELINE_REF = os.environ.get("BASELINE_REF", "")

SIDEDATA_URL = "https://github.com/matthane/script.module.sidedata.git"

JSONRPC_PORT = 8080
DASHBOARD_PORT = 8099
TOKEN = "TESTTK23"

# Media the tests play.
HDR10_CLIP = os.path.join(MEDIA, "src", "hdr10.mkv")
GRAY_HDR10 = os.path.join(MEDIA, "src", "gray_hdr10.mkv")
GRAY_SDR = os.path.join(MEDIA, "src", "gray_sdr.mp4")
