#!/usr/bin/env python3
"""Inline the shared site chrome into every page under website/.

Usage:  python tools/site/build.py [--check]

Each page carries marker pairs naming a partial in tools/site/partials/:

    <!--#include header-->
    ...whatever is here is replaced...
    <!--#endinclude header-->

The markers stay in the output, so the build is idempotent and re-runnable.
Output is committed to the repo; .github/workflows/deploy-website.yml uploads
website/ as plain static files, so the served HTML always contains the real nav
links (no client-side includes -- crawlers and link unfurlers can't run JS).

--check exits non-zero if any page is stale, for use in CI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "website"
PARTIALS = Path(__file__).resolve().parent / "partials"

# Page filename -> the canonical path its nav link uses, for aria-current.
SLUGS = {"index.html": "/"}

BLOCK = re.compile(
    r"(?P<open><!--#include (?P<name>[\w-]+)-->)"
    r".*?"
    r"(?P<close><!--#endinclude (?P=name)-->)",
    re.DOTALL,
)


def slug_for(page: Path) -> str:
    return SLUGS.get(page.name, "/" + page.stem)


def mark_current(html: str, slug: str) -> str:
    """Flag the nav link for the page being built (WCAG 2.4.8 / aria-current)."""
    return re.sub(
        r'<a href="%s"(?![^>]*aria-current)' % re.escape(slug),
        '<a href="%s" aria-current="page"' % slug,
        html,
        count=1,
    )


def render(page: Path) -> str:
    original = page.read_text(encoding="utf-8")
    slug = slug_for(page)

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        source = PARTIALS / f"{name}.html"
        if not source.exists():
            raise SystemExit(f"{page.name}: no partial named '{name}' in {PARTIALS}")
        body = source.read_text(encoding="utf-8").strip("\n")
        if name == "header":
            body = mark_current(body, slug)
        return f"{match.group('open')}\n{body}\n{match.group('close')}"

    return BLOCK.sub(replace, original)


def main() -> int:
    check = "--check" in sys.argv
    stale: list[str] = []
    touched = 0

    for page in sorted(SITE.glob("*.html")):
        built = render(page)
        if built == page.read_text(encoding="utf-8"):
            continue
        if check:
            stale.append(page.name)
        else:
            page.write_text(built, encoding="utf-8")
            print(f"updated {page.relative_to(ROOT)}")
            touched += 1

    if check and stale:
        print("stale (run `python tools/site/build.py`): " + ", ".join(stale))
        return 1
    if not check:
        print(f"{touched} page(s) updated" if touched else "all pages already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
