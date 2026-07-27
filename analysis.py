"""Shared arithmetic over the approved CSV.

Everything here is plain arithmetic the user can check by hand: monthly totals,
recurring-commitment detection, and outlier flagging.  The HTML report
re-implements the same logic in JavaScript so it can react to filters; this
module is what the Markdown digest is built from.
"""

import csv
import statistics
from collections import defaultdict

from categorise import categorise, normalise_merchant


def load_transactions(csv_path, categories):
    """Read the reviewed CSV and attach category + merchant to each row."""
    txns = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                amount = float(row["amount"])
            except (KeyError, ValueError):
                continue
            desc = row.get("description", "")
            cat, kw = categorise(desc, amount, categories)
            txns.append({
                "date": row.get("date", ""),
                "month": (row.get("date", "") or "")[:7],
                "description": desc,
                "amount": amount,
                "confidence": row.get("confidence", ""),
                "category": cat,
                "matched": kw,
                "merchant": normalise_merchant(desc),
            })
    return txns


def monthly_category_totals(txns):
    """{month: {category: signed_total}} and a sorted list of months."""
    totals = defaultdict(lambda: defaultdict(float))
    for t in txns:
        if t["month"]:
            totals[t["month"]][t["category"]] += t["amount"]
    months = sorted(totals)
    return totals, months


def _median_gap_days(dates):
    """Median gap in days between sorted ISO dates."""
    import datetime
    ds = sorted(datetime.date.fromisoformat(d) for d in dates if d)
    if len(ds) < 2:
        return None
    gaps = [(ds[i] - ds[i - 1]).days for i in range(1, len(ds))]
    return statistics.median(gaps)


def _cadence(gap_days):
    """Map a median day-gap to a human cadence + annual multiplier."""
    if gap_days is None:
        return None, 0
    buckets = [
        ("weekly", 7, 52), ("fortnightly", 14, 26), ("monthly", 30, 12),
        ("quarterly", 91, 4), ("half-yearly", 182, 2), ("yearly", 365, 1),
    ]
    best = min(buckets, key=lambda b: abs(gap_days - b[1]))
    # Only call it regular if it is within 35% of a known cadence.
    if abs(gap_days - best[1]) <= 0.35 * best[1]:
        return best[0], best[2]
    return None, 0


def detect_recurring(txns, min_occurrences=3):
    """Find repeated merchant + stable amount + regular gap.

    Returns a list of dicts with a 'stability' score: the share of occurrences
    whose amount is within 2% of the median.  We report the score rather than
    tuning it away — 100% is a real subscription, 40% is coincidence.
    """
    groups = defaultdict(list)
    for t in txns:
        if t["amount"] < 0:                       # commitments are outflows
            groups[t["merchant"]].append(t)

    out = []
    for merchant, items in groups.items():
        if len(items) < min_occurrences:
            continue
        amounts = [abs(t["amount"]) for t in items]
        median_amt = statistics.median(amounts)
        if median_amt == 0:
            continue
        within = sum(1 for a in amounts if abs(a - median_amt) <= 0.02 * median_amt)
        stability = within / len(amounts)
        gap = _median_gap_days([t["date"] for t in items])
        cadence, annual_mult = _cadence(gap)
        if not cadence:
            continue
        out.append({
            "merchant": merchant,
            "category": items[0]["category"],
            "occurrences": len(items),
            "median_amount": median_amt,
            "stability": stability,
            "cadence": cadence,
            "gap_days": gap,
            "annualised": median_amt * annual_mult,
            "dates": sorted(t["date"] for t in items),
        })
    out.sort(key=lambda r: r["annualised"], reverse=True)
    return out


def detect_outliers(txns, mad_k=4.0):
    """Flag transactions large relative to their OWN category (median + k*MAD).

    Uses the median absolute deviation so a normal rent payment does not flag
    but a 5x grocery bill does.
    """
    by_cat = defaultdict(list)
    for t in txns:
        if t["amount"] < 0:
            by_cat[t["category"]].append(t)
    flagged = []
    for cat, items in by_cat.items():
        vals = [abs(t["amount"]) for t in items]
        if len(vals) < 4:
            continue
        med = statistics.median(vals)
        mad = statistics.median([abs(v - med) for v in vals]) or 1e-9
        threshold = med + mad_k * mad
        for t in items:
            if abs(t["amount"]) > threshold:
                flagged.append({**t, "cat_median": med,
                                "threshold": threshold})
    flagged.sort(key=lambda t: abs(t["amount"]), reverse=True)
    return flagged
