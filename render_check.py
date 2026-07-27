"""Headless render check, run as a SEPARATE process from run_tests.py.

Playwright drives Chromium over a local socket, so it cannot run inside the
offline-guarded process.  This module is deliberately guard-free: it only
opens the local report.html file (no network) and reports, as JSON on stdout,
the console errors and whether each section populated.
"""

import json
import pathlib
import sys


def main(report_path):
    result = {"available": True, "errors": [], "populated": {}, "crash": None}
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print(json.dumps({"available": False}))
        return
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.on("console", lambda m: result["errors"].append(m.text)
                  if m.type == "error" else None)
            pg.on("pageerror", lambda e: result["errors"].append(str(e)))
            pg.goto(pathlib.Path(report_path).resolve().as_uri())
            pg.wait_for_timeout(500)
            for sec in ["stats", "flow", "insights", "cats", "sparks",
                        "recurring", "outliers", "unrecognised", "txntable"]:
                result["populated"][sec] = pg.eval_on_selector(
                    f"#{sec}", "el => el.innerHTML.trim().length") or 0
            b.close()
    except Exception as e:
        result["crash"] = str(e)
    print(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1])
