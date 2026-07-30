"""Stage 1 for tabular statements: CSV / Excel -> the same rows as the PDF path.

Banks also hand out statements as spreadsheets.  Unlike a PDF, the numbers are
already exact — we never have to infer a figure — so the "never invent a number"
guarantee holds trivially.  The hard part is only *which column is which*: every
bank names and orders them differently, wraps the table in preamble/summary
rows, and splits debit/credit in its own way.

Design: one shared core (find the header row, map columns, normalise each row
into an ``extractor.Row``) with a thin per-format reader in front of it.  The
resulting rows flow through the exact same pipeline as PDF output — including
``extractor.reconcile`` when a balance column is present.

CSV (stdlib) and XLSX (openpyxl) are supported; legacy ``.xls`` is not (re-save
as ``.xlsx`` or CSV).  New formats slot in as another reader behind
``_read_matrix`` — the shared core is untouched (see CSV_XLS_Plan.md).
"""

import os
import re

from extractor import Row, reconcile, parse_date

# Our own reviewed checkpoint file uses exactly these columns; a file with this
# header is already-extracted, not a raw bank export, so we pass it through
# verbatim rather than trying to "detect" columns.
INTERNAL_HEADER = ["date", "description", "amount", "confidence"]


class TabularParseError(ValueError):
    """Raised when the statement's columns can't be identified."""


# --- column classification --------------------------------------------------

def _norm(cell):
    return re.sub(r"\s+", " ", str(cell or "").strip().lower())


def _classify(header_cell):
    """Map a header cell to a logical column, or None if it isn't one we use."""
    h = _norm(header_cell)
    if not h:
        return None
    if "date" in h:
        return "date"
    if any(w in h for w in ("withdrawal", "debit", "paid out", "dr amt",
                            "dr amount", "withdrawal amt")):
        return "debit"
    if any(w in h for w in ("deposit", "credit", "paid in", "cr amt",
                            "cr amount", "deposit amt")):
        return "credit"
    if "balance" in h:
        return "balance"
    if h == "amount" or "amount" in h or h in ("amt", "value"):
        return "amount"
    if any(w in h for w in ("narration", "particular", "description", "remark",
                            "detail", "transaction", "payee", "reference")):
        return "description"
    return None


def _letter_ratio(cells):
    text = "".join(str(c) for c in cells)
    if not text:
        return 0.0
    return sum(ch.isalpha() for ch in text) / len(text)


# --- header / column detection ----------------------------------------------

def _find_header(matrix, scan=25):
    """Locate the header row and build {logical_col: index}.

    A header must carry a date column and at least one money column (debit,
    credit or amount).  Among candidates we prefer the most complete one (most
    distinct logical columns), which skips preamble lines that happen to hold a
    stray "date"-like word.
    """
    best = None
    for i, row in enumerate(matrix[:scan]):
        cmap = {}
        for j, cell in enumerate(row):
            kind = _classify(cell)
            if kind and kind not in cmap:      # first column of each kind wins
                cmap[kind] = j
        has_money = any(k in cmap for k in ("debit", "credit", "amount"))
        if "date" in cmap and has_money:
            score = len(cmap)
            if best is None or score > best[0]:
                best = (score, i, cmap)
    if best is None:
        raise TabularParseError(
            "Couldn't find the statement's columns — I looked for a Date column "
            "next to a Debit/Credit or Amount column in the first %d rows and "
            "found none. Is this a bank statement export?" % scan)
    _, idx, cmap = best
    # Fallback description: the unclassified column with the most letters.
    if "description" not in cmap:
        used = set(cmap.values())
        cols = list(zip(*matrix[idx + 1:idx + 30])) if len(matrix) > idx + 1 else []
        cand = [(j, _letter_ratio(cols[j])) for j in range(len(matrix[idx]))
                if j not in used and j < len(cols)]
        cand = [c for c in cand if c[1] > 0.3]
        if cand:
            cmap["description"] = max(cand, key=lambda c: c[1])[0]
    return idx, cmap


# --- value normalisation -----------------------------------------------------

_AMT_CLEAN = re.compile(r"[^0-9.\-]")


