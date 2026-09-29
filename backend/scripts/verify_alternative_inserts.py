"""
Verify every course alternative that `patch_known_alternatives()` INSERTED into
the catalog, against independent sources, and write the verdicts to
`program_data/alternative_inserts.json`.

Why: the patch's `insert_missing=True` added "the other course" to every
(program, group) holding one half of a known pair — CHEM 130 as an alternative
to CHEM 110 in Chemical Engineering, MATH 110 for MATH 140 in Physics, ACCTG 201
alone for ACCTG 211. Where the bulletin never offers that alternative, the audit
tells a student they are done when they are not.

A row is an insert (not a scrape) when BOTH hold — two independent tests:
  * its sort key has no scrape sequence number (`group#code`, not `group#code#6403`)
  * the original scrape (PSU_Major_Requirements.xlsx) has no such row

Sources consulted per insert; ANY one naming the course keeps it:
  1. live bulletin page — Program Requirements tab
  2. live bulletin page — Suggested Academic Plan tab
  3. live bulletin page — Entrance to Major tab
  4. live bulletin page — anywhere else on the page
  4b. live bulletin page — CourseLeaf course LINKS in the raw HTML, a second
      witness that shares no parsing with the text checks above
  5. bundled SAP templates (sap_templates/, scraped independently)
  6. bundled Entrance to Major spec (entrance_data/, parsed independently)
  7. the original scrape, any group of the same program
Abbreviated lists are expanded first ("PHYS 211 or 250" names PHYS 250).

Verdicts:
  keep    — some source names the course as an alternative
  branch  — the only source is a compound gate branch, "ACCTG 211 or (ACCTG 201
            and ACCTG 202)": the insert is kept but must become that branch,
            because ACCTG 201 alone is half a course
  drop    — no source names it anywhere
A page that cannot be fetched is `keep` (unverified): failing to verify must
never delete a requirement a student relies on.

Scope: University Park degree programs, outside the campus plan-grid groups the
timeline filters out anyway — i.e. every insert a student can actually see.

Usage (needs the local catalog, the gitignored xlsx, and network):
    python scripts/verify_alternative_inserts.py [--cache DIR]
"""

import argparse
import collections
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BACKEND, "program_data", "alternative_inserts.json")
XLSX_PATH = os.path.join(os.path.dirname(BACKEND), "PSU_Major_Requirements.xlsx")
UA = {"User-Agent": "GradGPS-CatalogScraper/1.0 (educational use; mkrokosz06@gmail.com)"}

TABS = {"bulletin_requirements": "programrequirementstextcontainer",
        "bulletin_plan": "suggestedacademicplantextcontainer",
        "bulletin_entrance": "howtogetintextcontainer"}

_STANDALONE = ("bulletin_requirements", "bulletin_plan", "sap_template")

_CAMPUS_GROUP = re.compile(r"\bat\b.*Campus|Campuses")

# "ENGL 202C , 202A , or 202D" — a subject followed by bare numbers.
_LIST = re.compile(r"\b([A-Z][A-Z-]{1,6}) (\d{1,3}[A-Z]?)"
                   r"((?:\s*(?:,|or|and|/)\s*(?:or\s+|and\s+)?\d{1,3}[A-Z]?\b)+)")


def expand(text: str) -> str:
    """Write every abbreviated course number out in full."""
    def rep(m):
        subj = m.group(1)
        tail = re.sub(r"\b(\d{1,3}[A-Z]?)\b", lambda n: f"{subj} {n.group(1)}", m.group(3))
        return f"{subj} {m.group(2)}{tail}"
    return _LIST.sub(rep, text)


