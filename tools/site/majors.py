#!/usr/bin/env python3
"""Generate the per-major SEO pages under website/majors/.

Usage:  python tools/site/majors.py

Each page combines, for one University Park major, the Suggested Academic Plan
(backend/sap_templates/) with its Entrance to Major gate
(backend/entrance_data/entrance_requirements.json) and real course titles
(backend/scripts/bulletin_courses.json). Gate courses are flagged inside the plan,
which is the part the bulletin itself doesn't show on one page.

Also writes website/majors/index.html and the majors block of sitemap.xml, then
runs build.py's chrome inlining over the new pages. Output is committed.

Only facts the data states unambiguously are published: a GPA floor appears only
when the bulletin names exactly one figure, and any gate condition we don't model
sends the reader to the official section instead of being paraphrased.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

import build

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "website"
OUT = SITE / "majors"
BACKEND = ROOT / "backend"

# Template stems to publish. Pilot set — widen once these are indexed.
MAJORS = [
    "enterprise-technology-integration-bs-information-sciences-and-technology",
    "accounting-bs-business",
    "finance-bs-business",
    "computer-science-bs-engineering",
    "mechanical-engineering-bs-engineering",
]

TERMS = {"FA": "Fall", "SP": "Spring", "SU": "Summer"}
YEARS = {1: "First year", 2: "Second year", 3: "Third year", 4: "Fourth year", 5: "Fifth year"}
GEN_ED = {
    "GA": "Arts", "GH": "Humanities", "GN": "Natural Sciences",
    "GS": "Social and Behavioral Sciences", "GHW": "Health and Wellness",
    "GQ": "Quantification", "US": "United States Cultures", "IL": "International Cultures",
}

esc = html.escape
OR = ' <span class="or">or</span> '


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


COURSES = load(BACKEND / "scripts" / "bulletin_courses.json")
ENTRANCE = load(BACKEND / "entrance_data" / "entrance_requirements.json")["programs"]


def title_of(code: str) -> str:
    for c in (code, re.sub(r"[WHMXY]$", "", code), code + "A"):
        if c in COURSES:
            return COURSES[c]["title"]
    return ""


def fmt_cr(x: float) -> str:
    return f"{x:g}"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def short_name(program: str) -> str:
    """'Accounting, B.S. (Business)' -> 'Accounting'."""
    return program.split(",")[0].strip()


GATE_TAG = ' <span class="gate-tag">Entrance</span>'


def course_html(code: str) -> str:
    t = title_of(code)
    title = f' <span class="c-title">{esc(t)}</span>' if t else ""
    return f'<span class="c-code">{esc(code)}</span>{title}'


def slot_html(slot: dict, gate: set[str]) -> str:
    kind = slot["type"]
    # One tag per slot: "ENGL 15 or ENGL 30H or ..." is one entrance requirement.
    if kind == "course":
        return course_html(slot["code"]) + (GATE_TAG if slot["code"] in gate else "")
    if kind == "choose_one":
        tag = GATE_TAG if gate.intersection(slot["codes"]) else ""
        return OR.join(course_html(c) for c in slot["codes"]) + tag
    if kind == "gen_ed":
        cat = slot.get("category")
        label = f"General Education &mdash; {esc(GEN_ED.get(cat, cat))} ({esc(cat)})" if cat else "General Education"
        return f'<span class="c-generic">{label}</span>'
    return f'<span class="c-generic">{esc(slot.get("label") or "Elective")}</span>'


def gate_codes(spec: dict | None) -> set[str]:
    if not spec:
        return set()
    return {code for group in spec["groups"] for branch in group for code in branch}


def entrance_html(spec: dict | None, source: str) -> str:
    if not spec or not spec["groups"]:
        return (
            "<p>The bulletin doesn&rsquo;t list specific entrance courses for this major. "
            f'Check the <a href="{esc(source)}#howtogetintextcontainer">official page</a> for any other conditions.</p>'
        )
    items = []
    for group in spec["groups"]:
        branches = []
        for branch in group:
            parts = [esc(c) + (f' <span class="c-title">{esc(title_of(c))}</span>' if title_of(c) else "") for c in branch]
            branches.append(" <em>and</em> ".join(parts) if len(branch) == 1 else "(" + " <em>and</em> ".join(parts) + ")")
        lead = "" if len(group) == 1 else '<span class="one-of">One of:</span> '
        items.append(f"<li>{lead}{OR.join(branches)}</li>")

    facts = []
    if spec.get("min_grade"):
        facts.append(f"Each course needs a grade of <strong>{esc(spec['min_grade'])} or better</strong>.")
    if spec.get("gpa_min") and len(spec.get("gpa_candidates") or []) <= 1:
        facts.append(f"Minimum cumulative GPA: <strong>{spec['gpa_min']:.2f}</strong>.")
    elif spec.get("gpa_candidates"):
        facts.append("The bulletin gives more than one GPA figure depending on your situation, so check the official section for the one that applies to you.")
    if spec.get("has_unmodelled"):
        facts.append("There are other conditions too, such as credit windows, application deadlines or space limits, that aren&rsquo;t summarised here.")

    return (
        f'<ul class="gate-list">{"".join(items)}</ul>'
        + "".join(f"<p>{f}</p>" for f in facts)
        + f'<p><a href="{esc(source)}#howtogetintextcontainer">Read the full entrance section on the Penn State bulletin</a>.</p>'
    )


def plan_html(tpl: dict, gate: set[str]) -> str:
    out = []
    for sem in tpl["semesters"]:
        rows = "".join(
            f'<tr><td>{slot_html(s, gate)}</td><td class="cr">{fmt_cr(s["credits"])}</td></tr>'
            for s in sem["slots"]
        )
        total = sum(s["credits"] for s in sem["slots"])
        year = YEARS.get(sem["year"], "Year %d" % sem["year"])
        head = f'{year} &middot; {TERMS.get(sem["term_season"], sem["term_season"])}'
        out.append(
            f'<section class="sem"><h3>{head} <span class="sem-cr">{fmt_cr(total)} credit{"" if total == 1 else "s"}</span></h3>'
            f'<table><thead><tr><th scope="col">Course</th><th scope="col" class="cr">Credits</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></section>"
        )
    return f'<div class="plan-grid">{"".join(out)}</div>'


def page(head: str, body_class: str, main: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<!--#include head-common-->
<!--#endinclude head-common-->
{head}
</head>
<body class="{body_class}">
<!--#include header-->
<!--#endinclude header-->

<main id="main">
{main}
</main>

<!--#include footer-->
<!--#endinclude footer-->
</body>
</html>
"""