def _parse_amount(value):
    """A signed float from a spreadsheet/CSV cell, or None if it isn't money.

    Handles thousands separators, currency symbols, parenthesised negatives and
    a trailing Dr/Cr marker.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    neg = False
    low = s.lower()
    if s.startswith("(") and s.endswith(")"):      # (1,234.00) == -1234.00
        neg = True
    if re.search(r"\bdr\b|dr$", low):
        neg = True
    elif re.search(r"\bcr\b|cr$", low):
        neg = False
    cleaned = _AMT_CLEAN.sub("", s)
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return -abs(val) if neg else val


def _parse_date_cell(value):
    """ISO date string from a cell (str/date/datetime/Excel serial), or ''."""
    import datetime
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime("%Y-%m-%d")
    # Excel sometimes stores a date column as a raw serial number. Convert only
    # values in a plausible date range (~1954–2064) so a stray amount isn't
    # mistaken for a date. Excel's epoch is 1899-12-30 (its 1900 leap-year bug).
    if isinstance(value, (int, float)) and 20000 <= value <= 60000:
        return (datetime.date(1899, 12, 30)
                + datetime.timedelta(days=int(value))).isoformat()
    s = str(value or "").strip()
    if not s:
        return ""
    try:                                   # already ISO (yyyy-mm-dd)
        return datetime.date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        pass
    hit = parse_date(s)                    # reuse the PDF date parser (dd/mm/yy…)
    return hit[0] if hit else ""


# --- row building ------------------------------------------------------------

def _signed_amount(row, cmap):
    """Signed amount for a data row, or None if the row carries no figure."""
    if "debit" in cmap or "credit" in cmap:
        deb = _parse_amount(_cell(row, cmap.get("debit")))
        cred = _parse_amount(_cell(row, cmap.get("credit")))
        if deb in (None, 0.0) and cred in (None, 0.0):
            return None
        return (cred or 0.0) - abs(deb or 0.0)
    return _parse_amount(_cell(row, cmap.get("amount")))


def _cell(row, idx):
    return row[idx] if idx is not None and idx < len(row) else ""


def _build_rows(matrix, header_idx, cmap):
    rows = []
    first = True
    for raw in matrix[header_idx + 1:]:
        if not any(_norm(c) for c in raw):      # blank spacer row
            continue
        date = _parse_date_cell(_cell(raw, cmap.get("date")))
        signed = _signed_amount(raw, cmap)
        if not date or signed is None:          # summary/trailer/non-txn line
            continue
        desc = str(_cell(raw, cmap.get("description")) or "").strip()
        bal = _parse_amount(_cell(raw, cmap.get("balance"))) if "balance" in cmap else None
        numbers = [abs(signed)] + ([bal] if bal is not None else [])
        r = Row(date, re.sub(r"\s+", " ", desc), numbers, None, new_section=first)
        r.amount = abs(signed)
        r.signed = signed
        r.balance = bal                          # override Row's numbers[-1] guess
        r.confidence = "high"                    # exact figure from the file
        rows.append(r)
        first = False
    if not rows:
        raise TabularParseError(
            "Found the header but no transaction rows under it — the file may be "
            "empty or the date/amount columns weren't what I expected.")
    return rows


def _internal_rows(matrix, header_idx, header):
    """Pass through a file that already uses our reviewed-CSV schema."""
    ix = {name: header.index(name) for name in INTERNAL_HEADER}
    rows = []
    for raw in matrix[header_idx + 1:]:
        if not any(_norm(c) for c in raw):
            continue
        signed = _parse_amount(_cell(raw, ix["amount"]))
        if signed is None:
            continue
        r = Row(str(_cell(raw, ix["date"])).strip(),
                str(_cell(raw, ix["description"])).strip(),
                [abs(signed)], None, new_section=False)
        r.amount, r.signed, r.balance = abs(signed), signed, None
        r.confidence = str(_cell(raw, ix["confidence"]) or "low").strip() or "low"
        rows.append(r)
    return rows


# --- format readers ----------------------------------------------------------

def _read_csv(path):
    """CSV -> matrix of string cells, sniffing encoding and delimiter."""
    import csv
    raw = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(path, encoding=enc) as fh:
                raw = fh.read()
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise TabularParseError("Couldn't read the file as text (unknown encoding).")
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel                       # default to comma
    import io
    return [list(r) for r in csv.reader(io.StringIO(raw), dialect)]


def _decrypt_office(path, password):
    """Decrypt a password-protected Office file (OLE2 wrapper) -> BytesIO.

    Banks often email password-protected .xlsx; Excel stores those as an
    encrypted OLE2 (CDFV2) container, not a zip, so openpyxl can't read them
    until we decrypt.  Returns a BytesIO of the inner workbook.
    """
    try:
        import msoffcrypto
    except ImportError:
        raise TabularParseError(
            "This Excel file is password-protected; reading it needs the "
            "'msoffcrypto-tool' package — or open it in Excel, remove the "
            "password, and re-save.")
    if not password:
        raise TabularParseError(
            "This Excel file is password-protected — re-run with the password "
            "(the desktop app has a password box; the CLI takes --password).")
    import io
    buf = io.BytesIO()
    try:
        with open(path, "rb") as fh:
            office = msoffcrypto.OfficeFile(fh)
            office.load_key(password=password)
            office.decrypt(buf)
    except TabularParseError:
        raise
    except Exception:
        raise TabularParseError(
            "Couldn't open the Excel file — the password looks incorrect.")
    buf.seek(0)
    if buf.read(4) != b"PK\x03\x04":          # decrypted content isn't a zip/xlsx
        raise TabularParseError(
            "This looks like a legacy or unusual Excel file — re-save it as "
            ".xlsx or export as CSV.")
    buf.seek(0)
    return buf


def _read_xlsx(path, password=None):
    """XLSX -> matrix of cells (typed: datetime/number/str kept as-is).

    A workbook may hold the table on any sheet (or split accounts across
    sheets); we pick the first sheet whose rows contain a detectable header, so
    a cover/summary sheet doesn't shadow the real one.  Password-protected
    workbooks are decrypted first (see ``_decrypt_office``).
    """
    try:
        import openpyxl
    except ImportError:
        raise TabularParseError(
            "Reading .xlsx needs the 'openpyxl' package (pip install openpyxl), "
            "or export the statement as CSV instead.")
    with open(path, "rb") as fh:
        magic = fh.read(4)
    if magic == b"PK\x03\x04":
        source = path                         # plain, unprotected .xlsx
    elif magic == b"\xd0\xcf\x11\xe0":        # OLE2 -> encrypted (or legacy) Office
        source = _decrypt_office(path, password)
    else:
        raise TabularParseError(
            "This .xlsx isn't a valid Excel file (its contents don't match the "
            "format). It may be an HTML or CSV export renamed to .xlsx — try "
            "opening it in Excel and re-saving, or export as CSV.")
    # read_only streams large sheets; data_only returns computed values, not
    # formula text.
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        best = None
        for ws in wb.worksheets:
            matrix = [list(row) for row in ws.iter_rows(values_only=True)]
            matrix = [r for r in matrix if any(c is not None and str(c).strip()
                                               for c in r)]
            try:
                _find_header(matrix)
            except TabularParseError:
                continue
            best = matrix
            break
        if best is None:
            raise TabularParseError(
                "No sheet in this workbook has a recognisable statement table "
                "(a Date column next to a Debit/Credit or Amount column).")
        return best
    finally:
        wb.close()


def _read_matrix(path, password=None):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return _read_csv(path)
    if ext == ".xlsx":
        return _read_xlsx(path, password)
    if ext == ".xls":
        raise TabularParseError(
            "Legacy .xls isn't supported — re-save it as .xlsx or CSV.")
    raise TabularParseError("Unsupported file type: %s" % ext)


# --- public API --------------------------------------------------------------

def extract_tabular(path, password=None):
    """Parse a CSV/Excel statement into the same dict shape as ``extract_pdf``.

    Keys: rows, opening, closing, reconcile, has_text.  ``password`` is used
    only for password-protected Excel files.
    """
    matrix = _read_matrix(path, password)
    matrix = [r for r in matrix if r]             # drop wholly empty lines

    # Our own reviewed checkpoint? Pass it through untouched.
    for i, row in enumerate(matrix[:5]):
        if [_norm(c) for c in row][:4] == INTERNAL_HEADER:
            rows = _internal_rows(matrix, i, [_norm(c) for c in row])
            res = reconcile(rows)
            return _result(rows, res)

    header_idx, cmap = _find_header(matrix)
    rows = _build_rows(matrix, header_idx, cmap)
    res = reconcile(rows) if "balance" in cmap else (
        None, "no balance column in the file — amounts are exact but could not "
              "be cross-checked; review the CSV by hand", None, None, None)
    return _result(rows, res)


def _result(rows, res):
    return {
        "rows": rows,
        "opening": None,
        "closing": rows[-1].balance if rows and rows[-1].balance is not None else None,
        "reconcile": {"ok": res[0], "message": res[1], "movement": res[2],
                      "parsed_sum": res[3], "gap": res[4]},
        "has_text": True,
    }