def normalise(text: str) -> str:
    return expand(re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")))


def names(code: str, text: str) -> bool:
    """Whether `text` names `code`, tolerating one attribute letter (311 / 311W)."""
    subj, num = code.split()
    base = re.sub(r"[WHNMXY]$", "", num)
    return re.search(rf"\b{re.escape(subj)} {re.escape(base)}[A-Z]?\b", text) is not None


_CODE = r"[A-Z][A-Z-]{1,6} \d{1,3}[A-Z]?"
_COMPOUND = re.compile(rf"\(\s*({_CODE})\s+and\s+({_CODE})\s*\)")


def stated_branches(text: str, code: str, partners: list[str]) -> list[list[str]]:
    """Compound branches the bulletin WRITES next to a partner: "ACCTG 211 or
    ( ACCTG 201 and ACCTG 202 )". The bulletin stating the branch outright beats
    any bare mention of its first course (a campus grid's ACCTG 201 row is just
    the first half of the same sequence)."""
    found = []
    for m in _COMPOUND.finditer(text or ""):
        members = [m.group(1), m.group(2)]
        if code not in members:
            continue
        window = text[max(0, m.start() - 40):m.end() + 40]
        if any(re.search(rf"\b{re.escape(p)}\b\s*\)?\s*or\b|\bor\s+\(?\s*{re.escape(p)}\b", window)
               for p in partners):
            found.append(members)
    return found


def decide(code: str, partners: list[str], evidence: dict, gate_branches: list[list[str]],
           stated: list[list[str]] | None = None, page_sane: bool = True) -> tuple[str, list[str]]:
    """Combine the sources into a verdict. Pure — the tests drive it directly.

    Returns (verdict, branch_members). `evidence` maps source -> bool, or None
    when the source could not be consulted.
    """
    if any(v is None for v in evidence.values()):
        return "keep", []                       # unverified: never delete on a failed check
    if stated:
        return "branch", stated[0]
    # A page that doesn't even name the course we KEEP is a page we failed to
    # read (wrong URL, changed layout) — its silence proves nothing.
    if not page_sane:
        return "keep", []
    # A compound gate branch holding this course AND something else, offered
    # as the alternative to a partner: "ACCTG 211 or (ACCTG 201 and ACCTG 202)".
    # Only a requirements list or a plan offering the course ON ITS OWN makes it a
    # standalone alternative; a campus plan grid listing ACCTG 201 and ACCTG 202
    # in consecutive terms is the branch, not evidence against it.
    for branch in gate_branches:
        if code in branch and len(branch) > 1:
            if not any(evidence.get(k) for k in _STANDALONE):
                return "branch", branch
    return ("keep" if any(evidence.values()) else "drop"), []


def _fetch(url: str, cache_dir: str | None) -> dict | None:
    import requests
    from bs4 import BeautifulSoup
    path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, re.sub(r"[^A-Za-z0-9]+", "_", url)[-120:] + ".html")
    html = None
    if path and os.path.exists(path):
        html = open(path, encoding="utf-8").read()
    else:
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=UA, timeout=30)
                if resp.status_code == 200:
                    html = resp.text
                    break
            except Exception:
                pass
            time.sleep(2 * (attempt + 1))
        time.sleep(1.0)
        if html is None:
            return None
        if path:
            open(path, "w", encoding="utf-8").write(html)
    soup = BeautifulSoup(html, "html.parser")
    out = {k: normalise(el.get_text(" ")) if (el := soup.find(id=v)) else ""
           for k, v in TABS.items()}
    out["bulletin_page"] = normalise(soup.get_text(" "))
    # Independent second witness: the course links CourseLeaf renders for every
    # mention, abbreviated ones included ("PHYS 211 or 250" links PHYS%20250).
    # Read straight from the HTML, so it shares no parsing with the text checks.
    out["bulletin_links"] = " ".join(sorted(set(
        m.replace("%20", " ") for m in re.findall(r"[?&]P=([A-Z][A-Z-]{1,6}%20\d{1,3}[A-Z]?)", html))))
    return out


def _scan(table) -> list[dict]:
    rows, kw = [], {}
    while True:
        r = table.scan(**kw)
        rows += r["Items"]
        if "LastEvaluatedKey" not in r:
            return rows
        kw = {"ExclusiveStartKey": r["LastEvaluatedKey"]}


def _plain(v):
    """DynamoDB Decimal / pandas NaN -> JSON-safe."""
    if v is None:
        return None
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    if hasattr(v, "as_integer_ratio") and not isinstance(v, bool):
        f = float(v)
        return int(f) if f.is_integer() else f
    return v


