"""Stage 1: PDF -> transactions.

The whole design assumes no single parser handles every bank, so the output is
a CSV the user reviews and fixes.  Correctness here means: never invent a
number, never silently invert a sign, and always tell the user when the parse
does not add up.

Three traps handled up front (see the task notes):

1. The date is stripped from the line *before* scanning for amounts, so the
   ``25`` in ``28/09/25`` and the ``CR`` in ``CREDIT`` cannot be misread as an
   amount or a direction marker.
2. Direction comes from the running-balance delta, validated against the row's
   own amount column — not from guessing at keywords.
3. Reconciliation: sum of signed amounts must equal the balance column's
   end-to-end movement, or we say so.
"""

import os
import re

# --- regexes -----------------------------------------------------------------

# A numeric date: dd/mm/yy, dd/mm/yyyy, dd-mm-yy, dd-mm-yyyy.
_NUM_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
# A worded date: 01 Apr 2024, 01-Apr-24, 1 January 2024.
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_WORD_DATE = re.compile(
    r"\b(\d{1,2})[ /-]([A-Za-z]{3,9})[ /-](\d{2,4})\b")

# An amount: a number that has a decimal-2 tail OR comma grouping.  Requiring
# one of those excludes bare reference numbers (e.g. 000123456789) and the
# stripped year from a date, both of which are plain digit runs.
_AMOUNT = re.compile(
    r"(?<![\d.])(\d[\d,]*\.\d{1,2}|\d{1,3}(?:,\d{2,3})+)(?![\d.])")

# Dr/Cr markers as whole words: "CR" inside "CREDIT" must not match, so we
# forbid a trailing letter.  A leading boundary stops "SCR" etc.
_DRCR = re.compile(r"(?<![A-Za-z])(DR|CR)(?![A-Za-z])", re.I)

# Opening / closing balance lines in the statement header or footer.
_OPENING = re.compile(
    r"(opening\s+balance|balance\s+b/?f|brought\s+forward|op\.?\s*bal)"
    r"[^0-9]*(\d[\d,]*\.\d{1,2}|\d{1,3}(?:,\d{2,3})+)", re.I)
_CLOSING = re.compile(
    r"(closing\s+balance|balance\s+c/?f|carried\s+forward|cl\.?\s*bal)"
    r"[^0-9]*(\d[\d,]*\.\d{1,2}|\d{1,3}(?:,\d{2,3})+)", re.I)

# Words that hint at a debit when we have nothing better (lowest confidence).
_DEBIT_WORDS = re.compile(
    r"\b(withdrawal|wdl|atm|debit|paid|purchase|pos|charge|emi|"
    r"sent|txn|payment|dr)\b", re.I)
_CREDIT_WORDS = re.compile(
    r"\b(deposit|credit|salary|interest|refund|reversal|received|cr)\b", re.I)

# A transaction-table header row (column titles).  Different banks word it
# differently, so we look for a "date" column title next to a "balance" one,
# with a debit/credit/withdrawal/deposit column somewhere between.  Seeing one
# starts a new section: a fresh account or the same table continued on a new
# page.  It also means the running balance must not be carried across it blindly.
_SECTION_HDR = re.compile(
    r"\bdate\b.*\b(balance|bal)\b", re.I)
_SECTION_HDR_COLS = re.compile(
    r"\b(withdrawal|deposit|debit|credit|dr|cr|amount|chq|ref)\b", re.I)

# Lines that state a balance rather than a transaction — they carry a date and
# a number and would otherwise be ingested as a bogus row.
_SKIP_LINE = re.compile(
    r"(opening|closing|available|current|ledger|effective)\s+balance|"
    r"balance\s+(b/?f|c/?f|brought|carried)|"
    r"multi[- ]?option\s+deposit|total\b.*\binr|statement\s+summary|"
    r"customer\s+care|please\s+do\s+not\s+share|www\.|\.co\.in|page\s+\d+\s+of|"
    # Account-summary header block (SBI et al.): "A/C Open Date", "Expected AMB"
    # (average monthly balance), etc.  These carry a date (the account-open
    # date) and a number, so without this they get ingested as a phantom row —
    # and they leak account metadata that never belonged in the txn table.
    # \s* not \s+: some SBI PDFs render these glued with no spaces, e.g.
    # "A/COpenDate : ExpectedAMB:" — still a summary header, never a txn.
    r"a/?c\s*open\s*date|account\s*open(?:ing)?\s*date|expected\s*amb|"
    r"average\s*monthly\s*bal|\bamb\b\s*[:\-]|"
    # SBI writes empty summary fields as the literal token "null"; such lines
    # (e.g. a garbled "Opening Balance on … : 7501.87 null null null null") are
    # account summaries, never transactions.  No real narration contains "null".
    r"\bnull\b",
    re.I)

