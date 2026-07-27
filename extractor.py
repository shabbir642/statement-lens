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


# --- row model ---------------------------------------------------------------

class Row:
    __slots__ = ("date", "description", "numbers", "balance",
                 "marker", "amount", "signed", "confidence")

    def __init__(self, date, description, numbers, marker):
        self.date = date
        self.description = description
        self.numbers = numbers          # all money numbers on the row
        self.marker = marker            # 'DR' | 'CR' | None (whole-word)
        self.balance = numbers[-1] if numbers else None
        self.amount = None              # chosen transaction amount (magnitude)
        self.signed = None              # signed amount
        self.confidence = None


def _candidate_rows(lines):
    """Turn text lines into candidate transaction rows (date + >=1 amount)."""
    rows = []
    for line in lines:
        iso, remainder = _strip_dates(line)
        if not iso:
            continue
        amounts = _find_amounts(remainder)
        if not amounts:
            continue
        marker_m = _DRCR.search(remainder)
        marker = marker_m.group(1).upper() if marker_m else None
        # Description is the remainder with amounts and the marker removed.
        desc = remainder
        for _, (a, b) in reversed(amounts):
            desc = desc[:a] + " " + desc[b:]
        desc = _DRCR.sub(" ", desc)
        rows.append(Row(iso, _clean_description(desc),
                        [v for v, _ in amounts], marker))
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


def find_opening_balance(full_text):
    m = _OPENING.search(full_text)
    return _to_float(m.group(2)) if m else None


def find_closing_balance(full_text):
    m = _CLOSING.search(full_text)
    return _to_float(m.group(2)) if m else None


def _assign_from_balance(rows, opening):
    """Set signed amounts using the running balance, validating each row."""
    prev_balance = opening
    for r in rows:
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
        # No usable balance yet (first row without opening) — fall back.
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


def reconcile(rows, opening, closing):
    """Compare sum of signed amounts against the balance column's movement.

    Returns (ok, message, movement, parsed_sum, gap) — movement/parsed_sum are
    None when there is no balance column to check against.
    """
    balances = [r.balance for r in rows if r.balance is not None]
    if not balances or opening is None:
        return None, ("no balance column detected — reconciliation skipped, "
                      "review the CSV by hand"), None, None, None
    last_balance = closing if closing is not None else balances[-1]
    movement = last_balance - opening
    parsed_sum = sum(r.signed for r in rows if r.signed is not None)
    gap = parsed_sum - movement
    if abs(gap) <= 0.01:
        return True, (f"reconciled against the balance column exactly "
                      f"(Rs {abs(movement):,.2f} movement)"), movement, parsed_sum, gap
    return False, (f"! does NOT reconcile: gap Rs {gap:,.2f} — "
                   f"rows are missing or duplicated"), movement, parsed_sum, gap


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

    if _has_balance_column(rows):
        # If we could not detect an opening balance from the header, seed it
        # from the first row so later deltas still work; reconciliation then
        # measures movement from that same first balance (still catches drops
        # in rows 2..n).
        seed = opening
        if seed is None and rows and rows[0].balance is not None:
            first = rows[0]
            others = first.numbers[:-1]
            _assign_from_marker_or_words(first, others)
            seed = first.balance - (first.signed or 0.0)
            opening = seed
            _assign_from_balance(rows[1:], first.balance)
        else:
            _assign_from_balance(rows, seed)
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


class NoTextLayer(Exception):
    """Raised when a PDF has no text layer (scanned image)."""

    def __init__(self, path):
        super().__init__(
            f"'{path}' has no text layer — it looks like a scanned image.\n"
            f"Run OCR first, e.g.:\n"
            f"    ocrmypdf '{path}' '{path.rsplit('.', 1)[0]}-ocr.pdf'\n"
            f"then re-run extract on the OCR'd file."
        )
