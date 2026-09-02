"""
CourseLeaf course-list parser for PSU credential (minor / certificate) pages.

Why this exists instead of reusing `scripts/scrape_psu.py`: that scraper reads the page
as *text* and only resets its group state on an `<h2>`-`<h5>` heading (scrape_psu.py:195).
Credential pages carry one heading and express all their structure inside a single
`table.sc_courselist`, so one stray "Select one of the following:" leaks into every
later table — and because `_eval_choose_one()` treats unpaired `choose_one` rows as
individually required (audit_engine.py:1655), that leak is what turns an 18-credit minor
into a 660-credit one.

PSU's CourseLeaf markup is fully semantic, so this parser reads the classes instead:

    tr.areaheader      section boundary        ("Prescribed Courses")
    tr.areasubheader   constraint prose        ("Require a grade of C or better")
    tr > td.codecol    a course row            (td.hourscol holds the credits)
    tr.orclass         alternative of the row above
    tr (no codecol)    a pool sentence         ("Select 11 credits … in PSYCH")

Same philosophy as `scripts/scrape_sap.py`, which parses `table.sc_plangrid` header
attributes deterministically rather than guessing from text.

Pure: HTML string in, structured groups out.  No network, no DB.
"""

from __future__ import annotations

import re
from bs4 import BeautifulSoup

from pools import PoolSpec, parse_pool, looks_like_pool, is_section_label

_CODE_RE = re.compile(r"^([A-Z]{2,6})\s?(\d{1,3}[A-Z]?)$")
# One or more subject codes (hyphens allowed: "A-I"), then a course number.  Used to
# pull every code out of a cell, however the cell joins them ("/" or "&").
_SUBJECT = r"[A-Z][A-Z\-]{0,7}"
_CODES_IN = re.compile(rf"((?:{_SUBJECT})(?:/{_SUBJECT})*)\s?(\d{{1,3}}[A-Z]?)\b")