def main():
    import pandas as pd
    from db import requirements_table
    from routers.programs import is_up_program, is_degree_program
    from seed_matthew import KNOWN_ALTERNATIVE_GROUPS

    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="directory to cache fetched bulletin pages")
    args = ap.parse_args()

    group_codes = {c for g in KNOWN_ALTERNATIVE_GROUPS for c in g["codes"]}

    x = pd.read_excel(XLSX_PATH)
    scraped = {}
    for r in x.itertuples():
        scraped[(r.program_name, r.requirement_group, str(r.course_code).strip())] = r
    urls = dict(zip(x.program_name, x.url))
    scraped_by_program = collections.defaultdict(set)
    for (p, _g, c) in scraped:
        scraped_by_program[p].add(c)

    templates = collections.defaultdict(set)
    tdir = os.path.join(BACKEND, "sap_templates")
    for f in os.listdir(tdir):
        t = json.load(open(os.path.join(tdir, f), encoding="utf-8"))
        for sem in t.get("semesters", []):
            for slot in sem.get("slots", []):
                for c in ([slot["code"]] if slot.get("code") else (slot.get("codes") or [])):
                    templates[t["program_name"]].add(c)

    etm = json.load(open(os.path.join(BACKEND, "entrance_data", "entrance_requirements.json"),
                         encoding="utf-8"))["programs"]

    rows = _scan(requirements_table)
    degrees = collections.defaultdict(set)
    for r in rows:
        degrees[r.get("program_name", "")].add(r.get("degree") or "")
    by_pair = collections.defaultdict(list)
    for r in rows:
        if r.get("pair_group_id") is not None:
            by_pair[(r["program_name"], r["requirement_group"], r["pair_group_id"])].append(r)

    entries = []
    pages: dict[str, dict | None] = {}
    for r in rows:
        p, g, c = r.get("program_name", ""), r.get("requirement_group", ""), r.get("course_code", "")
        if c not in group_codes or p.startswith("__"):
            continue
        if r.get("group_course") != f"{g}#{c}" or (p, g, c) in scraped:
            continue                                         # a scraped row, not an insert
        if not is_up_program(p) or not is_degree_program(p, degrees[p]) or _CAMPUS_GROUP.search(g):
            continue

        # Partners are the scraped rows of the same pair — told apart by their
        # sequence-numbered key, not by the xlsx, whose pair ids are numbered per
        # scrape run and don't match the loaded catalog's.
        mates = [m for m in by_pair.get((p, g, r.get("pair_group_id")), []) if m is not r]
        partners = sorted(m["course_code"] for m in mates
                          if m.get("group_course") != f"{g}#{m['course_code']}")

        url = urls.get(p)
        if url not in pages:
            pages[url] = _fetch(url, args.cache) if url else None
        page = pages[url]

        evidence = {}
        for key in ("bulletin_requirements", "bulletin_plan", "bulletin_entrance", "bulletin_page",
                    "bulletin_links"):
            evidence[key] = names(c, page[key]) if page else None
        evidence["sap_template"] = any(names(c, t) for t in templates.get(p, ()))
        gate_groups = (etm.get(p) or {}).get("groups", [])
        evidence["entrance_spec"] = any(c in b for grp in gate_groups for b in grp)
        evidence["scraped_elsewhere"] = c in scraped_by_program.get(p, set())

        gate_branches = [b for grp in gate_groups for b in grp
                         if any(pc in [x for bb in grp for x in bb] for pc in partners)]
        stated = stated_branches(page["bulletin_page"], c, partners) if page else []
        page_sane = (bool(page) and bool(partners)
                     and all(names(pc, page["bulletin_page"]) for pc in partners))
        verdict, branch = decide(c, partners, evidence, gate_branches, stated, page_sane)

        entries.append({
            "program": p, "group": g, "inserted": c,
            "group_course": r["group_course"],
            "pair_group_id": _plain(r.get("pair_group_id")),
            "partners": partners,
            "verdict": verdict,
            "branch": branch,
            "evidence": evidence,
            "page_names_partner": page_sane,
        })

    entries.sort(key=lambda e: (e["program"], e["group"], e["inserted"]))
    counts = collections.Counter(e["verdict"] for e in entries)
    json.dump({
        "about": "Verdicts on course alternatives inserted by patch_known_alternatives(); "
                 "built by scripts/verify_alternative_inserts.py. patch_known_alternatives() "
                 "inserts ONLY entries marked keep/branch; remove_unverified_alternatives.py "
                 "deletes the drops from a loaded catalog.",
        "counts": dict(counts),
        "entries": entries,
    }, open(OUT_PATH, "w", encoding="utf-8"), indent=1, sort_keys=False)
    print(f"{len(entries)} inserts, {len(pages)} pages: {dict(counts)} -> {OUT_PATH}")


if __name__ == "__main__":
    main()
