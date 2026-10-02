# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Collect PASS/FAIL lines of a test run and write them to config.RESULTS."""

import json
import os

import config


class Report:
    def __init__(self, name):
        self.name = name
        self.results = []
        self.settings = set()

    def section(self, title):
        print(f"\n=== {title} ===", flush=True)

    def check(self, name, ok, detail="", settings=()):
        self.settings.update(settings)
        self.results.append({"test": name, "ok": bool(ok), "detail": str(detail)[:600]})
        print(("PASS " if ok else "FAIL ") + name + (f"  -- {detail}" if detail else ""), flush=True)
        return ok

    def skip(self, name, reason):
        """Note a check that cannot run here; it counts neither way."""
        print(f"SKIP {name}  -- {reason}", flush=True)

    def finish(self):
        """Write the results, print the tally and return the exit code."""
        os.makedirs(config.RESULTS, exist_ok=True)
        with open(os.path.join(config.RESULTS, f"{self.name}.json"), "w", encoding="utf-8") as handle:
            json.dump({"results": self.results, "settings": sorted(self.settings)}, handle, indent=1)
        passed = sum(r["ok"] for r in self.results)
        print(f"\n{self.name}: {passed}/{len(self.results)} passed", flush=True)
        return 0 if self.results and passed == len(self.results) else 1
