# Known gaps & what the real SBI statement taught us

The first version was tested only against a synthetic HDFC-style PDF, so it
baked in HDFC's assumptions. A real SBI netbanking statement broke it in ways
the synthetic test could never have surfaced. This is the honest list of what
was wrong, what is now fixed, and what still doesn't work.

## Fixed (were real bugs)

1. **Wrapped transaction rows.** When a UPI narration is long, pdfplumber puts
   the description on one line and `date … amounts balance` on the next. The
   old parser required the date and amounts on the *same* line as the
   narration, so it silently dropped the description for ~half the rows and
   skipped the narration-only lines. → Now buffered and re-attached.

2. **Multiple accounts in one PDF.** The statement carried two savings
   accounts, each with its own transaction table and its own running balance.
   Concatenating them made the balance "jump" at the seam, which corrupted both
   direction inference and reconciliation. → Now segmented into sections; the
   running balance resets only at a genuine balance discontinuity (so a header
   repeated at a page break, same account, is *not* treated as a break).

3. **Garbled balance-summary lines ingested as transactions.** SBI's
   `Your Opening Balance on … : 7501.87 null null null null` gets its characters
   interleaved with a `null null null null` column, so it reads as
   `Yourn Oupllening nBualllance …`. The skip regex missed the garbled words and
   the tool booked ₹18,704 of **fake debits**. → Now skipped via the `null`
   placeholder tell, which no real narration contains.

4. **Reconciliation assumed a labelled opening balance.** SBI has no "Opening
   Balance" label in the transaction table. → Reconciliation is now a per-row
   balance-continuity check (each row's delta must equal its own amount), which
   needs no label and works across pages and accounts.

5. **UPI traffic mislabelled as "Transfers Out".** Bare `upi` sat under
   Transfers Out, so every everyday UPI *payment* (a shop, an auto, a QR code)
   was silently called a transfer. → The categoriser now distinguishes UPI
   QR/merchant payments, explicit bank transfers, and generic UPI in/out.

6. **Personal data on screen.** `dump` printed name, address, account number,
   PAN, email. → New `redact.py`; `dump` redacts by default.

## Since addressed (follow-up work)

- **Single-statement horizon.** → `--append` builds a multi-month store
  (`store.py`), deduping re-imports by multiplicity, so recurring/trends/
  month-over-month have data to work with.
- **Inter-account transfers double-counted.** → matched debit/credit pairs are
  netted as `Internal Transfer` and excluded from spend/income (`--no-net` off).
- **Metrics but no advice.** → `alerts.py` emits deterministic warnings (low
  balance before a big debit, concentration, net-negative, month-over-month
  spikes, …) in the console, report, and digest.
- **One layout tested.** → a synthetic SBI fixture (`make_sbi_pdf.py`) joins the
  HDFC one as a golden regression test, so a fix for one bank can't silently
  break another.

## Still weak (limitations, not bugs)

- **Person-to-person UPI can't be auto-categorised.** Payments to individuals
  carry a name and a bank VPA, nothing brandable. They land in the honest
  `UPI Payment` / `UPI Received` buckets for you to review — the tool will not
  guess what a payment to a person was *for*.

- **CRED / credit-card bill payments read as "EMI & Loans".** Defensible, but
  it is really a card bill, not a loan EMI. Rename the category if it bothers
  you — it's just a keyword file.

- **Single-month statements have no recurring commitments.** Recurrence needs
  ≥3 occurrences with a regular gap; one month of data can't show a monthly
  subscription as recurring. Feed several months for that section to fill in.

- **Redaction is heuristic.** It targets Indian statement conventions (titles,
  PIN codes, PAN, masked tails, `null` fields). A bank with a very different
  header could leak a field or over-mask a branch name. Eyeball the first
  `dump` of any new bank layout.

- **`en-IN` "received" is not the same as "income".** Money received over UPI
  is shown as received, not classified as salary/income. On a pass-through
  account (lots of peer settlements) the income/month figure will overcount.

- **Two-column amount layouts still rely on the balance delta.** The tool does
  not read the *positions* of the Credit/Debit columns; it infers direction
  from the running balance. If a statement has no balance column at all, the
  first row of each section falls back to Dr/Cr markers, then keywords, and is
  marked lower confidence.

## CSV / Excel ingest (`tabular_source.py`)

CSV and XLSX statements go through a shared column-detection core. The numbers
are exact (never inferred), so the trust model is stronger than the PDF path —
reconciliation still runs when a balance column is present, otherwise the report
says totals are exact-but-unverified. Current limitations:

- **Number format is en-IN / en-US only.** Amounts are cleaned to digits, `.`
  and `-`, so comma-thousands + period-decimal (incl. Indian lakh grouping,
  `1,23,456.00`) parse correctly, but a European `1.234,56` (comma-decimal)
  would be mis-read. No locale detection.

- **One account per file assumed.** Only the first data row is marked a new
  section, so a CSV/sheet that concatenates two accounts (the running balance
  jumps at the seam) will show reconciliation mismatches. Multiple *sheets* are
  scanned only to find the one real table, not merged as separate accounts.

- **Header detection can fail on unusual layouts — by design it fails loudly.**
  It needs a Date column beside a Debit/Credit or Amount column within the first
  25 rows. Bare `Dr`/`Cr` headers are handled; a column named only `Amount` with
  no balance is handled (unverified). A genuinely unrecognisable layout raises a
  clear "couldn't find the columns" error rather than guessing.

- **Date strings: dash-ISO and `dd/mm/yy` only.** `2024-06-05`, `05/06/2024`,
  `05-Jun-2024` and real Excel date/serial cells parse; `2024/06/05`
  (slash-ISO) does not. Numeric `dd/mm` order is assumed (same as the PDF path).

- **Legacy `.xls` is not read.** Only `.xlsx` (via `openpyxl`); re-save an old
  `.xls` as `.xlsx` or export CSV. Password-protected `.xlsx` is decrypted with
  the supplied password (`msoffcrypto-tool`).
