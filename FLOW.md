# Code flow

How a PDF becomes a report, module by module. Diagrams are Mermaid (render on
GitHub and most Markdown viewers). Every arrow is plain function calls — no
network, no LLM. The first import in `lens.py` is `offline_guard`, which patches
`socket` to raise, so nothing downstream can reach out.

## Module map

| File | Role |
| --- | --- |
| [offline_guard.py](offline_guard.py) | Blocks the network on import (first thing `lens.py` does) |
| [lens.py](lens.py) | CLI entry: `extract` / `report` / `run` / `dump` |
| [extractor.py](extractor.py) | Stage 1 — PDF text → transaction `Row`s + reconciliation |
| [categorise.py](categorise.py) | Direction-aware keyword categoriser + merchant normaliser |
| [analysis.py](analysis.py) | Arithmetic over the CSV: totals, recurring, outliers, insights, balance health |
| [reporter.py](reporter.py) | Stage 2 — CSV → self-contained `report.html` |
| [digest.py](digest.py) | `--summary` → anonymised `digest.md` |
| [redact.py](redact.py) | Strips identity fields from `dump` output |
| [make_test_pdf.py](make_test_pdf.py) / [run_tests.py](run_tests.py) / [render_check.py](render_check.py) | Test-only |

## Entry → commands

```mermaid
flowchart TD
    A["python lens.py ..."] --> G["import offline_guard<br/>(socket.socket / create_connection /<br/>getaddrinfo -> raise)"]
    G --> B["main() -> build_parser()"]
    B --> C{subcommand}
    C -->|extract| E["cmd_extract"]
    C -->|report| R["cmd_report"]
    C -->|run| RUN["cmd_run"]
    C -->|dump| D["cmd_dump"]
    RUN --> E
    RUN --> R
    E --> CSV[("transactions.csv")]
    R --> HTML[("report.html")]
    R -->|--summary| MD[("digest.md")]
    D --> TXT["redacted text to stdout"]
    E -.first run.-> CAT[("categories.json<br/>written if missing")]
```

- `run` is just `extract` then `report`, passing the reconciliation result
  through so the report banner can show it.
- `--password` is a shared option accepted before *or* after the subcommand.

## Stage 1 — extract (PDF → transactions.csv)

Driver: `extract_pdf()` in [extractor.py](extractor.py). Correctness rule:
never invent a number, never silently invert a sign, always report when the
parse doesn't add up.

```mermaid
flowchart TD
    P[("PDF")] --> PL["pdfplumber.open(password)<br/>page.extract_text() per page"]
    PL --> TL{"any text?"}
    TL -->|no| NTL["raise NoTextLayer<br/>(tells user to run ocrmypdf)"]
    TL -->|yes| CR["_candidate_rows(lines)"]

    subgraph CR2 ["_candidate_rows: line by line"]
      direction TB
      H1["_is_section_header?<br/>(Date...Balance + a Dr/Cr/amount col)"] -->|yes| SB["mark section break, clear buffer"]
      H2["_SKIP_LINE? (balance labels,<br/>'null' summary rows, footers)"] -->|yes| SK["skip"]
      H3["_strip_dates(line)<br/>(cut 1st + 2nd date out FIRST)"] --> H4["_find_amounts(remainder)<br/>(needs decimal-2 or comma)"]
      H4 -->|"no date / no amount"| WD["_looks_like_description?<br/>buffer as wrapped narration"]
      H4 -->|"date + amounts"| MK["_DRCR marker (whole word)<br/>build description<br/>adopt buffered narration if empty"]
      MK --> ROW["Row(date, desc, numbers, marker, new_section)"]
    end

    CR --> BC{"_has_balance_column?<br/>(sample: does last-col delta<br/>match another number?)"}
    BC -->|yes| AB["_assign_from_balance(rows, opening)"]
    BC -->|no| AM["_assign_from_marker_or_words per row"]

    subgraph AB2 ["_assign_from_balance: running balance"]
      direction TB
      NS{"new_section row?"} -->|"i==0"| SEED["seed prev = opening"]
      NS -->|"else & _continues() false"| RST["reset prev = None (real account change)"]
      NS -->|"else"| KEEP["keep prev (page continuation)"]
      DELTA["delta = balance - prev"] --> VAL{"_matches_any(abs delta, amounts)?"}
      VAL -->|yes| HI["amount=_closest, sign=delta -> confidence HIGH"]
      VAL -->|"no, but delta moved"| ME["confidence MEDIUM"]
      VAL -->|no prior balance| FB["_assign_from_marker_or_words<br/>DR/CR -> MEDIUM, keyword -> LOW"]
    end

    AB --> RC["reconcile(rows, opening, closing)"]
    AM --> RC
    RC --> OUT["dict: rows, opening, closing, reconcile"]
    OUT --> BH["_print_balance_health(rows)<br/>(per-account low / churn)"]
    OUT --> WCSV["_write_csv -> date,description,amount,confidence"]
    WCSV --> CSV[("transactions.csv")]
```

