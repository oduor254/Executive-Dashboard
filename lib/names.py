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

import pandas as pd
import streamlit as st

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


# ---------------------------------------------------------------------------
# Misspelt first names
#
# Attendants type fast: "Meercy", "Briyan", "Caherine", "Fairh". Across the
# 290,000 customers with a sale (Oct 2026), 17,000 first names occur only once,
# and a few thousand of those are one slip away from a common name. A typed
# name is taken as a misspelling only when ALL of these hold, because plenty
# of rare names are real (Gary is not Mary, Merry is not Mercy, Alfreda is not
# Alfred):
#   * it occurs 3 times or fewer and has 4+ letters;
#   * it is not a name in its own right (_REAL_NAMES; a name in the gender
#     list must share the common name's gender and be 100x rarer);
#   * one letter missing, extra, swapped with its neighbour or mistyped turns
#     it into a common name (30+ customers, 20x as many as the typed form).
#     The first letter must stay (Kane/Jane, Wick/Nick, Mendy/Wendy are
#     names), and four-letter names may only gain or lose a letter;
#   * only one common name is that close (Marie: Mary or Maria? — left alone);
#   * the customer's recorded gender doesn't contradict the suggestion.
# ---------------------------------------------------------------------------
_COMMON_MIN = 30
_COMMON_RATIO = 20
_RARE_MAX = 3
_LISTED_RATIO = 100
_LETTERS = "abcdefghijklmnopqrstuvwxyz"
# Real names one letter from a commoner one, never "corrected".
_REAL_NAMES = {"gary", "merry", "marty", "marg", "mara", "maria", "marie", "mario", "kane",
               "wick", "mendy", "sonny", "tony", "kute", "mura", "norean", "alfreda",
               "fabia", "silva", "martie", "jessen", "kendie", "bryan", "brain", "ann",
               "anne", "joan", "john", "jean", "janet", "jane", "dennis", "denis",
               "steven", "stephen", "allan", "alan", "ian", "eric", "erick", "erik",
               "mutoni", "jabes", "jabez", "joana", "alban", "alisha", "janie", "jamilah",
               "leonardo", "meshach", "musab", "salif", "sheela", "eliab", "atanda", "hendry",
               "christin", "dianna", "dian", "otondi", "rushid", "margy", "nicki", "annex",
               "mofile", "morah", "neri", "sabrah", "roben", "kayte", "vela", "clarks",
               "elis", "even", "elosi", "sherah", "mathia", "lorren", "alica", "magrine",
               "belly", "jessa", "nanny", "loiza"}

_CUSTOMER_NAMES = """
SELECT rp.name
FROM res_partner rp
WHERE EXISTS (SELECT 1 FROM pos_order po WHERE po.partner_id = rp.id)
"""


def _one_slip(word: str) -> set[str]:
    """Names one typing slip away from `word`. The first letter stays, and so
    does the last: real variants differ most often at the end (Joana/Joan,
    Nicki/Nick, Salif/Salim, Caled/Caleb) and can't be told from typos."""
    splits = [(word[:i], word[i:]) for i in range(1, len(word))]   # never at either end
    out = {a + b[1:] for a, b in splits if len(b) > 1}                  # extra letter
    out |= {a + ch + b for a, b in splits for ch in _LETTERS}           # missing letter
    out |= {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1}   # swapped
    if len(word) > 4:
        out |= {a + ch + b[1:] for a, b in splits if len(b) > 1 for ch in _LETTERS}  # wrong letter
        out |= {ch + word for ch in _LETTERS}                           # first letter dropped
    out.discard(word)
    return out


@st.cache_data(ttl=86400, show_spinner=False)
def spelling_suggestions() -> dict[str, str]:
    """Typed first name (lower case) -> the common name it is a slip of."""
    from lib import db, gender
    rows = db.run_query(_CUSTOMER_NAMES)
    if rows.empty:
        return {}
    first = rows["name"].map(clean).str.split().str[0].str.lower()
    freq = first[first.notna() & (first != "n/a")].value_counts()
    common = freq[freq >= _COMMON_MIN]
    lookup = gender._load_lookup()

    out = {}
    for typed, times in freq[freq <= _RARE_MAX].items():
        if len(typed) < 4 or not typed.isalpha() or typed in _REAL_NAMES:
            continue
        near = sorted((c for c in _one_slip(typed) if c in common.index),
                      key=lambda c: common[c], reverse=True)
        if not near or common[near[0]] < _COMMON_RATIO * times:
            continue
        if len(near) > 1 and common[near[1]] * 3 >= common[near[0]]:
            continue
        # The gender list holds typos too (Fairh, Etsher, Briam were added
        # as seen), so a listed name is corrected only when it has the same
        # gender as the common name and is far rarer.
        if typed in lookup and (lookup[typed] != lookup.get(near[0], lookup[typed])
                                or common[near[0]] < _LISTED_RATIO * times):
            continue
        out[typed] = near[0]
    return out


def fix_spelling(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Correct misspelt first names in Name / First Name.

    Returns the corrected frame and the corrections made (Name as typed,
    Phone, Typed, Corrected To, Orders) to put right in Odoo.
    """
    from lib import gender
    suggestions = spelling_suggestions()
    lookup, learned = gender._load_lookup(), gender._learned()
    df = df.copy()
    typed = df["First Name"].str.lower()
    target = typed.map(suggestions)

    def agrees(row_gender, suggestion) -> bool:
        if row_gender not in ("Male", "Female") or not isinstance(suggestion, str):
            return True
        implied, reliable = gender._expected(suggestion, lookup, learned)
        return not reliable or implied == row_gender

    # Corporate orders carry a company or organisation name, not a person's.
    ok = target.notna() & (df["Gender"] != "Corporate") & pd.Series(
        [agrees(g, s) for g, s in zip(df["Gender"], target)], index=df.index)
    fixed = df[ok]
    corrections = pd.DataFrame({
        "Name as Typed": fixed["Name"], "Phone": fixed["Phone"],
        "Typed": fixed["First Name"], "Corrected To": target[ok].str.title(),
    })
    new_first = target[ok].str.title()
    df.loc[ok, "Name"] = [n.replace(f, nf, 1) for n, f, nf in
                          zip(fixed["Name"], fixed["First Name"], new_first)]
    df.loc[ok, "First Name"] = new_first
    if corrections.empty:
        return df, corrections.assign(Orders=[])
    corrections = (corrections.groupby(list(corrections.columns), as_index=False)
                   .size().rename(columns={"size": "Orders"})
                   .sort_values("Orders", ascending=False))
    return df, corrections