def _txt(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def _classes(tr) -> set[str]:
    return set(tr.get("class") or [])


def _credits(cell_text: str) -> float | None:
    """A `td.hourscol` value.  Blank on pool members; a range ("2-7") on flexible pools."""
    t = (cell_text or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)(?:\s*[-–—]\s*(\d+(?:\.\d+)?))?$", t)
    return float(m.group(1)) if m else None


def _credits_max(cell_text: str) -> float | None:
    """The high end of a credit range ("1-6" -> 6.0).  None when it isn't a range.

    PSU lists variable-credit courses this way (HONOR 401, 1-6).  Taking only the low
    end made a certificate look like 5 credits when it is 5-12.
    """
    t = (cell_text or "").strip()
    m = re.match(r"^\d+(?:\.\d+)?\s*[-–—]\s*(\d+(?:\.\d+)?)$", t)
    return float(m.group(1)) if m else None


def _options_follow(rows, index) -> bool:
    """Whether the rows after `index` are a pool's options.

    CourseLeaf gives the credit amount to the pool sentence and leaves its member rows
    blank, so blank-hours course rows below a sentence are its options.  Judged over
    the whole run up to the next section boundary or sentence, not just the first row:
    lists are often mixed, and bailing on a single credited first option sent 53
    options of the Food Systems minor into its prescribed block (177 credits).
    """
    blank = credited = 0
    for tr in rows[index + 1:]:
        cls = _classes(tr)
        if "noscript" in cls or "hidden" in cls or "listsum" in cls:
            continue
        if "areaheader" in cls:
            break
        if "areasubheader" in cls:
            continue
        hours = tr.find("td", class_="hourscol")
        code_cell = tr.find("td", class_="codecol")
        if code_cell is None:
            # A code-less row with its own credit amount is the NEXT requirement, so
            # the run ends.  Without one it is just a category label inside the list
            # ("Agricultural and Environmental Sciences:") — skip it and keep going,
            # or the 53 courses beneath it stop looking like options.
            if _credits(_txt(hours)) is not None:
                break
            continue
        if _credits(_txt(hours)) is None:
            blank += 1
        else:
            credited += 1
    return blank > credited


def _norm_code(raw: str) -> str | None:
    """"PSYCH 100" / "PSYCH100" -> "PSYCH 100".  None if the cell isn't a course code."""
    m = _CODE_RE.match(re.sub(r"\s+", " ", (raw or "").strip()))
    return f"{m.group(1)} {m.group(2)}" if m else None


def _parse_code_cell(raw: str) -> tuple[str | None, list[str], list[str]]:
    """Split a code cell into (primary code, cross-listed alternates, co-requisites).

    A single-code regex silently dropped four real shapes, and a dropped row removes a
    requirement from the minor with no warning — this was the largest source of
    under-counting (African American Studies came out 15 credits instead of 18):

        AFAM/WMNST 101N        cross-listed, subjects share the number
        PHIL 132/RLST 131      cross-listed, each subject has its own number
        ANSC 207 & ANSC 208    a co-requisite pair carrying one combined credit value
        A-I 305                a subject code containing a hyphen

    The first subject is primary, matching how the catalog and
    `audit_engine._EQUIVALENCE_PAIRS` already treat cross-listings.
    """
    text = re.sub(r"\s+", " ", (raw or "").strip())
    text = re.sub(r"^\s*or\s+", "", text, flags=re.I)
    if not text:
        return None, [], []

    # "&" joins courses that must BOTH be taken; the row's credits cover the pair.
    segments = [s.strip() for s in re.split(r"\s*&\s*", text) if s.strip()]
    head, tail = segments[0], segments[1:]

    codes = _CODES_IN.findall(head)
    if not codes:
        return None, [], []

    if "/" in head and len(codes) == 1:
        # "AFAM/WMNST 101N" — one number shared by every subject listed.
        dept_blob, number = codes[0]
        depts = [d for d in dept_blob.split("/") if d]
        primary = f"{depts[0]} {number}"
        alts    = [f"{d} {number}" for d in depts[1:]]
    else:
        # "PHIL 132/RLST 131" — each subject brings its own number.
        primary = f"{codes[0][0].split('/')[0]} {codes[0][1]}"
        alts    = [f"{d.split('/')[0]} {n}" for d, n in codes[1:]] if "/" in head else []

    co_requisites = []
    for seg in tail:
        found = _CODES_IN.findall(seg)
        co_requisites += [f"{d.split('/')[0]} {n}" for d, n in found]

    return primary, alts, co_requisites


def _min_grade(text: str) -> str:
    t = (text or "").lower()
    if "grade of c" in t or "c or better" in t:
        return "C"
    if "grade of b" in t or "b or better" in t:
        return "B"
    return ""


def pool_label(spec: PoolSpec) -> str:
    """Short human label for a pool, used to keep two pools in one section distinct.

    `run_audit()` buckets a group's rows by (group_type, threshold), so two pools of the
    same type *and* the same size inside one section would silently merge into one.
    Giving each pool its own group name keeps them separate and reads correctly in the UI.
    """
    if spec.dept and spec.min_level and spec.max_level:
        return f"{spec.dept} {spec.min_level}-{spec.max_level}"
    if spec.dept and spec.min_level:
        return f"{spec.dept} {spec.min_level}+"
    if spec.dept:
        return f"{spec.dept} electives"
    unit = "credits" if spec.unit == "credits" else "courses"
    return f"choose {spec.threshold} {unit}"


_REQUIREMENTS_HEADING = re.compile(r"requirements?\s+for\s+the\s+(minor|certificate)", re.I)
# "Entrance to Minor" is admission criteria, not coursework the student owes.
_NOT_REQUIREMENTS = re.compile(r"entrance|admission|application|advis|contact|career", re.I)


def _requirement_tables(soup, tables):
    """The subset of course lists that state the credential's requirements.

    Chosen by the heading each table sits under, because position is unreliable in
    both directions (reference lists after, entrance criteria before).  Falls back to
    the first table when no heading matches, which is how most pages look anyway.
    """
    matched = []
    for t in tables:
        heading = t.find_previous(["h1", "h2", "h3", "h4", "h5", "strong"])
        text = heading.get_text(" ", strip=True) if heading else ""
        if _REQUIREMENTS_HEADING.search(text):
            matched.append(t)
    if matched:
        return matched
    usable = [t for t in tables
              if not _NOT_REQUIREMENTS.search(
                  (t.find_previous(["h1", "h2", "h3", "h4", "h5", "strong"]) or soup).get_text(" ", strip=True)[:80])]
    return (usable or tables)[:1]


class ParseWarning(str):
    """A recoverable oddity worth surfacing in the health report."""


def parse_courselist(html: str) -> tuple[list[dict], list[str]]:
    """Parse a credential page into requirement groups.

    Returns (groups, warnings).  A group is::

        {"name": str, "group_type": str, "min_grade": str,
         "threshold": int|None, "threshold_max": int|None,
         "pool": {...}|None,          # PoolSpec dict for dept_credits groups
         "courses": [{"course_code", "course_title", "credits", "pair_group_id"}]}

    `group_type` is one of: required, choose_one, choose_credits, choose_courses,
    dept_credits.
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table.sc_courselist")
    if not tables:
        return [], ["no table.sc_courselist on the page"]

    # Pick the table(s) that actually state the requirements, by the heading each one
    # sits under.  Position is not enough in either direction:
    #   * Environmental Inquiry puts seven cluster reference lists AFTER its
    #     requirement table — folding them in counted every cluster course as required
    #     (292 credits instead of 18);
    #   * Environmental Engineering opens with an "Entrance to Minor" table (admission
    #     criteria, not degree requirements) and puts the real one second.
    all_tables   = tables
    tables       = _requirement_tables(soup, all_tables)
    extra_tables = len(all_tables) - len(tables)

    groups: list[dict] = []
    warnings: list[str] = []

    section       = "Requirements"
    section_grade = ""
    open_pool: dict | None = None      # the enumerable pool currently collecting members
    prescribed: dict | None = None     # the running `required` group for this section
    pair_seq = [0]
    # section name -> (declared_min, declared_max) credits, when the header states them
    section_totals: dict[str, tuple[float | None, float | None]] = {}

    def new_group(name, gtype, **kw) -> dict:
        g = {"name": name, "group_type": gtype, "min_grade": section_grade,
             "section": section,
             # Whether this group's size is stated in the page's credits column.  A
             # pool sentence with a blank credits cell is a SUBDIVISION of the pool
             # above it ("Select 12 credits of which 9 must be at the 400 level:"
             # followed by "Select 6 credits from the following:"), so counting it
             # again would double-count the parent's credits.
             "counts_toward_total": True,
             "threshold": None, "threshold_max": None, "pool": None, "courses": [], **kw}
        groups.append(g)
        return g

    def close_pool():
        nonlocal open_pool
        open_pool = None

    def prescribed_group() -> dict:
        """The `required` bucket for the current section, created on first use."""
        nonlocal prescribed
        if prescribed is None:
            prescribed = new_group(section, "required")
        return prescribed

    for table in tables:
        table_rows = table.find_all("tr")
        for row_index, tr in enumerate(table_rows):
            cls = _classes(tr)
            if "noscript" in cls or "hidden" in cls:
                continue
            # CourseLeaf's own footer ("Total Credits 18") — a summary, not a requirement.
            if "listsum" in cls:
                continue

            # Footnote markers are <sup> elements inside the cell text.  Left in, they
            # append a stray digit to the sentence ("Select 3 credits of the
            # following: 1"), which hides the trailing colon that marks an
            # enumerable pool — so the pool never opens and its options get read as
            # prescribed courses with no credits.
            for sup in tr.find_all("sup"):
                sup.decompose()

            cells      = tr.find_all(["td", "th"])
            code_cell  = tr.find("td", class_="codecol")
            hours_cell = tr.find("td", class_="hourscol")
            hours_txt  = _txt(hours_cell)
            # The sentence must exclude the credits column: CourseLeaf repeats the
            # amount there, and appending it both hides the trailing colon that marks
            # an enumerable pool and turns "… in PSYCH" into "… in PSYCH 11".
            row_txt = " ".join(
                t for t in (_txt(c) for c in cells if c is not hours_cell) if t
            )

            # ── Section boundary — the reset scrape_psu.py is missing ──────────
            if "areaheader" in cls:
                name = _txt(tr.find("span")) or row_txt
                if name:
                    section, section_grade = name, ""
                    # A section header that states its own credit total is
                    # authoritative for that section.  Some sections branch
                    # ("Non-Geoscience Majors" / "Geoscience Majors") and list every
                    # branch's courses, so summing the children double-counts — the
                    # header's number is what the student actually owes.
                    section_totals[name] = (_credits(hours_txt), _credits_max(hours_txt))
                    prescribed = None
                    close_pool()
                continue

            # ── Constraint prose for the open section ─────────────────────────
            if "areasubheader" in cls:
                grade = _min_grade(row_txt)
                if grade:
                    section_grade = grade
                    for g in groups:
                        if g["name"].startswith(section) and not g["min_grade"]:
                            g["min_grade"] = grade
                continue

            # ── A course row ──────────────────────────────────────────────────
            if code_cell is not None:
                code, cross_listed, co_requisites = _parse_code_cell(_txt(code_cell))
                if not code:
                    continue

                title = ""
                for c in cells:
                    if c is code_cell or c is hours_cell:
                        continue
                    title = _txt(c)
                    if title:
                        break

                credits = _credits(hours_txt)
                entry = {"course_code": code, "course_title": title[:120],
                         "credits": credits, "credits_max": _credits_max(hours_txt),
                         "pair_group_id": None}
                if cross_listed:
                    # The other subjects that own this course; the audit already treats
                    # cross-listings as equivalent (audit_engine._EQUIVALENCE_PAIRS).
                    entry["cross_listed"] = cross_listed
                if co_requisites:
                    # "ANSC 207 & ANSC 208" — both must be taken, and the row's credit
                    # value covers the pair, so this stays ONE requirement.
                    entry["co_requisites"] = co_requisites

                # An "or" row is an alternative of the row immediately above it.
                if "orclass" in cls:
                    # Inside a pool the alternatives are just more options, so the pair
                    # stays in the pool.  Inside a prescribed block the pair is its own
                    # choose_one group: flipping the whole block to choose_one would
                    # leave every *other* course in it unpaired, and unpaired
                    # choose_one rows are evaluated as individually required
                    # (audit_engine.py:1655) — the exact defect this parser exists to fix.
                    if open_pool is not None and open_pool["courses"]:
                        prev = open_pool["courses"][-1]
                        if prev["pair_group_id"] is None:
                            pair_seq[0] += 1
                            prev["pair_group_id"] = pair_seq[0]
                        entry["pair_group_id"] = prev["pair_group_id"]
                        open_pool["courses"].append(entry)
                        continue

                    prev_group = _group_holding_last_course(groups, prescribed)
                    if prev_group is not None and prev_group["courses"]:
                        prev = prev_group["courses"][-1]
                        if prev_group["group_type"] == "choose_one":
                            # Extending an existing chain: A or B or C.
                            entry["pair_group_id"] = prev["pair_group_id"]
                            prev_group["courses"].append(entry)
                            continue
                        # Start a new pair: lift the previous course out of the
                        # prescribed block into a choose_one group of its own.
                        prev_group["courses"].pop()
                        pair_seq[0] += 1
                        prev["pair_group_id"]  = pair_seq[0]
                        entry["pair_group_id"] = pair_seq[0]
                        pair_group = new_group(
                            f"{section}: {prev['course_code']} or {code}", "choose_one")
                        pair_group["courses"] = [prev, entry]
                        continue
                    warnings.append(f"orphan 'or' row: {code}")

                # An open pool owns every course row until a *structural* boundary —
                # the next section header or the next requirement sentence.  It must
                # NOT be closed by an option that happens to state its own credits:
                # mixed lists are common, and closing there sent the rest of the list
                # into the prescribed block, which is exactly the over-require bug
                # this parser exists to fix (it read Environmental Inquiry as 510
                # credits, with 80 options of one pool marked required).
                if open_pool is not None:
                    open_pool["courses"].append(entry)
                else:
                    prescribed_group()["courses"].append(entry)
                continue

            # ── A code-less row: pool sentence, or a note we ignore ───────────
            # Two ways to recognise a requirement sentence.  The wording is the usual
            # one; the structural signal — it carries a credit amount AND blank-hours
            # course rows follow it — is the reliable one, and catches sentences with
            # no verb and no number ("Additional courses, no more than one of which
            # may be a Jewish Studies course").
            has_amount   = _credits(hours_txt) is not None
            opens_a_pool = has_amount and _options_follow(table_rows, row_index)
            if is_section_label(row_txt, section):
                continue
            if looks_like_pool(row_txt, has_amount) or opens_a_pool:
                spec = parse_pool(row_txt, hours_txt)

                # Structure beats punctuation.  A sentence whose wording we can't
                # classify ("Additional courses, no more than one of which may be a
                # 100-level course") is still plainly enumerable when blank-hours
                # course rows follow it — those rows ARE its options.  Without this,
                # the pool never opens and its options are read as prescribed
                # courses, which is how a 6-credit slot became 17 required courses.
                if opens_a_pool:
                    if spec is None:
                        amount = _credits(hours_txt)
                        if amount is not None:
                            open_pool = new_group(
                                f"{section}: {row_txt[:40]}",
                                "choose_credits",
                                threshold=amount,
                                threshold_max=_credits_max(hours_txt),
                                pool={"text": row_txt},
                            )
                            continue
                    elif not spec.enumerable and not (spec.dept or spec.depts):
                        spec.enumerable = True

                if spec is None:
                    # A requirement we can read the *size* of but not the *rule*, e.g.
                    # "Students must take 9 credits within one or more of the following
                    # areas of concentration: Ceramics, Drawing and Painting, … These 9
                    # credits must include 3 credits at the 300-level."  Record it so the
                    # credit total stays honest, and let validation flag the credential
                    # for a human — never guess a rule that would auto-satisfy it.
                    amount = _credits(hours_txt)
                    if amount is not None:
                        new_group(f"{section}: {row_txt[:40]}", "unstructured_credits",
                                  threshold=amount,
                                  threshold_max=_credits_max(hours_txt),
                                  pool={"text": row_txt})
                    else:
                        warnings.append(f"unparsed requirement sentence: {row_txt[:90]}")
                    close_pool()
                    continue

                label = pool_label(spec)
                name  = section if _only_pool_in_section(groups, section) else f"{section}: {label}"

                if spec.enumerable:
                    gtype = "choose_credits" if spec.unit == "credits" else "choose_courses"
                    g = new_group(name, gtype,
                                  threshold=spec.threshold,
                                  threshold_max=spec.threshold_max,
                                  counts_toward_total=has_amount)
                    open_pool = g
                else:
                    new_group(name, "dept_credits",
                              threshold=spec.threshold,
                              threshold_max=spec.threshold_max,
                              counts_toward_total=has_amount,
                              pool=spec.to_dict())
                    close_pool()
                continue

    # Drop groups that never collected anything (an enumerable pool with no members
    # is a parse failure, not an empty requirement — surface it).
    kept = []
    for g in groups:
        if g["group_type"] in ("choose_credits", "choose_courses") and not g["courses"]:
            # The sentence promised a list and none followed — we know the size but not
            # the options, which is the unstructured case above.
            g["group_type"] = "unstructured_credits"
            g["pool"] = {"text": (g.get("pool") or {}).get("text", g["name"])}
            kept.append(g)
            continue
        if g["group_type"] in ("required", "choose_one") and not g["courses"]:
            continue
        kept.append(g)

    if extra_tables:
        warnings.append(
            f"{extra_tables} further course table(s) on the page were ignored as "
            f"reference lists"
        )

    for g in kept:
        g["section_credits"] = section_totals.get(g.get("section")) or (None, None)

    return kept, warnings


def _group_holding_last_course(groups: list[dict], prescribed: dict | None) -> dict | None:
    """The group the row immediately above landed in.

    Usually the section's prescribed block, but an or-chain that has already been
    lifted into its own choose_one group must be extended, not restarted.
    """
    for g in reversed(groups):
        if g["courses"]:
            return g
    return prescribed


def _only_pool_in_section(groups: list[dict], section: str) -> bool:
    """True when no pool group has been opened for this section yet."""
    return not any(
        g["name"] == section or g["name"].startswith(f"{section}: ")
        for g in groups
        if g["group_type"] in ("choose_credits", "choose_courses", "dept_credits")
    )