### Reconciliation (`reconcile`)

Two *independent* measurements per row are compared: the printed balance delta
vs. the printed Credit/Debit figure. If they always agree, nothing was dropped
or duplicated. Needs no opening-balance label and works across pages and
multiple accounts (`_continues()` tells a page-repeat header from a real
account change).

```mermaid
flowchart LR
    S["for each row (in order)"] --> Q{"prev balance?<br/>real section break?"}
    Q -->|"break / no prev"| RESET["reset prev, skip"]
    Q -->|"same run"| CK["delta = balance - prev<br/>compare abs delta vs row amount"]
    CK -->|match| M["matched++"]
    CK -->|mismatch| G["record first gap"]
    M --> N["next"]
    G --> N
    N --> R{"any mismatch?"}
    R -->|no| OK["reconciled: all N steps match (Rs X moved)"]
    R -->|yes| BAD["does NOT reconcile: K of N steps off"]
```

## Stage 2 — report (transactions.csv → report.html)

Driver: `build_report()` in [reporter.py](reporter.py). Data is embedded in the
page as JSON; **all aggregation runs in the browser in vanilla JS**, so the
month-range and category filters recompute everything live. Zero external refs
(no `http` substring anywhere — verify with `grep http report.html`).

```mermaid
flowchart TD
    CSV[("transactions.csv")] --> LT["load_transactions()<br/>+ categorise() + normalise_merchant() per row"]
    CAT[("categories.json")] --> LT
    LT --> BR["build_report(): embed txns as JSON<br/>into the HTML template"]
    BR --> HTML[("report.html")]

    subgraph JS ["in-browser render: recomputes on every filter"]
      direction TB
      ST["header stats: spend/income/net/committed"]
      FL["monthly flow SVG (income up / spend down / net line)"]
      IN["Insights: throughput, Pareto concentration,<br/>counterparties, weekday, round-number, autopay pings"]
      CB["category bars (click to filter below)"]
      SP["per-category sparklines"]
      RCR["recurring commitments (+ stability %)"]
      OL["outliers (median + 4*MAD per category)"]
      UR["unrecognised merchants + copy-rules JSON"]
      TB["searchable transaction table (low-conf flagged)"]
    end
    HTML --> JS

    CSV -->|--summary| WD["write_digest()"]
    CAT --> WD
    WD --> MD[("digest.md<br/>anonymised: category totals per month,<br/>recurring, spending insights")]
```

### What computes where

| Concern | Function | Consumed by |
| --- | --- | --- |
| Category of a row (direction-aware) | `categorise()` | report, digest |
| Merchant key (drops single-letter tokens) | `normalise_merchant()` | recurring, insights |
| Month × category totals | `monthly_category_totals()` | digest |
| Recurring (merchant + stable amount + regular gap + stability) | `detect_recurring()` | digest (report mirrors it in JS) |
| Outliers (median + 4×MAD) | `detect_outliers()` | report mirrors it in JS |
| Concentration / counterparties / weekday / pings | `spending_insights()` | digest (report mirrors it in JS) |
| Per-account low balance / churn | `balance_health()` | `extract`/`run` console |

## dump (debugging path)

```mermaid
flowchart LR
    P[("PDF")] --> DT["cmd_dump: extract_text per page"]
    DT --> RD{"--no-redact?"}
    RD -->|"no (default)"| RX["redact_text()<br/>mask name/address/account/PAN/email/<br/>masked-id; keep transaction rows"]
    RD -->|yes| RAW["raw text"]
    RX --> O["stdout"]
    RAW --> O
```

## Test path

`run_tests.py` builds a synthetic HDFC PDF with `make_test_pdf.py`, runs the
pipeline, and asserts exact-paisa reconciliation, that dropping a row breaks
reconciliation, correct Income categorisation, the CREDIT/date traps, zero
`http` in the report, and — via `render_check.py` in a separate (guard-free)
process — a headless render with no console errors and every section populated.
