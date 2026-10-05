"""Turning the customer name as typed at the till into the customer's name.

Attendants note how a sale was paid inside the customer name — "Ali(KCB)",
"Anne -PDQ", "Evans S.pay", "Mukinya[I&M BANK]", "JAIRO (prepayment
fulfilled)" — and sometimes the person is the part in brackets: "KCB (Emily)",
"ncba(brian)". Removing every bracket left those as nothing and the
Customers page showed N/A. So:

  1. split off what is in brackets;
  2. drop payment and banking words, amounts and stray characters;
  3. use what is left outside the brackets; if nothing is, use a bracket
     that names a person;
  4. tidy the result: letters, apostrophes (Ndung'u) and single spaces only.
"""
from __future__ import annotations

import re

# Payment methods, banks and till notes that get typed into the name.
_NOT_A_NAME = [
    r"prepayments?", r"fulfill?(?:ed)?", r"full?fill?(?:ed)?", r"fulfil", r"pre\s*pay(?:ment)?",
    r"sasa\s*pay", r"s\.?\s*pay", r"\bsp\b", r"\bpdq\b", r"\bcash\b", r"\btill\b", r"\bkcb\b",
    r"\bncba\b", r"\bco-?op\b", r"\bcoop\b", r"\bi\s*(?:&|and)\s*m\b(?:\s*bank)?",
    r"\bequity\b", r"\bfamily\s*bank\b", r"\bchoice\s*bank\b", r"\bairtel\b",
    r"\bm-?pesa\b", r"\bgift\s*pesa\b", r"\bgiftpesa\b", r"\bprompted\b", r"\bbank\b",
    r"\bpayments?\b", r"ful+f[iu]+l+(?:ed|led|lled)?",
    r"\bstanbic\b", r"\bco\s*-?\s*op(?:erative)?\b",
    r"\bi\s*(?:&|and|n)?\s*m\b", r"\bloop\s*b2c\b", r"\bb2c\b",
    r"\bmombo\s*savings\b", r"\bsavings\b", r"\bcard\b", r"\bvisa\b",
]
_NOT_A_NAME_RE = re.compile("|".join(_NOT_A_NAME), re.IGNORECASE)
_BRACKETS = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")


def _strip(text: str) -> str:
    """Remove payment words, amounts and anything that is not part of a name."""
    text = _NOT_A_NAME_RE.sub(" ", text)
    text = re.sub(r"(^|\s)0(?=[A-Za-z])", r"\1O", text)   # "0kumu" typed for "Okumu"
    text = re.sub(r"[/,;&+|]", " ", text)          # "Jane/judy", "Judy,mercy"
    text = re.sub(r"[^A-Za-z' ]", " ", text)       # digits, -, ., [, ], *, ...
    text = re.sub(r"(^|\s)'+|'+(\s|$)", " ", text)  # stray apostrophes, keep Ndung'u
    return re.sub(r"\s+", " ", text).strip()


def _title(text: str) -> str:
    """Title case that leaves the letter after an apostrophe small: Ng'ang'a."""
    return " ".join(w[:1].upper() + w[1:].lower() for w in text.split())


def clean(raw) -> str:
    if raw is None:
        return "N/A"
    raw = str(raw)
    inside = _BRACKETS.findall(raw)
    outside = _strip(_BRACKETS.sub(" ", raw))
    if outside:
        return _title(outside)
    for part in inside:
        name = _strip(part)
        if name:
            return _title(name)
    return "N/A"
