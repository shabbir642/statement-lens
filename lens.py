#!/usr/bin/env python3
"""Statement Lens — a local-only spending analyser for bank statement PDFs.

Offline-only, single-user, plain arithmetic.  The very first thing this file
does is install the network block, before importing anything that could reach
out.  Two stages kept deliberately separate with a CSV checkpoint in between:

    extract  PDFs -> transactions.csv   (review and fix this by hand)
    report   CSV  -> report.html        (built from what you approved)
    run      does both
    dump     prints raw PDF text, for when parsing fails
"""

import offline_guard  # noqa: F401  — installs the socket block on import, first

import argparse
import csv
import sys

from categorise import ensure_categories_file


def _load_categories():
    return ensure_categories_file()


def cmd_extract(args, csv_path=None):
    from extractor import extract_pdf, NoTextLayer
    _load_categories()  # ensure the starter file exists on first run
    csv_path = csv_path or args.out

    all_rows = []
    reconciles = []
    for pdf_path in args.pdfs:
        print(f"\n== {pdf_path} ==")
        try:
            res = extract_pdf(pdf_path, password=args.password)
        except NoTextLayer as e:
            print(str(e), file=sys.stderr)
            reconciles.append({"ok": None, "message": "no text layer"})
            continue
        rows = res["rows"]
        all_rows.extend(rows)
        rc = res["reconcile"]
        reconciles.append(rc)
        print(f"parsed {len(rows)} rows; "
              f"opening={res['opening']}, closing={res['closing']}")
        print(rc["message"])

    _write_csv(all_rows, csv_path)
    print(f"\nwrote {len(all_rows)} rows -> {csv_path}")
    print("Review and fix this CSV, then run: report")
    return reconciles


def _write_csv(rows, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "description", "amount", "confidence"])
        for r in rows:
            signed = r.signed if r.signed is not None else 0.0
            w.writerow([r.date, r.description, f"{signed:.2f}",
                        r.confidence or "low"])


def cmd_report(args, reconcile=None):
    from reporter import build_report
    from analysis import load_transactions
    from digest import write_digest

    categories = _load_categories()
    out, n = build_report(args.csv, categories, out_path=args.out,
                          reconcile=reconcile)
    print(f"wrote report with {n} transactions -> {out}")

    if args.summary:
        txns = load_transactions(args.csv, categories)
        path = write_digest(txns)
        print(f"wrote anonymised digest -> {path}")
    return out


def cmd_run(args):
    reconciles = cmd_extract(args, csv_path=args.csv)
    # Pass the first file's reconcile through to the report banner (the common
    # single-statement case); for many files just flag if any failed.
    reconcile = None
    if len(reconciles) == 1:
        reconcile = reconciles[0]
    elif reconciles:
        any_bad = any(r.get("ok") is False for r in reconciles)
        reconcile = {"ok": (False if any_bad else True),
                     "message": ("some statements did not reconcile — see console"
                                 if any_bad else
                                 "all statements reconciled — see console")}
    cmd_report(args, reconcile=reconcile)


def cmd_dump(args):
    import pdfplumber
    with pdfplumber.open(args.pdf, password=args.password or "") as pdf:
        for i, page in enumerate(pdf.pages, 1):
            print(f"\n----- page {i} -----")
            print(page.extract_text() or "(no text on this page)")


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--password", help="password for locked statement PDFs")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="PDFs -> transactions.csv")
    e.add_argument("pdfs", nargs="+")
    e.add_argument("--out", default="transactions.csv")
    e.set_defaults(func=lambda a: cmd_extract(a))

    r = sub.add_parser("report", help="CSV -> report.html")
    r.add_argument("--csv", default="transactions.csv")
    r.add_argument("--out", default="report.html")
    r.add_argument("--summary", action="store_true",
                   help="also write anonymised digest.md")
    r.set_defaults(func=lambda a: cmd_report(a))

    run = sub.add_parser("run", help="extract then report")
    run.add_argument("pdfs", nargs="+")
    run.add_argument("--out", default="report.html")
    run.add_argument("--csv", default="transactions.csv")
    run.add_argument("--summary", action="store_true")
    run.set_defaults(func=cmd_run)

    d = sub.add_parser("dump", help="print raw PDF text")
    d.add_argument("pdf")
    d.set_defaults(func=cmd_dump)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
