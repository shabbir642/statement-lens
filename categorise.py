"""Direction-aware categorisation of transactions.

Categorisation is a plain keyword file the user edits.  There is no model and
no cleverness beyond substring matching — every classification can be checked
by eye against ``categories.json``.

Two facts make it direction-aware (trap #3):

* A credit whose description contains ``neft`` is salary, not a transfer out.
  So for money coming in we check the Income rules *first* and never let an
  outflow-only rule claim it.
* Some categories only make sense for money going out (rent, EMI, fees, cash
  withdrawal, transfers out).  Those are skipped entirely for credits.
"""

import json
import os
import re

CATEGORIES_PATH = "categories.json"

# Categories that only apply to money going OUT.  A positive amount is never
# put in one of these, no matter what the description says.
OUTFLOW_ONLY = {
    "Transfers Out",
    "Cash Withdrawal",
    "Fees & Charges",
    "EMI & Loans",
    "Rent",
    "UPI Merchant/QR",
    "UPI Payment",
}

# The single inflow category.  Checked first for credits, never for debits.
INCOME_CATEGORY = "Income"

# Written verbatim to categories.json on first run.  Lowercase substrings.
#
# Order matters: the FIRST matching category wins (Income is always tried first
# for credits).  So specific rules — brands, QR-merchant markers — come before
# the broad "UPI Payment" / "UPI Received" catch-alls at the very end, which
# sweep up whatever UPI traffic no specific rule claimed.  On UPI-heavy Indian
# accounts most debits are payments, not "transfers", so bare "upi" must NOT
# live under Transfers Out (that silently mislabels everyday spending).
DEFAULT_CATEGORIES = {
    "Income": ["salary", "REMOVED", "neft cr", "imps cr", "int.pd", "interest",
               "int credit", "interest credit", "dividend", "refund",
               "cashback", "cash back", "reversal", "credited by"],
    "Food Delivery": ["swiggy", "zomato", "eatclub", "faasos", "box8"],
    "Groceries": ["blinkit", "zepto", "bigbasket", "big basket", "dmart",
                  "d mart", "grofers", "instamart", "jiomart", "reliance fresh"],
    "Transport": ["uber", "ola", "rapido", "irctc", "redbus", "blu smart",
                  "blusmart", "metro", "namma yatri"],
    "Fuel": ["hp ", "hpcl", "iocl", "indian oil", "bharat petroleum", "bpcl",
             "shell", "fuel", "petrol"],
    "Utilities": ["bses", "tata power", "adani electricity", "airtel", "jio",
                  "vodafone", "vi ", "act fibernet", "gas", "electricity",
                  "broadband", "water bill", "mahanagar gas"],
    "Health": ["apollo", "1mg", "pharmeasy", "netmeds", "cultfit", "cult.fit",
               "medplus", "practo", "tata 1mg", "max healthcare", "fortis"],
    "Subscriptions": ["netflix", "spotify", "prime video", "hotstar", "disney",
                      "youtube premium", "apple.com/bill", "google one",
                      "icloud", "sony liv", "zee5"],
    "Investments": ["groww", "zerodha", "sip", "mutual fund", "mf ",
                    "coin", "kuvera", "indmoney", "smallcase", "nps",
                    "ppf", "elss"],
    "Rent": ["nobroker", "rent", "rental", "housing.com", "lease"],
    "Shopping": ["amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho",
                 "tata cliq", "croma", "reliance digital", "decathlon"],
    "EMI & Loans": ["emi", "loan", "bajaj finance", "hdfc loan", "credit card",
                    "cc payment", "cred.club"],
    "Cash Withdrawal": ["atm", "cash wdl", "cash withdrawal", "nwd", "eaw",
                        "atw", "cwdr"],
    "Fees & Charges": ["service charge", "sms alert", "annual fee", "penalty",
                       "amc", "processing fee", "gst", "cgst", "sgst", "igst"],
    # NACH/ACH auto-debit mandates that carry no brand of their own (a branded
    # one — NACH-NETFLIX, ACH … MUTUAL FUND SIP — is claimed by the category
    # above, since first match wins and those rules come first).
    "Mandate": ["nach-", "nach ", "ach d-", "ach c-", "ach dr", "ach cr",
                "e-mandate", "emandate", "enach", "indian clearing corp",
                "clearing corp", "mandate"],
    # QR / aggregator merchant payments — money spent at a shop, not a transfer.
    "UPI Merchant/QR": ["bharatpe", "paytmqr", "paytm.q", "razorpay", "cashfree",
                        "payu", "billdesk", "ccavenue", "pinelabs", "phonepe.qr",
                        "@rzp", "okbizaxis"],
    # Explicit bank transfers (NEFT/RTGS/IMPS out, named transfers).
    "Transfers Out": ["neft dr", "imps dr", "rtgs", "transfer to", "sent to",
                      "self", "own account"],
    # Catch-alls, tried last: leftover UPI traffic no specific rule claimed.
    "UPI Payment": ["upi/dr", "upi-dr", "upi/p2m", "upi", "vpa"],
    "UPI Received": ["upi/cr", "upi-cr", "upi"],
}


