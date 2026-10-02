#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn
#
# The whole Kodi 22 suite: media, profile template, then every run.  Exits
# non-zero when any check failed.  See tests/README.md.
set -u
cd "$(dirname "$0")"
PYTHON=${PYTHON:-python3}

if [ ! -d /etc/coreelec ]; then
  echo "/etc/coreelec is missing: create it on the (throwaway) test machine," >&2
  echo "e.g. 'sudo mkdir /etc/coreelec', so TinyPPI treats Kodi as CoreELEC." >&2
  exit 2
fi
"$PYTHON" setup_media.py || exit 2
"$PYTHON" setup_profiles.py || exit 2

status=0
for run in run_scan.py run_functional.py run_settings.py run_settings_dialog.py; do
  echo
  echo "##### $run"
  "$PYTHON" "$run" || status=1
done
echo
if [ "$status" -eq 0 ]; then echo "all Kodi 22 runs passed"; else echo "some Kodi 22 runs FAILED"; fi
exit "$status"