def meta(title: str, desc: str, url: str, crumbs: list[tuple[str, str]]) -> str:
    ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(crumbs)
        ],
    }
    return f"""<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}" />
<link rel="canonical" href="{url}" />
<meta property="og:title" content="{esc(title)}" />
<meta property="og:description" content="{esc(desc)}" />
<meta property="og:url" content="{url}" />
<meta property="og:image" content="https://gradgps.com/og.png" />
<meta property="og:image:type" content="image/png" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta property="og:image:alt" content="GradGPS — You are here. Graduation is that way." />
<script type="application/ld+json">
{json.dumps(ld, indent=2, ensure_ascii=False)}
</script>"""


CTA = """  <section class="cta">
    <div class="wrap">
      <img class="pin" src="/logo.png" width="68" height="68" alt="" aria-hidden="true" />
      <h2>Already partway through?</h2>
      <p>This plan assumes you start from zero. GradGPS reads your LionPATH transcript, checks off what you&rsquo;ve done, and reflows the rest of this plan around you, including AP, transfer credit and switched majors.</p>
      <a class="btn btn-navy" href="/download">Get the app</a>
      <p class="hero-note">Free &middot; iPhone &middot; not affiliated with Penn State</p>
    </div>
  </section>"""


def major_page(tpl: dict, slug: str) -> str:
    program = tpl["program_name"]
    name = short_name(program)
    spec = ENTRANCE.get(program)
    gate = gate_codes(spec)
    source = spec["source_url"] if spec else tpl["source"]
    url = f"https://gradgps.com/majors/{slug}"
    total = fmt_cr(tpl["total_credits"])
    n_sem = len(tpl["semesters"])

    title = f"Penn State {name} {tpl['degree']}: 4-Year Plan & Entrance Requirements"
    desc = (
        f"The {total}-credit, semester-by-semester plan for Penn State's {name} {tpl['degree']} at University Park, "
        f"with course titles and the Entrance to Major courses marked."
    )
    head = meta(title, desc, url, [
        ("Home", "https://gradgps.com/"), ("Majors", "https://gradgps.com/majors/"), (name, url),
    ])
    gate_note = (
        f'<p class="legend"><span class="gate-tag">Entrance</span> marks a course that counts toward the Entrance to Major requirements.</p>'
        if gate else ""
    )
    main = f"""  <div class="wrap page-head">
    <p class="kicker"><a href="/majors/">Majors</a> &rsaquo; {esc(program)}</p>
    <h1>{esc(name)} at Penn State: 4&#8209;year plan &amp; entrance requirements</h1>
    <p class="lede">
      Penn State&rsquo;s suggested {n_sem}-semester route through the {esc(name)} {esc(tpl['degree'])} at University Park,
      {total} credits in all, with every course titled and the Entrance to Major courses marked.
    </p>
  </div>

  <section class="block major-block">
    <div class="wrap">
      <h2>Entrance to Major</h2>
      <p class="section-lede">The courses you need before you can formally enter the major.</p>
      <div class="prose major-prose">{entrance_html(spec, source)}</div>
    </div>
  </section>

  <section class="block major-block">
    <div class="wrap">
      <h2>Semester-by-semester plan</h2>
      <p class="section-lede">The order Penn State suggests, so prerequisites come first and credit loads stay balanced.</p>
      {gate_note}
      {plan_html(tpl, gate)}
      <p class="source">
        Source: the Suggested Academic Plan in the
        <a href="{esc(tpl['source'])}">Penn State Undergraduate Bulletin</a>.
        GradGPS is an independent student project and isn&rsquo;t affiliated with Penn State.
        Requirements change, so confirm your plan with your adviser.
      </p>
    </div>
  </section>

{CTA}"""
    return page(head, "page-major", main)


