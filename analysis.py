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


def spending_insights(txns):
    """Second-order patterns the raw totals don't show.

    All derived from amounts, dates and descriptions in the CSV — no balance
    column needed (see balance_health for that).  Returns a plain dict so the
    digest and report can present the same numbers.
    """
    import datetime
    debits = [t for t in txns if t["amount"] < 0]
    credits = [t for t in txns if t["amount"] > 0]
    outs = sorted((abs(t["amount"]) for t in debits), reverse=True)
    gross_out = sum(outs)
    gross_in = sum(t["amount"] for t in credits)

    # Concentration (Pareto): what share of outflow the biggest few debits are.
    pareto = {}
    for k in (3, 5, 10):
        if outs:
            pareto[k] = round(sum(outs[:k]) / gross_out * 100) if gross_out else 0

    # Counterparty concentration.
    payees = {}
    for t in debits:
        payees.setdefault(t["merchant"], []).append(abs(t["amount"]))
    distinct = len(payees)
    repeat = sum(1 for v in payees.values() if len(v) >= 2)
    top_merchants = sorted(((m, sum(v), len(v)) for m, v in payees.items()),
                           key=lambda x: -x[1])[:8]

    # Weekday rhythm.
    weekday = {d: [0, 0.0] for d in
               ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
    byday = {}
    for t in debits:
        try:
            wd = datetime.date.fromisoformat(t["date"]).strftime("%a")
        except ValueError:
            continue
        weekday[wd][0] += 1
        weekday[wd][1] += abs(t["amount"])
        byday[t["date"]] = byday.get(t["date"], 0.0) + abs(t["amount"])
    biggest_day = max(byday.items(), key=lambda x: x[1]) if byday else (None, 0)

    # Round-number debits (often person-to-person / lending, not merchants).
    round100 = [a for a in outs if a >= 100 and a % 100 == 0]
    # Tiny pings = UPI mandate / autopay verification.
    pings = sum(1 for t in txns if abs(t["amount"]) <= 2)

    return {
        "n_debits": len(debits), "n_credits": len(credits),
        "gross_out": gross_out, "gross_in": gross_in,
        "throughput": gross_in + gross_out,
        "pareto": pareto,
        "distinct_payees": distinct, "repeat_payees": repeat,
        "top_merchants": top_merchants,
        "weekday": weekday, "biggest_day": biggest_day,
        "round100_n": len(round100), "round100_total": sum(round100),
        "autopay_pings": pings,
    }


def balance_health(rows):
    """Cash-flow health from the running balance (extract-stage only).

    ``rows`` are extractor Row objects with .balance; splits by account at a
    genuine balance discontinuity and reports the low-water mark of each.
    """
    from extractor import _continues
    accounts, cur, prev = [], [], None
    for r in rows:
        if r.new_section and prev is not None and not _continues(prev, r):
            accounts.append(cur)
            cur = []
        cur.append(r)
        if r.balance is not None:
            prev = r.balance
    if cur:
        accounts.append(cur)

    out = []
    for a in accounts:
        bals = [(r.date, r.balance) for r in a if r.balance is not None]
        if not bals:
            continue
        low = min(bals, key=lambda x: x[1])
        end = bals[-1][1]
        ins = sum(r.signed for r in a if r.signed and r.signed > 0)
        outs = sum(-r.signed for r in a if r.signed and r.signed < 0)
        out.append({"txns": len(a), "low_date": low[0], "low_balance": low[1],
                    "end_balance": end, "in": ins, "out": outs,
                    "throughput": ins + outs,
                    "churn": (ins + outs) / max(end, 1)})
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
