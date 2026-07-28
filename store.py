"""The transactions.csv store: read, merge, write.

Kept tiny and dependency-free.  The interesting part is the merge: re-importing
a statement you already loaded must not double every row, but two genuinely
distinct payments that happen to share a day, amount and description must both
survive.  So the merge dedupes by *multiplicity* — it skips an incoming row only
while the store still has an un-accounted occurrence of the same key.
"""

import csv
from collections import Counter

FIELDS = ["date", "description", "amount", "confidence"]


def read_records(path):
    """Read transactions.csv into a list of dict records (empty if missing)."""
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return [{k: row.get(k, "") for k in FIELDS}
                    for row in csv.DictReader(fh)]
    except FileNotFoundError:
        return []


def rows_to_records(rows):
    """Turn extractor Row objects into CSV records."""
    out = []
    for r in rows:
        signed = r.signed if r.signed is not None else 0.0
        out.append({"date": r.date, "description": r.description,
                    "amount": f"{signed:.2f}", "confidence": r.confidence or "low"})
    return out


def _key(rec):
    return (rec["date"], rec["amount"], rec["description"])


def merge(existing, incoming):
    """Merge incoming records into existing, deduping by multiplicity.

    Returns (merged, n_added, n_skipped).  An incoming row is skipped only while
    the store still holds an un-matched occurrence of its (date, amount,
    description) key — so re-importing the same statement adds nothing, but
    distinct same-key rows in a fresh statement are all kept.
    """
    have = Counter(_key(r) for r in existing)
    seen = Counter()
    added, skipped = [], 0
    for rec in incoming:
        k = _key(rec)
        if seen[k] < have[k]:
            skipped += 1              # re-import of a row already stored
        else:
            added.append(rec)
        seen[k] += 1
    merged = existing + added
    merged.sort(key=lambda r: r["date"])   # stable: keeps within-day order
    return merged, len(added), skipped


def write_records(records, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(records)
