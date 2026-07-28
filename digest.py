"""`--summary` : write digest.md, safe to paste into an external model.

Merchant names, dates, reference numbers and account details are stripped.
What remains is category totals per month and recurring commitments described
only by category, cadence and amount — the shape of the spending, none of the
identity.
"""

from analysis import (monthly_category_totals, detect_recurring,
                      spending_insights)


def _fmt(n):
    return f"Rs {n:,.2f}"


def write_digest(txns, path="digest.md"):
    totals, months = monthly_category_totals(txns)
    categories = sorted({c for m in totals.values() for c in m})

    lines = ["# Spending digest", ""]
    lines.append("_Anonymised: no merchant names, dates, reference numbers or "
                 "account details. Safe to paste into an external tool._")
    lines.append("")

    # --- category totals per month (as a table) ---
    lines.append("## Category totals per month")
    lines.append("")
    header = "| Category | " + " | ".join(months) + " |"
    sep = "| --- " * (len(months) + 1) + "|"
    lines.append(header)
    lines.append(sep)
    for cat in categories:
        cells = [f"{totals[m].get(cat, 0.0):,.0f}" for m in months]
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    # Net row
    net = [sum(totals[m].values()) for m in months]
    lines.append("| **Net** | " + " | ".join(f"{v:,.0f}" for v in net) + " |")
    lines.append("")

    # --- recurring commitments (no merchant names) ---
    recurring = detect_recurring(txns)
    lines.append("## Recurring commitments (anonymised)")
    lines.append("")
    if not recurring:
        lines.append("_None detected._")
    else:
        lines.append("| # | Category | Cadence | Typical amount | "
                     "Stability | Annualised |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for i, r in enumerate(recurring, 1):
            lines.append(
                f"| {i} | {r['category']} | {r['cadence']} | "
                f"{_fmt(r['median_amount'])} | {r['stability'] * 100:.0f}% | "
                f"{_fmt(r['annualised'])} |")
    lines.append("")

    # --- second-order insights (all anonymised aggregates) ---
    ins = spending_insights(txns)
    lines.append("## Spending insights (anonymised)")
    lines.append("")
    lines.append(f"- **Throughput:** Rs {ins['throughput']:,.0f} moved "
                 f"(in Rs {ins['gross_in']:,.0f} / out Rs {ins['gross_out']:,.0f}) "
                 f"across {ins['n_debits']} debits and {ins['n_credits']} credits.")
    if ins["pareto"]:
        p = ins["pareto"]
        lines.append(f"- **Concentration:** the top 3 debits are "
                     f"{p.get(3, 0)}% of all outflow; top 10 are {p.get(10, 0)}%.")
    lines.append(f"- **Counterparties:** {ins['distinct_payees']} distinct "
                 f"payees, {ins['repeat_payees']} seen more than once "
                 f"(a high distinct count = mostly one-off payments).")
    if ins["biggest_day"][0]:
        lines.append(f"- **Biggest single day:** Rs "
                     f"{ins['biggest_day'][1]:,.0f}.")
    lines.append(f"- **Round-number debits:** {ins['round100_n']} totalling "
                 f"Rs {ins['round100_total']:,.0f} (often person-to-person).")
    lines.append(f"- **Autopay/verify pings (<= Rs 2):** {ins['autopay_pings']} "
                 f"— check what mandates are authorised.")
    wk = ins["weekday"]
    busiest = max(wk.items(), key=lambda x: x[1][1])
    lines.append(f"- **Busiest weekday by spend:** {busiest[0]} "
                 f"(Rs {busiest[1][1]:,.0f}).")
    internal = [t for t in txns if t.get("internal") and t["amount"] < 0]
    if internal:
        tot = sum(abs(t["amount"]) for t in internal)
        lines.append(f"- **Internal transfers netted out:** {len(internal)} "
                     f"pairs, Rs {tot:,.0f} moved between own accounts (not "
                     f"counted as spend or income).")
    lines.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path
