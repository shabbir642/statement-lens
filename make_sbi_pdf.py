"""Throwaway generator: a synthetic SBI-netbanking-style statement.

Reproduces — with NO real data — the exact things that broke the first parser
on a real SBI statement, so they stay fixed:

  * two accounts in one PDF, each with its own header and closing balance
  * long UPI narrations that wrap onto their own line above the amounts
  * "Credit Debit Balance" columns with a "-" ref and a "0" placeholder column
  * garbled "Opening Balance … : amount null null null null" summary lines

Returns a dict of expectations the test asserts against.
"""

import os
import random

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

MONO = "Courier"
NAMES = ["MOHD SAK", "RAJ KUMAR", "VED PRAK", "Shivkumar", "NIRAJ K",
         "ASHISH K", "Ganga Pr", "MAISAM A", "FEROZ A", "Sonu Kh"]
BANKS = ["YESB", "SBIN", "PUNB", "UTIB", "HDFC", "BARB"]
VPAS = ["paytm.s2ez", "paytmqr6qh", "bharatpe.9", "gpay-12193", "q137132835",
        "cashfreepd", "okbizaxis", "9716429013"]

WRAP_TOKEN = "wrapcheckvpa"   # sentinel: proves a wrapped narration survived


def _fmt(n):
    return f"{n:,.2f}"


def generate(path="statements/test-sbi.pdf", seed=7):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rng = random.Random(seed)
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    x0 = 30
    y = [height - 40]
    total = 0
    accounts = []

    def line(txt, font=7):
        if y[0] < 60:
            c.showPage()
            y[0] = height - 40
            _hdr()
        c.setFont(MONO, font)
        c.drawString(x0, y[0], txt)
        y[0] -= 11

    def _hdr():
        c.setFont(MONO, 7)
        c.drawString(x0, y[0], "Date Transaction Reference Ref.No./Chq.No. "
                               "Credit Debit Balance")
        y[0] -= 12

    for acct in range(2):
        opening = round(rng.uniform(3000, 12000), 2)
        bal = opening
        # Garbled opening-balance summary line (the pdfplumber interleaving).
        line(f"Yourn Oupllening nBualllance on 01-06-26: {_fmt(opening)} "
             f"null null null null")
        _hdr()
        n = rng.randint(34, 42)
        for i in range(n):
            is_credit = rng.random() < 0.2
            amt = round(rng.uniform(20, 3000), 2)
            if not is_credit:
                amt = min(amt, round(bal - 100, 2))  # keep balance positive
            bal = round(bal + amt if is_credit else bal - amt, 2)
            day = min(28, 1 + (i * 27) // n)
            date = f"{day:02d}-06-26"
            name = rng.choice(NAMES)
            bank = rng.choice(BANKS)
            vpa = WRAP_TOKEN if (acct == 0 and i == 3) else rng.choice(VPAS)
            ref = rng.randint(10 ** 11, 10 ** 12 - 1)
            desc = f"UPI/{'CR' if is_credit else 'DR'}/{ref}/{name}/{bank}/{vpa}/Paid"
            cr = _fmt(amt) if is_credit else "0"
            dr = "0" if is_credit else _fmt(amt)
            wrapped = (acct == 0 and i == 3) or rng.random() < 0.4
            if wrapped:                      # narration on its own line first
                line(desc)
                line(f"{date} - {cr} {dr} {_fmt(bal)}")
            else:
                line(f"{date} {desc} - {cr} {dr} {_fmt(bal)}")
            total += 1
        line(f"Your Closing Balance on 30-06-26: {_fmt(bal)}", font=8)
        accounts.append({"opening": opening, "closing": bal, "txns": n})

    c.save()
    return {"path": path, "accounts": accounts, "total": total,
            "wrap_token": WRAP_TOKEN}


if __name__ == "__main__":
    print(generate())
