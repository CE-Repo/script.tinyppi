# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""A library scan with an open films tab: how often does the box re-read?

Kodi announces every scanned item, and each drop of the cached lists makes
an open page read them again.  The burst must end in about one drop.  With
BASELINE_REF set (e.g. ``main``), the same run on that code is shown beside.
"""

import json
import sys
import time

import config
import driver
from report import Report
from stream import Page


def scan(name, ref=None):
    home = driver.make_home(name, ref)
    with driver.Kodi(home) as kodi:
        if not driver.start_tinyppi(kodi):
            raise SystemExit("TinyPPI did not start")
        time.sleep(2)
        page = Page()
        page.start()
        time.sleep(2)
        driver.http("/api/library")
        mark = kodi.log_size()
        started = time.time()
        driver.scan_library()
        took = time.time() - started
        time.sleep(4)             # the quiet period and one producer pass
        page.stop.set()
        log = kodi.log(mark)
        films = json.loads(driver.http("/api/library")[2])["count"]
        shows = json.loads(driver.http("/api/series")[2])["count"]
    return {"scan_seconds": round(took, 1), "notifications": log.count("method=VideoLibrary.OnUpdate"),
            "revision_changes": len(page.revisions) - 1, "page_reads": page.fetches,
            "box_reads": log.count("films read from the video database"), "films": films, "shows": shows,
            "page_error": page.error}


def main():
    report = Report("scan")
    report.section("library scan with an open films tab")
    result = scan("scan")
    print(json.dumps(result))
    report.check("the scan adds 30 films and 2 series", result["films"] == 30 and result["shows"] == 2, result)
    report.check("Kodi announced the items one by one", result["notifications"] >= 30, result["notifications"])
    report.check("the burst ends in one re-read of the page", 1 <= result["page_reads"] <= 2, result["page_reads"])
    report.check("... and in one read of the video database", 1 <= result["box_reads"] <= 2, result["box_reads"])
    report.check("the event stream stayed up", result["page_error"] is None, result["page_error"])
    if config.BASELINE_REF:
        baseline = scan("scan-baseline", config.BASELINE_REF)
        print(json.dumps(baseline))
        report.check(f"fewer reads than {config.BASELINE_REF}", result["box_reads"] <= baseline["box_reads"],
                     f"{result['box_reads']} vs {baseline['box_reads']}")
    sys.exit(report.finish())


if __name__ == "__main__":
    main()