# SBI-style "Your Closing Balance on 30-06-26: 868.87" (per-account closing).
_CLOSING_LABEL = re.compile(
    r"closing\s+balance[^0-9]*?[:\-]?\s*(\d[\d,]*\.\d{1,2}|\d{1,3}(?:,\d{2,3})+)",
    re.I)


def _to_float(token):
    return float(token.replace(",", ""))


def parse_date(line):
    """Return (iso_date, match_span) for the first date in the line, or None."""
    m = _NUM_DATE.search(line)
    if m:
        d, mo, y = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if y < 100:
            y += 2000
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}", m.span()
    m = _WORD_DATE.search(line)
    if m:
        mon = _MONTHS.get(m.group(2)[:3].lower())
        if mon:
            d, y = int(m.group(1)), int(m.group(3))
            if y < 100:
                y += 2000
            if 1 <= d <= 31:
                return f"{y:04d}-{mon:02d}-{d:02d}", m.span()
    return None


def _strip_dates(line):
    """Remove up to two leading dates (transaction date + value date).

    Returns (iso_date, remainder).  ``iso_date`` is the first date found.
    """
    first = parse_date(line)
    if not first:
        return None, line
    iso, span = first
    remainder = line[:span[0]] + " " + line[span[1]:]
    # Drop a second date too (value-date column) so it can't be read as money.
    second = parse_date(remainder)
    if second:
        _, span2 = second
        remainder = remainder[:span2[0]] + " " + remainder[span2[1]:]
    return iso, remainder


def _find_amounts(text):
    """Return list of (value, span) for money-looking numbers in text order."""
    return [(_to_float(m.group(1)), m.span()) for m in _AMOUNT.finditer(text)]


def _clean_description(text):
    return re.sub(r"\s+", " ", text).strip(" -\t")


def _has_narration(text):
    """True if ``text`` holds a human-readable word, not just a reference code.

    A payee narration has whole-word tokens ("MOHD", "ANWAR", "SORRY"); a bank
    reference like ``HDFCH01066840361`` is letters glued to digits — no
    standalone alphabetic word.  Used to tell a row that describes *who* was
    paid from one that carries only an IMPS/UPI reference, so the wrapped line
    holding the payee name / VPA / account is not thrown away.
    """
    return any(tok.isalpha() and len(tok) >= 3
               for tok in re.split(r"[\s/\-]+", text or ""))


# --- row model ---------------------------------------------------------------

class Row:
    __slots__ = ("date", "description", "numbers", "balance",
                 "marker", "amount", "signed", "confidence", "new_section")

    def __init__(self, date, description, numbers, marker, new_section=False):
        self.date = date
        self.description = description
        self.numbers = numbers          # all money numbers on the row
        self.marker = marker            # 'DR' | 'CR' | None (whole-word)
        self.balance = numbers[-1] if numbers else None
        self.amount = None              # chosen transaction amount (magnitude)
        self.signed = None              # signed amount
        self.confidence = None
        self.new_section = new_section  # first row of a table section/account


def _is_section_header(line):
    return bool(_SECTION_HDR.search(line) and _SECTION_HDR_COLS.search(line)
                and not _find_amounts(line))


def _looks_like_description(line):
    """A wrapped narration line: has letters, isn't noise, carries no amount."""
    if not re.search(r"[A-Za-z]", line):
        return False
    if _SKIP_LINE.search(line) or _is_section_header(line):
        return False
    return True