def index_page(entries: list[tuple[str, str, dict]]) -> str:
    url = "https://gradgps.com/majors/"
    title = "Penn State Majors: 4-Year Plans & Entrance Requirements"
    desc = "Semester-by-semester plans and Entrance to Major requirements for Penn State University Park majors, with course titles and credits."
    head = meta(title, desc, url, [("Home", "https://gradgps.com/"), ("Majors", url)])
    items = "".join(
        f'<li><a href="/majors/{slug}">{esc(tpl["program_name"])}</a> '
        f'<span class="m-meta">{fmt_cr(tpl["total_credits"])} credits</span></li>'
        for _, slug, tpl in sorted(entries)
    )
    main = f"""  <div class="wrap page-head">
    <h1>Penn State majors, planned out.</h1>
    <p class="lede">
      The suggested semester-by-semester plan and the Entrance to Major courses for each
      University Park major, on one page. More majors are on the way.
    </p>
  </div>

  <div class="wrap prose">
    <ul class="major-list">{items}</ul>
  </div>

{CTA}"""
    return page(head, "page-majors", main)


def update_sitemap(urls: list[str]) -> None:
    path = SITE / "sitemap.xml"
    xml = path.read_text(encoding="utf-8")
    today = date.today().isoformat()
    block = "  <!-- majors -->\n" + "".join(
        f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls
    ) + "  <!-- /majors -->\n"
    if "<!-- majors -->" in xml:
        old = re.search(r"  <!-- majors -->\n.*?  <!-- /majors -->\n", xml, re.DOTALL).group(0)
        # Keep lastmod stable when the URL list hasn't changed.
        if re.sub(r"<lastmod>[^<]*</lastmod>", "", old) == re.sub(r"<lastmod>[^<]*</lastmod>", "", block):
            return
        xml = xml.replace(old, block)
    else:
        xml = xml.replace("</urlset>", block + "</urlset>")
    path.write_text(xml, encoding="utf-8")
    print("updated website/sitemap.xml")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.write_text(build.render(path), encoding="utf-8")


def main() -> int:
    entries = []
    for stem in MAJORS:
        tpl = load(BACKEND / "sap_templates" / f"{stem}.json")
        entries.append((tpl["program_name"], slugify(short_name(tpl["program_name"])), tpl))

    slugs = [s for _, s, _ in entries]
    if len(slugs) != len(set(slugs)):
        raise SystemExit(f"slug collision: {slugs}")

    for _, slug, tpl in entries:
        write(OUT / f"{slug}.html", major_page(tpl, slug))
    write(OUT / "index.html", index_page(entries))

    update_sitemap(["https://gradgps.com/majors/"] + [f"https://gradgps.com/majors/{s}" for s in sorted(slugs)])
    print(f"wrote {len(entries)} major page(s) + index to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
