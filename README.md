# Statement Lens

A local-only spending analyser for Indian bank statement PDFs (HDFC / ICICI /
SBI / Axis / Kotak layouts, degrading gracefully on others). Single user, runs
on your laptop. No LLM, no API, no network. Every number is plain arithmetic you
can verify by hand.

## Guarantees

- **Offline, enforced not promised.** Before any work, `offline_guard` replaces
  `socket.socket`, `socket.create_connection` and `socket.getaddrinfo` with
  functions that raise. If a dependency ever phones home, the tool crashes.
- **Self-contained report.** `report.html` has zero external references — no
  CDN, no web fonts, no analytics. Verify: `grep http report.html` → nothing.
- **Reconciliation.** If the statement has a balance column, the sum of every
  signed amount is checked against the column's end-to-end movement. A clean
  reconcile proves nothing was dropped or double-counted.

## Install

Only runtime dependency is `pdfplumber` (Python 3.9+):

```bash
python3 -m venv .venv
.venv/bin/pip install pdfplumber
```

`reportlab` and `playwright` are needed only to run the tests, not the tool.

## Use

Two stages, deliberately separate, with a CSV checkpoint you review by hand.

```bash
# 1. PDFs -> transactions.csv  (review and fix this file)
.venv/bin/python lens.py extract statements/mystatement.pdf

# 2. reviewed CSV -> report.html
.venv/bin/python lens.py report --summary

# or both at once
.venv/bin/python lens.py run statements/mystatement.pdf --summary

# when parsing fails, see the raw text the parser sees
.venv/bin/python lens.py dump statements/mystatement.pdf
```

- `--password SECRET` handles locked statements (banks email them locked).
- If a PDF has no text layer it is a scan: the tool tells you to run
  `ocrmypdf` first rather than failing silently.
- `--summary` writes `digest.md`: category totals per month plus recurring
  commitments, with merchant names, dates, reference numbers and account
  details stripped — safe to paste into an external tool.

## CSV format

`date, description, amount, confidence`. Amount is signed; negative is money
out. Confidence is `high` (direction from the running balance, validated),
`medium` (from Dr/Cr markers), or `low` (keyword guess — check these).

## Categories

`categories.json` is a plain `{"category": ["lowercase", "substrings"]}` map
written on first run. Edit it freely; it is safe to commit and worth
versioning. Categorisation is direction-aware: a `neft` credit is Income, not a
transfer out. The report's "Unrecognised merchants" panel has a **copy rules**
button that emits JSON to paste straight into this file.

## Report

Dark UI, inline SVG charts (no chart library). Header stats, a monthly flow
chart, clickable category bars that filter everything below, per-category
sparklines, recurring commitments (with a stability score — the share of
charges within 2% of the median), outliers (large relative to their own
category via median + 4×MAD), an unrecognised-merchants panel, a searchable
transaction table, and a month-range filter driving everything.

## Tests

```bash
.venv/bin/pip install reportlab playwright && .venv/bin/playwright install chromium
.venv/bin/python run_tests.py
```

Generates a realistic ~370-row HDFC-style statement, runs the pipeline, and
asserts: exact paisa reconciliation, that dropping a row breaks reconciliation,
that salary is Income, that the CREDIT/date traps are handled, that the report
has zero `http` references, and (headless) that it renders with no console
errors and every section populated.

## How it works

See [FLOW.md](FLOW.md) for the code-flow diagrams — entry points, the two
pipelines (extract and report), the parsing/reconciliation helpers, and the
outputs. Known limitations are in [GAPS.md](GAPS.md).

## Repo hygiene

`.gitignore` excludes `statements/`, `*.pdf`, `transactions.csv`, `report.html`,
`digest.md` and `merchant_overrides.json` — that is your financial history in
plaintext. Only the code and `categories.json` are committed.
