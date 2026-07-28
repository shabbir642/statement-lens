"""Rule-based alerts — deterministic warnings, no LLM.

Turns the raw metrics into plain-English flags a person would actually act on.
Every rule is arithmetic over the transactions or the running balance, so the
same input always yields the same alerts. Levels: 'high' (act now), 'warn',
'info'. Each alert is a dict {level, msg}.
"""

import statistics
from collections import defaultdict

from analysis import spending_insights, detect_outliers

_ORDER = {"high": 0, "warn": 1, "info": 2}


def _sorted(alerts):
    return sorted(alerts, key=lambda a: _ORDER.get(a["level"], 3))


def spending_alerts(txns):
    """Alerts derivable from the CSV (amounts, dates, categories)."""
    alerts = []
    real = [t for t in txns if not t.get("internal")]
    if not real:
        return alerts
    ins = spending_insights(txns)
    gross_out = ins["gross_out"]
    net = sum(t["amount"] for t in real)

    if net < 0:
        alerts.append({"level": "warn",
                       "msg": f"Net negative: Rs {-net:,.0f} more went out than came in."})

    p10 = ins["pareto"].get(10)
    if p10 and p10 >= 85:
        alerts.append({"level": "warn",
                       "msg": f"Spending is highly concentrated — the top 10 debits are {p10}% of all outflow."})
    elif p10 and p10 >= 70:
        alerts.append({"level": "info",
                       "msg": f"Top 10 debits are {p10}% of outflow — a few payments dominate."})

    review = sum(abs(t["amount"]) for t in real
                 if t["amount"] < 0 and t["category"] in
                 ("Uncategorised", "UPI Payment"))
    if gross_out and review / gross_out >= 0.30:
        alerts.append({"level": "info",
                       "msg": f"{review / gross_out * 100:.0f}% of spend is uncategorised / generic UPI — add rules in categories.json to see where it goes."})

    lowc = sum(1 for t in txns if t.get("confidence") == "low")
    if lowc:
        alerts.append({"level": "info",
                       "msg": f"{lowc} row(s) are low-confidence — verify them in transactions.csv before trusting the totals."})

    outliers = detect_outliers(real)
    if outliers:
        b = outliers[0]
        alerts.append({"level": "info",
                       "msg": f"{len(outliers)} transaction(s) are outliers for their category (largest Rs {abs(b['amount']):,.0f} in {b['category']})."})

    if ins["autopay_pings"]:
        alerts.append({"level": "info",
                       "msg": f"{ins['autopay_pings']} tiny (<= Rs 2) verify pings — check which autopay mandates are active."})

    # Month-over-month, only with enough history.
    spend_by = defaultdict(float)
    for t in real:
        if t["amount"] < 0 and t["month"]:
            spend_by[t["month"]] += abs(t["amount"])
    months = sorted(spend_by)
    if len(months) >= 3:
        last = spend_by[months[-1]]
        prior = statistics.median(spend_by[m] for m in months[:-1])
        if prior and last > prior * 1.25:
            alerts.append({"level": "warn",
                           "msg": f"Latest month spend (Rs {last:,.0f}) is {(last / prior - 1) * 100:.0f}% above your median month."})
        elif prior and last < prior * 0.6:
            alerts.append({"level": "info",
                           "msg": f"Latest month spend (Rs {last:,.0f}) is well below your median — possibly a partial statement."})

    return _sorted(alerts)


def balance_alerts(health):
    """Alerts from the running balance (extract-stage only)."""
    alerts = []
    multi = len(health) > 1
    for i, h in enumerate(health, 1):
        tag = f"Account {i}" if multi else "Account"
        if h.get("low_before_big"):
            alerts.append({"level": "high",
                           "msg": f"{tag}: balance ran down to Rs {h['low_balance']:,.0f} on {h['low_date']}, days before a Rs {h['big_debit_amt']:,.0f} debit on {h['big_debit_date']} — fund it ahead of large payments."})
        elif h["low_balance"] < 1000:
            alerts.append({"level": "warn",
                           "msg": f"{tag} fell to Rs {h['low_balance']:,.0f} on {h['low_date']} — thin buffer."})
        if h["churn"] >= 10:
            alerts.append({"level": "info",
                           "msg": f"{tag} churned {h['churn']:.0f}x its ending balance — largely a pass-through account."})
    return _sorted(alerts)