def _candidate_rows(lines):
    """Turn text lines into transaction rows, handling two real-world messes:

    * **Wrapped rows.** When a narration is long, the description lands on its
      own line and the ``date ... amounts balance`` lands on the next.  We keep
      a rolling description buffer and, when a dated row has no usable narration
      of its own, adopt the buffered line(s).
    * **Sections.** A column-header row (or a balance-label line) marks a break
      between accounts / pages.  The next real row is flagged ``new_section`` so
      the running balance is not carried across the seam.
    """
    rows = []
    pending = []            # buffered wrapped-description lines
    section_break = True    # the first row is always a section start

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if _is_section_header(line):
            section_break = True
            pending = []
            continue
        if _SKIP_LINE.search(line):
            pending = []
            continue

        iso, remainder = _strip_dates(line)
        amounts = _find_amounts(remainder)

        if not iso or not amounts:
            # Not a dated money row: treat as a possible wrapped description.
            if _looks_like_description(line):
                pending.append(_clean_description(line))
            continue

        marker_m = _DRCR.search(remainder)
        marker = marker_m.group(1).upper() if marker_m else None
        desc = remainder
        for _, (a, b) in reversed(amounts):
            desc = desc[:a] + " " + desc[b:]
        desc = _clean_description(_DRCR.sub(" ", desc))

        # Adopt the buffered wrapped line(s) when this row lacks a real
        # narration of its own — either nothing readable, or just a bank
        # reference code (an IMPS/UPI ref like HDFCH0106..., no payee).  The
        # reference alone throws away the payee name / VPA / account that the
        # wrapped line carries, so we keep both (narration first, then ref).
        if pending and (not _has_narration(desc) or len(desc) < 4):
            joined = _clean_description(" ".join(pending))
            desc = joined if not desc else _clean_description(joined + " " + desc)
        pending = []

        rows.append(Row(iso, desc, [v for v, _ in amounts], marker,
                        new_section=section_break))
        section_break = False
    return rows


def _has_balance_column(rows, sample=8, tol=0.02):
    """Decide whether the last number on each row is a running balance.

    Sample the first few multi-number rows: if the change in the last column
    between consecutive rows matches one of the *other* numbers on the row,
    a balance column exists and we can trust deltas.
    """
    multi = [r for r in rows if len(r.numbers) >= 2]
    if len(multi) < 2:
        return False
    hits = checks = 0
    prev = None
    for r in multi[:sample + 1]:
        if prev is not None:
            delta = abs(r.balance - prev.balance)
            others = r.numbers[:-1]
            if others and _matches_any(delta, others, tol):
                hits += 1
            checks += 1
        prev = r
    return checks > 0 and hits / checks >= 0.6


def _matches_any(value, candidates, tol):
    for c in candidates:
        if abs(abs(c) - value) <= max(0.01, tol * max(abs(c), value)):
            return True
    return False


def _closest(value, candidates):
    return min(candidates, key=lambda c: abs(abs(c) - value))


def _continues(prev_balance, r, tol=0.02):
    """True if r's balance flows from prev_balance by one of r's own amounts.

    Used to tell a repeated page header (balance continues — same account) from
    a real account change (balance jumps), so we only reset the running balance
    at genuine breaks.
    """
    if prev_balance is None or r.balance is None:
        return False
    others = r.numbers[:-1]
    delta = r.balance - prev_balance
    return bool(others and _matches_any(abs(delta), others, tol))


def find_opening_balance(full_text):
    m = _OPENING.search(full_text)
    return _to_float(m.group(2)) if m else None


def find_closing_balance(full_text):
    m = _CLOSING.search(full_text)
    return _to_float(m.group(2)) if m else None


def _assign_from_balance(rows, opening=None):
    """Set signed amounts using the running balance, validating each row.

    The balance is not carried across a section break (a new account, where the
    balance jumps): at each ``new_section`` row the running balance resets, so
    that row falls back to its Dr/Cr marker rather than trusting a bogus delta.
    Only the very first section is seeded with a detected opening balance.
    """
    prev_balance = None
    for i, r in enumerate(rows):
        if r.new_section:
            if i == 0:
                prev_balance = opening
            elif not _continues(prev_balance, r):
                # Genuine break (account change): reset. A repeated page header
                # where the balance still flows is left alone.
                prev_balance = None
        others = r.numbers[:-1]
        if prev_balance is not None and r.balance is not None:
            delta = r.balance - prev_balance
            if others and _matches_any(abs(delta), others, 0.02):
                r.amount = _closest(abs(delta), others)
                r.signed = -r.amount if delta < 0 else r.amount
                r.confidence = "high"
                prev_balance = r.balance
                continue
            # Balance moved but no amount matches: still trust the delta's sign,
            # but this row is suspicious.
            if others:
                r.amount = _closest(abs(delta), others)
                r.signed = -r.amount if delta < 0 else r.amount
                r.confidence = "medium"
                prev_balance = r.balance
                continue
        # No usable prior balance (first row of a section) — fall back.
        _assign_from_marker_or_words(r, others or r.numbers)
        if r.balance is not None:
            prev_balance = r.balance


def _assign_from_marker_or_words(r, candidates):
    """Fallback: Dr/Cr markers (medium), then keyword guessing (low)."""
    if not candidates:
        candidates = r.numbers
    # Prefer the non-balance amount if we have >1 number.
    amount = candidates[0] if candidates else (r.numbers[0] if r.numbers else 0.0)
    if r.marker == "DR":
        r.amount, r.signed, r.confidence = amount, -amount, "medium"
    elif r.marker == "CR":
        r.amount, r.signed, r.confidence = amount, amount, "medium"
    else:
        text = r.description
        if _CREDIT_WORDS.search(text) and not _DEBIT_WORDS.search(text):
            r.amount, r.signed = amount, amount
        else:
            r.amount, r.signed = amount, -amount   # default to money out
        r.confidence = "low"


