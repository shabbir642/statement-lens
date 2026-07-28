#!/usr/bin/env python3
"""End-to-end tests. Reports what actually happened, including failures.

Run: .venv/bin/python run_tests.py
"""

import offline_guard  # noqa: F401  — prove the pipeline runs with sockets blocked

import json
import subprocess
import sys

import make_test_pdf
from extractor import extract_pdf, reconcile
from categorise import ensure_categories_file, categorise
from reporter import build_report
from analysis import load_transactions

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


def main():
    categories = ensure_categories_file()

    # 1. Generate a realistic statement.
    opening, closing, nrows = make_test_pdf.generate()
    print(f"generated test PDF: opening={opening:.2f} closing={closing:.2f} "
          f"rows={nrows}")

    # 2. Extract and check exact reconciliation.
    res = extract_pdf("statements/test-hdfc.pdf")
    rows = res["rows"]
    parsed_sum = sum(r.signed for r in rows if r.signed is not None)
    recomputed_closing = opening + parsed_sum
    check("parsed row count is plausible",
          abs(len(rows) - nrows) <= 1,
          f"parsed {len(rows)} of {nrows} generated")
    check("opening + sum(parsed) == closing, to the paisa",
          round(recomputed_closing, 2) == round(closing, 2),
          f"{recomputed_closing:.2f} vs {closing:.2f}")
    check("reconciliation self-check reports OK",
          res["reconcile"]["ok"] is True,
          res["reconcile"]["message"])
    check("every row parsed at high confidence (balance column trusted)",
          all(r.confidence == "high" for r in rows),
          f"{sum(1 for r in rows if r.confidence=='high')}/{len(rows)} high")

    # 3. Negative test: drop one row, reconciliation MUST now report a gap.
    dropped = rows[:len(rows)//2] + rows[len(rows)//2 + 1:]
    neg = reconcile(dropped, res["opening"], res["closing"])
    check("dropping one row breaks reconciliation (non-zero gap)",
          neg[0] is False and abs(neg[4]) > 0.01,
          neg[1])

    # 4. Salary must categorise as Income, not Transfers Out.
    salary = [r for r in rows if "SALARY" in r.description.upper()]
    cats = {categorise(r.description, r.signed, categories)[0] for r in salary}
    check("salary credits categorise as Income",
          bool(salary) and cats == {"Income"},
          f"{len(salary)} salary rows -> {cats}")

    # 4b. The CREDIT trap: description not corrupted, parsed as a credit.
    interest = [r for r in rows if "INTEREST CAPITALISED" in r.description.upper()]
    check("CREDIT INTEREST line survives (description intact, parsed as credit)",
          bool(interest)
          and all(r.signed and r.signed > 0 for r in interest)
          and all(r.description.upper() == "CREDIT INTEREST CAPITALISED"
                  for r in interest),
          f"{len(interest)} interest rows, sample: "
          f"{interest[0].description if interest else 'none'}")

    # 4c. Merchant normalisation drops the single-letter token ("D").
    from categorise import normalise_merchant
    m = normalise_merchant("ACH D- HDFC MUTUAL FUND SIP")
    check("merchant normalisation drops single-letter token",
          "HDFC MUTUAL FUND" in m and " D " not in f" {m} ", f"-> '{m}'")

    # 5. Build the report and check offline-safety + populated sections.
    from lens import _write_csv
    _write_csv(rows, "transactions.csv")
    out, n = build_report("transactions.csv", categories,
                          reconcile=res["reconcile"])
    with open(out, encoding="utf-8") as fh:
        html = fh.read()
    check("report.html has zero 'http' references (offline-safe)",
          "http" not in html, f"grep http -> {html.count('http')} hits")

    # 6. Store merge: re-import is a no-op; distinct same-key rows both survive.
    import store
    rec = [{"date": "2026-06-01", "description": "X",
            "amount": "-100.00", "confidence": "high"}]
    _, added, skipped = store.merge(rec, rec)
    check("store: re-importing a statement adds nothing",
          added == 0 and skipped == 1, f"added={added} skipped={skipped}")
    _, added2, _ = store.merge([], rec + rec)
    check("store: two genuine same-key rows both kept", added2 == 2,
          f"added={added2}")

    render_headlessly(out)

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


def render_headlessly(report_path):
    """Render via render_check.py in a clean (guard-free) subprocess.

    Playwright talks to Chromium over a local socket, so it cannot run in this
    offline-guarded process; the subprocess only reads the local HTML file.
    """
    proc = subprocess.run(
        [sys.executable, "render_check.py", report_path],
        capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        check("headless render (playwright)", False,
              f"could not run render check: {proc.stderr[-300:]}")
        return
    if not data.get("available"):
        check("headless render (playwright)", None,
              "SKIPPED — playwright not installed; `pip install playwright` "
              "then `playwright install chromium` to enable")
        return
    if data.get("crash"):
        check("headless render (playwright)", False,
              f"render crashed: {data['crash']}")
        return
    check("headless render: zero console errors",
          len(data["errors"]) == 0, f"errors={data['errors'][:3]}")
    empty = [s for s, v in data["populated"].items() if not v]
    check("headless render: every section populated",
          not empty, f"empty sections: {empty}" if empty else "all populated")


if __name__ == "__main__":
    sys.exit(main())
