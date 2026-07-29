"""
scrape_course_titles.py
-----------------------
Scrapes canonical course titles for EVERY undergraduate course from the PSU
bulletin course-description pages (same pages scrape_gen_ed_courses.py walks,
but keeping all courses, not just gen-ed ones).

Output: scripts/bulletin_course_titles.json  mapping course_code -> title.
fix_junk_titles.py uses it as the authoritative source for codes whose title
is junk in every catalog row.

Usage:
    python scripts/scrape_course_titles.py    # ~5-10 min, ~274 departments
"""

import re
import sys
import json
import time
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.append(str(Path(__file__).parent))
from scrape_gen_ed_courses import get_soup, get_all_departments, _CODE_RE, _CREDITS_RE

OUT_PATH = Path(__file__).parent / "bulletin_course_titles.json"


def scrape_department_titles(dept_url: str) -> dict[str, str]:
    soup = get_soup(dept_url)
    if not soup:
        return {}
    titles = {}
    for block in soup.select(".courseblock"):
        title_el = block.select_one(".courseblocktitle") or block.find(["strong", "b"])
        if not title_el:
            continue
        raw = title_el.get_text(" ", strip=True)
        m = _CODE_RE.search(raw)
        if not m:
            continue
        code = f"{m.group(1)} {m.group(2)}"
        title = _CODE_RE.sub("", raw, count=1)
        title = _CREDITS_RE.sub("", title)
        title = re.sub(r"\s{2,}", " ", title).strip(" ():-–—,;")
        if title:
            titles[code] = title
    return titles


def scrape_all_titles() -> dict[str, str]:
    print("Fetching department list...", flush=True)
    depts = get_all_departments()
    print(f"Found {len(depts)} departments.", flush=True)

    titles: dict[str, str] = {}
    for i, (name, url) in enumerate(depts, 1):
        found = scrape_department_titles(url)
        for code, title in found.items():
            titles.setdefault(code, title)
        if i % 25 == 0 or i == len(depts):
            print(f"  [{i}/{len(depts)}] {len(titles)} titles so far", flush=True)
        time.sleep(0.3)
    return titles


if __name__ == "__main__":
    titles = scrape_all_titles()
    OUT_PATH.write_text(json.dumps(titles, indent=1, ensure_ascii=False, sort_keys=True),
                        encoding="utf-8")
    print(f"\nWrote {len(titles)} course titles to {OUT_PATH}")