def reconcile(rows, opening=None, closing=None):
    """Check that the balance column and the amounts tell the same story.

    For each row that follows another within the same section, the balance
    should move by exactly that row's amount.  Two *independent* measurements —
    the printed balance delta and the printed Credit/Debit figure — are compared
    per row.  If a row was dropped or duplicated, its neighbour's delta no longer
    matches its amount, so the mismatch is caught.  This needs no opening-balance
    label and works across pages and multiple accounts.

    Returns (ok, message, movement, parsed_sum, gap).
    """
    checked = matched = 0
    prev = None
    movement = parsed = 0.0
    first_gap = None
    for r in rows:
        b = r.balance
        if prev is None or b is None:
            if b is not None:
                prev = b
            continue
        # A real section break (balance jumps) is not a checkable step; a page
        # header where the balance still flows is checked like any other row.
        if r.new_section and not _continues(prev, r):
            prev = b
            continue
        delta = b - prev
        movement += delta
        if r.signed is not None:
            parsed += r.signed
        amt = r.amount
        if amt is not None and abs(abs(delta) - abs(amt)) <= max(0.01, 0.02 * abs(amt)):
            matched += 1
        elif first_gap is None:
            first_gap = (r.date, (r.description or "")[:30])
        checked += 1
        prev = b

    if checked == 0:
        return None, ("no balance column detected — reconciliation skipped, "
                      "review the CSV by hand"), None, None, None

    gap = parsed - movement
    mismatches = checked - matched
    if mismatches == 0:
        return True, (f"reconciled against the balance column: all {checked} "
                      f"balance steps match their amounts "
                      f"(Rs {abs(movement):,.2f} moved)"), movement, parsed, gap
    msg = (f"! does NOT reconcile: {mismatches} of {checked} balance steps "
           f"don't match their amounts — rows missing or duplicated "
           f"(first near {first_gap[0]} '{first_gap[1]}')")
    return False, msg, movement, parsed, gap


# --- public API --------------------------------------------------------------

def extract_pdf(pdf_path, password=None):
    """Parse a bank statement PDF into rows plus a reconciliation result.

    Returns a dict with keys: rows, opening, closing, reconcile, has_text.
    Raises NoTextLayer when the PDF has no extractable text.
    """
    import pdfplumber  # imported late so the offline guard is already installed

    lines = []
    page_texts = []
    with pdfplumber.open(pdf_path, password=password or "") as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            page_texts.append(text)
            lines.extend(text.splitlines())

    full_text = "\n".join(page_texts)
    if not full_text.strip():
        raise NoTextLayer(pdf_path)

    rows = _candidate_rows(lines)
    opening = find_opening_balance(full_text)
    closing = find_closing_balance(full_text)
    if closing is None:
        m = _CLOSING_LABEL.search(full_text)
        if m:
            closing = _to_float(m.group(1))

    if _has_balance_column(rows):
        _assign_from_balance(rows, opening)
    else:
        for r in rows:
            _assign_from_marker_or_words(r, r.numbers[:-1] if len(r.numbers) > 1
                                        else r.numbers)

    result = reconcile(rows, opening, closing)
    return {
        "rows": rows,
        "opening": opening,
        "closing": closing,
        "reconcile": {
            "ok": result[0], "message": result[1],
            "movement": result[2], "parsed_sum": result[3], "gap": result[4],
        },
        "has_text": True,
    }


def extract(path, password=None):
    """Parse any supported statement into rows + reconcile, by file type.

    PDF goes through the text-layout parser; CSV/Excel go through the tabular
    reader.  Both return the same dict shape (rows, opening, closing, reconcile,
    has_text) so the rest of the pipeline doesn't care which format it was.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".xlsx", ".xls"):
        import tabular_source
        return tabular_source.extract_tabular(path)
    return extract_pdf(path, password=password)


class NoTextLayer(Exception):
    """Raised when a PDF has no text layer (scanned image)."""

    def __init__(self, path):
        super().__init__(
            f"'{path}' has no text layer — it looks like a scanned image.\n"
            f"Run OCR first, e.g.:\n"
            f"    ocrmypdf '{path}' '{path.rsplit('.', 1)[0]}-ocr.pdf'\n"
            f"then re-run extract on the OCR'd file."
        )