def ensure_categories_file(path=CATEGORIES_PATH):
    """Write the starter categories.json on first run; return the loaded map."""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_CATEGORIES, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def categorise(description, amount, categories):
    """Return (category, matched_keyword) for one transaction.

    ``amount`` is signed: negative is money out.  Returns ("Uncategorised",
    None) when nothing matches.
    """
    text = (description or "").lower()
    is_credit = amount is not None and amount > 0

    def first_hit(name):
        for kw in categories.get(name, []):
            if kw in text:
                return kw
        return None

    if is_credit:
        # Income rules win for money coming in.
        kw = first_hit(INCOME_CATEGORY)
        if kw:
            return INCOME_CATEGORY, kw
        for name in categories:
            if name == INCOME_CATEGORY or name in OUTFLOW_ONLY:
                continue
            kw = first_hit(name)
            if kw:
                return name, kw
        return "Uncategorised", None

    # Money going out: skip the Income category.
    for name in categories:
        if name == INCOME_CATEGORY:
            continue
        kw = first_hit(name)
        if kw:
            return name, kw
    return "Uncategorised", None


_REF_RE = re.compile(r"\b[\dxX*]{6,}\b")          # long ref / masked card numbers
# Mixed alphanumeric refs (transaction IDs like 0000SWV7WAFQ, account tails like
# HDFCH01066840361).  A 6+ char token that contains at least one digit is a
# reference, never a merchant word — dropping it lets otherwise-identical rows
# (same payee, different ref) collapse to one key so recurring detection sees them.
_ALNUM_REF_RE = re.compile(r"\b(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{6,}\b")
_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_UPI_TAIL = re.compile(r"@[a-z]+", re.I)          # upi handle suffix
_NONWORD = re.compile(r"[^A-Za-z0-9&/ ]+")


def normalise_merchant(description):
    """Collapse a raw description into a stable merchant key for grouping.

    Drops single-letter tokens so ``ACH D- HDFC MUTUAL FUND SIP`` groups as
    ``HDFC MUTUAL FUND SIP`` and not ``D HDFC MUTUAL FUND``.
    """
    text = description or ""
    text = _DATE_RE.sub(" ", text)
    text = _REF_RE.sub(" ", text)
    text = _ALNUM_REF_RE.sub(" ", text)
    text = _UPI_TAIL.sub(" ", text)
    text = _NONWORD.sub(" ", text)
    tokens = [t for t in text.upper().split() if len(t) > 1]
    # Long glued merchant names get truncated at different widths by different
    # systems (e.g. MERCHANT vs MERCHANT), which would
    # otherwise split one payee into two groups.  Cap each token so the
    # variants collapse to the same key.
    tokens = [t[:15] for t in tokens]
    # Keep it short: first handful of meaningful tokens is enough to group by.
    key = " ".join(tokens[:5]).strip()
    return key or (description or "").strip().upper()[:40] or "UNKNOWN"
