"""`--summary` : write digest.md, safe to paste into an external model.

Merchant names, dates, reference numbers and account details are stripped.
What remains is category totals per month and recurring commitments described
only by category, cadence and amount — the shape of the spending, none of the
identity.
"""

from analysis import monthly_category_totals, detect_recurring


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

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path
