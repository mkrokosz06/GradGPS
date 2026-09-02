"""
Independent verification: does our reconstruction match what PSU says the credential costs?

Structural validation (validate.py) only proves a parse is *well-formed*.  It cannot
catch a parse that is well-formed and wrong — *Environmental Inquiry, Minor* passed every
structural check while reconstructing to **510 credits**.  Catching that needs a source of
truth outside our own parse.

PSU publishes one on nearly every page, in two places:

1. `table.tbl_programrequirements` — a "Program Requirements" table whose rows are
   (requirement, credits).  Present on 154/207 pages, and authoritative.
2. Prose — "To earn an undergraduate certificate in X, a minimum of N credits is
   required."  Covers 50 of the remaining pages, nearly all certificates.

Between them, 205 of 207 credentials can be checked against PSU's own number.  This is
the check that found every real bug after the first round; it belongs in the pipeline,
not in a one-off script.
"""

from __future__ import annotations

import re
from bs4 import BeautifulSoup

_CREDIT_CELL = re.compile(r"^\d+(?:\s*[-–—]\s*\d+)?$")
_PROSE_TOTAL = re.compile(
    r"to earn an? undergraduate (?:certificate|minor)[^.]{0,90}?"
    r"a minimum of (\d{1,2}) credits is required",
    re.I,
)


def stated_total(html: str) -> tuple[float | None, str | None]:
    """PSU's own credit total for the credential, and where it came from."""
    soup = BeautifulSoup(html, "html.parser")

    table = soup.select_one("table.tbl_programrequirements")
    if table is not None:
        total = 0.0
        found = False
        for tr in table.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True))
                     for td in tr.find_all(["td", "th"])]
            if len(cells) >= 2 and _CREDIT_CELL.match(cells[-1].strip()):
                total += float(re.match(r"^(\d+)", cells[-1].strip()).group(1))
                found = True
        if found:
            return total, "program-requirements table"

    stripped = BeautifulSoup(str(soup), "html.parser")
    for t in stripped.select("table"):
        t.decompose()
    body = re.sub(r"\s+", " ", stripped.get_text(" ", strip=True))
    m = _PROSE_TOTAL.search(body)
    if m:
        return float(m.group(1)), "prose"

    return None, None


def check(entry: dict, html: str) -> dict:
    """Compare a built entry against PSU's stated total.

    Returns {stated, source, agrees} — `agrees` is None when the page states no total,
    which is not a failure, just an unverifiable credential.
    """
    stated, source = stated_total(html)
    if stated is None:
        return {"stated_credits": None, "stated_source": None, "agrees": None}
    lo, hi = entry["credits"]["min"], entry["credits"]["max"]
    return {
        "stated_credits": stated,
        "stated_source":  source,
        "agrees":         bool(lo <= stated <= hi),
    }
