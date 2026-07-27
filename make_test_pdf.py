"""Throwaway generator: a realistic HDFC-style statement PDF for testing.

~400 rows over 9 months with a running-balance column, two date columns
(transaction + value date), monthly salary credits, fixed subscriptions and
randomised discretionary spending.  Deliberately includes the two nasty lines
the parser has to survive:

  * "CREDIT INTEREST CAPITALISED"  — the CR-in-CREDIT trap
  * "ACH D- HDFC MUTUAL FUND SIP"  — the single-letter-token trap

Returns (opening_balance, closing_balance) so the test can assert exact
reconciliation to the paisa.
"""

import os
import random

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

MONO = "Courier"


def _fmt(n):
    # Indian grouping with 2 decimals, e.g. 1,25,000.00
    neg = n < 0
    s = f"{abs(n):.2f}"
    intp, dec = s.split(".")
    if len(intp) > 3:
        head, tail = intp[:-3], intp[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        intp = ",".join(parts) + "," + tail
    out = f"{intp}.{dec}"
    return "-" + out if neg else out


DISCRETIONARY = [
    ("UPI-SWIGGY-ORDER", 180, 700), ("UPI-ZOMATO-DELIVERY", 200, 900),
    ("UPI-BLINKIT-GROCERY", 150, 1200), ("UPI-ZEPTO-STORE", 120, 800),
    ("UPI-UBER-INDIA", 90, 600), ("UPI-OLA-CABS", 100, 550),
    ("POS-AMAZON-RETAIL", 300, 4500), ("POS-FLIPKART-INTERNET", 250, 3800),
    ("UPI-BIGBASKET-BB", 400, 2500), ("POS-MYNTRA-FASHION", 500, 3000),
    ("UPI-RAPIDO-RIDE", 40, 200), ("POS-CROMA-ELECTRONICS", 800, 12000),
    ("UPI-APOLLO-PHARMACY", 120, 1500), ("UPI-IRCTC-RAIL", 300, 2200),
    ("ATM-CASH WDL-NWD", 1000, 8000),
]

FIXED_MONTHLY = [
    ("NACH-NETFLIX-SUBSCRIPTION", 199.00),
    ("NACH-SPOTIFY-INDIA", 119.00),
    ("ACH D- HDFC MUTUAL FUND SIP", 10000.00),
    ("NACH-NOBROKER-RENT-PAYMENT", 32000.00),
    ("BILLPAY-AIRTEL-POSTPAID", 799.00),
    ("EMI-BAJAJ FINANCE LOAN", 4500.00),
]


def generate(path="statements/test-hdfc.pdf", seed=42):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rng = random.Random(seed)
    opening = 125000.00
    balance = opening
    rows = []  # (txn_date, val_date, narration, debit, credit, balance)

    for month in range(1, 10):                      # Jan..Sep 2025
        # Salary credit at the start of the month.
        balance += 185000.00
        rows.append((f"01/{month:02d}/25", f"01/{month:02d}/25",
                     "NEFT-ACME TECHNOLOGIES-SALARY", None, 185000.00, balance))
        # Fixed subscriptions mid-month.
        for i, (narr, amt) in enumerate(FIXED_MONTHLY):
            day = 3 + i
            balance -= amt
            rows.append((f"{day:02d}/{month:02d}/25", f"{day:02d}/{month:02d}/25",
                         narr, amt, None, balance))
        # Quarterly bank interest credit — includes the CREDIT trap word.
        if month % 3 == 0:
            amt = round(rng.uniform(400, 900), 2)
            balance += amt
            rows.append((f"28/{month:02d}/25", f"28/{month:02d}/25",
                         "CREDIT INTEREST CAPITALISED", None, amt, balance))
        # Randomised discretionary spending.
        for _ in range(rng.randint(30, 36)):
            narr, lo, hi = rng.choice(DISCRETIONARY)
            amt = round(rng.uniform(lo, hi), 2)
            day = rng.randint(2, 27)
            balance -= amt
            rows.append((f"{day:02d}/{month:02d}/25", f"{day:02d}/{month:02d}/25",
                         narr, amt, None, balance))

    closing = balance

    # --- draw ---
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    x0, y = 30, height - 40

    def header():
        nonlocal y
        c.setFont(MONO, 9)
        c.drawString(x0, y, "HDFC BANK LTD - STATEMENT OF ACCOUNT"); y -= 14
        c.drawString(x0, y, "Account No: XXXXXXXX1234   IFSC: HDFC0000123"); y -= 14
        c.drawString(x0, y, f"Opening Balance : {_fmt(opening)}"); y -= 18
        c.setFont(MONO, 7)
        c.drawString(x0, y,
            f"{'Date':<9}{'ValueDt':<9}{'Narration':<34}"
            f"{'Withdrawal':>13}{'Deposit':>13}{'Balance':>15}")
        y -= 12

    header()
    c.setFont(MONO, 7)
    for (td, vd, narr, dr, cr, bal) in rows:
        if y < 60:
            c.showPage(); y = height - 40; header(); c.setFont(MONO, 7)
        line = (f"{td:<9}{vd:<9}{narr[:33]:<34}"
                f"{(_fmt(dr) if dr else ''):>13}"
                f"{(_fmt(cr) if cr else ''):>13}"
                f"{_fmt(bal):>15}")
        c.drawString(x0, y, line); y -= 11

    if y < 60:
        c.showPage(); y = height - 40
    c.setFont(MONO, 9)
    y -= 8
    c.drawString(x0, y, f"Closing Balance : {_fmt(closing)}")
    c.save()
    return opening, closing, len(rows)


if __name__ == "__main__":
    o, cl, n = generate()
    print(f"opening={_fmt(o)} closing={_fmt(cl)} rows={n}")
