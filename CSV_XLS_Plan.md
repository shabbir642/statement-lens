# Plan: accept CSV / Excel statements (Phase 1)

Status: **planned, not implemented.** Parked here so it survives context loss.
Sibling doc: `DEFERRED_FEATURES.md` (data-purge). Image/OCR support is a separate,
higher-risk Phase 2 — deliberately out of scope here.

## Goal

Let the tool ingest bank statements exported as **CSV**, **XLSX**, and (optionally)
legacy **XLS**, in addition to today's PDF. Everything downstream — the `Row`
model → `transactions.csv` → `categorise` / `analysis` / `reporter` — stays
unchanged. `store.py --append` (multi-month merge) then works across formats for
free.

## Why CSV + Excel are one feature

The hard part of both is identical: **detecting which columns are
date / description / amount / balance**, then normalising signs and dates. Only
the *reader* differs. So build the column-detection core once and reuse it. CSV
is the cheapest entry point because Python's `csv` is stdlib — **zero new
dependencies** — and it forces the detection design that XLSX then reuses.

## Trust model (why this is low-risk, unlike OCR)

Today's guarantee (`extractor.py`): *never invent a number; reconcile every row
against the running-balance column.* Tabular inputs **preserve** this — the
numbers are exact.

- If a **balance column exists** → reuse the existing `reconcile()`; reconciled
  rows are high-confidence.
- If **no balance column** → the numbers are still exact (never invented), but we
  cannot cross-check them, so the report must show a banner: *"no balance column —
  totals not independently verified."* Do **not** silently imply the same
  assurance a reconciled PDF gets.

## Architecture

Add a format dispatch layer in `extractor.py` keyed on extension; the rest of the
pipeline is untouched:

```
extract(path) ─▶ .pdf              → extract_pdf        (exists)
                 .csv/.xlsx/.xls   → tabular_source.extract_tabular  (new)
```

New module `tabular_source.py`:

```
readers (format-specific):
  read_csv()   → csv (stdlib) + delimiter & encoding sniffing     [no dep]
  read_xlsx()  → openpyxl, data_only=True                         [1 small dep]
  read_xls()   → xlrd (legacy BIFF)                               [defer]
      │  each returns a uniform matrix: list[list[cell]]
      ▼
shared core (write once, reuse for all three):
  1. find_header_row()  — skip preamble/account-info rows; pick the row whose
                          cells best match the synonym dictionary
  2. map_columns()      — build {date, description, debit, credit, amount, balance}
  3. per data row → Row(date, description, signed_amount, balance)
                    stop at trailer/summary rows
  4. if a balance column exists → reuse extractor.reconcile()
```

### Column synonym dictionary

- date: `Date, Txn Date, Transaction Date, Value Date, Posting Date`
- description: `Narration, Particulars, Description, Remarks, Details`
- amount: `Debit`/`Withdrawal`(+`Credit`/`Deposit`) two-column form, **or** a single
  signed `Amount`
- balance: `Balance, Closing Balance, Running Balance, Available Balance`

### Normalisation rules

- Combine Dr/Cr columns into one signed amount.
- Handle `(1,234.00)` parenthesised negatives, trailing `Dr`/`Cr`, currency
  symbols, thousands separators, locale.
- Dates: strings via the existing date parser; Excel also has real datetime cells
  **and** serial-number dates — handle both.

## Format-specific notes

| | CSV | XLSX | XLS (legacy) |
|---|---|---|---|
| Reader | `csv` (stdlib) | `openpyxl` | `xlrd` |
| New dependency | none | one, pure-Python | one — defer |
| Delimiter | sniff `, ; \t \|` | n/a | n/a |
| Encoding | sniff UTF-8 / BOM / cp1252 | handled | handled |
| Dates | all strings → parse | typed datetime or serial number | typed |
| Extra gotchas | quoted commas, preamble/trailer rows | multiple sheets, merged cells, formulas (`data_only=True`) | old BIFF format |

## CSV collision with our own file (important)

We already emit an internal `transactions.csv` (`date,description,amount,confidence`).
The adapter must **detect that exact schema and short-circuit**: if the header
already matches our internal format, treat the file as *already reviewed* and skip
extraction (go straight to reporting). A bank's raw CSV won't match, so it flows
through column detection. Bonus: users can re-open a CSV they previously edited.

## Challenges vs the current PDF path

- **Column/header variety across banks** is the whole game (differing names/order,
  preamble account rows, trailing "Total / Closing Balance" rows). Solved once for
  all three formats.
- **No text-layout fallback** like PDF has — if header detection fails, fail
  *loudly* with "couldn't identify the columns — here's what I saw", never guess.
- Reconciliation fires only when a balance column is present; otherwise be explicit
  that totals are exact-but-unverified.
- Packaging is trivial vs OCR: CSV adds nothing; XLSX adds one small pure-Python
  wheel — no binaries, no size blowup. Offline guarantee intact (`csv`/`openpyxl`
  don't touch the network — quick `offline_guard` re-check anyway).

## Files to touch

- `extractor.py` — extension dispatch.
- `tabular_source.py` — **new**: readers + shared column-detection core.
- `app.py` — picker `file_types` add CSV/Excel.
- `ui/upload.html` — copy ("Drop a PDF, CSV or Excel statement") + drop-accept.
- `lens.py` — CLI accepts the new extensions.
- `statement-lens.spec` — bundle `openpyxl` (and `xlrd` if 1c).
- `run_tests.py` — golden fixtures (a synthetic bank CSV; an `openpyxl`-generated
  XLSX) asserting correct mapping + reconciliation.
- `requirements-app.txt` / requirements — add `openpyxl`.

## Sub-phasing

- **1a — shared core + CSV.** Zero new deps. Fastest; builds the column-detection
  engine everything else reuses. Includes the internal-schema short-circuit.
- **1b — XLSX.** Add `openpyxl` + `read_xlsx()`; core already exists.
- **1c — legacy `.xls`.** Only if real statements need it; add `xlrd`. Defer.

## First concrete step when resumed

Draft `tabular_source.py` with `find_header_row()` + `map_columns()` + `read_csv()`
(delimiter/encoding sniffing) + the internal-`transactions.csv` short-circuit, wire
a `.csv` branch into `extractor.extract`, and add a golden CSV fixture to
`run_tests.py`.
