"""Strip personal identity fields from statement text.

The statement header carries who you are — name, address, account and customer
numbers, PAN, email, phone.  None of that is needed to analyse spending, and it
should not be printed to a terminal or handed to anything else.  This module
removes it while leaving transaction rows (dates, descriptions, amounts)
untouched, because the descriptions are the whole point.

It is heuristic and errs toward over-redaction: better to mask a branch name
than to leak an address.  It is not a guarantee — always eyeball the output of
a statement from a bank layout you have not tried before.
"""

import re

# Email addresses (personal and bank alike — all masked).
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Indian PAN: 5 letters, 4 digits, 1 letter.
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
# Aadhaar-style 12-digit id (spaces optional), not amounts (those have decimals).
_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
# Any token the bank already partially masked with a run of X's — mask fully so
# the visible tail (…9953, …0068) cannot be correlated across the statement.
_MASKED = re.compile(r"\b[A-Za-z0-9.@]*[Xx]{3,}[A-Za-z0-9.@]*\b")
# A person's name following a title.  Name words are ALL-CAPS on these
# statements, so the match stops naturally at a Titlecase label like "My".
_NAME = re.compile(
    r"\b(Mr|Mrs|Ms|Dr|Shri|Smt|M/s)\.?\s+([A-Z]{2,}(?:\s+[A-Z]{2,}){0,3})")
# A long unmasked account / reference number sitting on a header line.
_LONG_NUM = re.compile(r"(?<![\d.,])\d{9,}(?![\d.,])")
# A 6-digit PIN code marks an address line (and usually the line above it too).
_PIN = re.compile(r"\b\d{6}\b")

REPLACEMENTS = [
    (_EMAIL, "[EMAIL]"),
    (_PAN, "[PAN]"),
    (_AADHAAR, "[ID]"),
    (_NAME, lambda m: f"{m.group(1)}. [NAME]"),
    (_MASKED, "[REDACTED]"),
]


# Street / locality words that mark an address line even without a PIN.
_STREET = re.compile(
    r"\b(SECTOR|FLOOR|ROAD|STREET|NAGAR|COLONY|BLOCK|LANE|MARG|GALI|PLOT|"
    r"HOUSE|FLAT|APARTMENT|APT|VILLAGE|POST|DISTRICT|TEHSIL|PIN)\b", re.I)


def _pin_line(line):
    """True if the line carries a 6-digit PIN code in an address-y context."""
    return bool(_PIN.search(line) and "," in line and re.search(r"[A-Z]{3,}", line))


def _street_line(line):
    """True if the line looks like a street address (number + street word)."""
    return bool(_STREET.search(line) and ("," in line or re.search(r"\d", line)))


def _label_address(line):
    return bool(re.match(r"\s*(My\s+)?Address\b", line, re.I))


def redact_text(text):
    """Return (redacted_text, counts) with identity fields removed.

    Transaction-style content (dates, amounts, descriptions) is preserved; only
    identity patterns and address lines are masked.
    """
    counts = {}
    lines = text.split("\n")

    # Address is multi-line and laid out unpredictably.  Mask a line if it has
    # a PIN, a street word, or an Address label — and the two lines above a PIN
    # line, since the street portion usually sits there.
    addr = set()
    for i, ln in enumerate(lines):
        if _pin_line(ln):
            addr.update({i, i - 1, i - 2} & set(range(len(lines))))
        elif _street_line(ln) or _label_address(ln):
            addr.add(i)
    for i in sorted(addr):
        counts["address"] = counts.get("address", 0) + 1
        lines[i] = "[ADDRESS REDACTED]"

    out = []
    for ln in lines:
        if ln == "[ADDRESS REDACTED]":
            out.append(ln)
            continue
        for pat, repl in REPLACEMENTS:
            ln, n = pat.subn(repl, ln)
            if n:
                counts[getattr(pat, "pattern", "?")[:12]] = \
                    counts.get(getattr(pat, "pattern", "?")[:12], 0) + n
        # Long unmasked numbers on non-transaction lines (no amount => header).
        if not re.search(r"\d[\d,]*\.\d{2}", ln):
            ln = _LONG_NUM.sub("[NUM]", ln)
        out.append(ln)

    return "\n".join(out), counts
