"""
scrape_crosslistings.py
-----------------------
Scrapes the PSU undergraduate bulletin for all cross-listed courses.
Outputs:
  - cross_listings.csv          (CODE_A, CODE_B, TITLE, EVIDENCE)
  - cross_listings_pairs.py     (ready-to-paste _EQUIVALENCE_PAIRS for audit_engine.py)

Usage:
  python scripts/scrape_crosslistings.py

Takes ~3-5 minutes for all 274 departments.
"""

import re
import csv
import sys
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://bulletins.psu.edu"
INDEX_URL = f"{BASE}/university-course-descriptions/undergraduate/"

# Patterns that indicate cross-listing in a course description
CROSSLIST_PATTERNS = [
    re.compile(r"cross[- ]?listed with[:\s]+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"also offered as[:\s]+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"same as[:\s]+(.+?)(?:\.|$)", re.IGNORECASE),
]

# Extracts individual course codes like "STAT 318", "BMB 251W", "CRIM 100"
CODE_RE = re.compile(r"\b([A-Z]{2,6})\s+(\d+[A-Z]?)\b")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "PSU-Audit-Scraper/1.0 (educational use)"


def get_soup(url: str, retries: int = 3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=15)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            if attempt == retries - 1:
                print(f"  FAILED: {url} — {e}")
                return None
            time.sleep(2)


def get_all_departments() -> list[tuple[str, str]]:
    """Returns list of (dept_name, url) from the bulletin index."""
    soup = get_soup(INDEX_URL)
    if not soup:
        return []
    depts = []
    for a in soup.select("a[href*='/university-course-descriptions/undergraduate/']"):
        href = a["href"]
        # Skip the index page itself and non-dept links
        parts = href.rstrip("/").split("/")
        if len(parts) >= 2 and parts[-2] == "undergraduate" and parts[-1]:
            url = href if href.startswith("http") else BASE + href
            name = a.get_text(strip=True)
            depts.append((name, url))
    # Deduplicate
    seen = set()
    unique = []
    for name, url in depts:
        if url not in seen:
            seen.add(url)
            unique.append((name, url))
    return unique


def extract_cross_listings(dept_url: str) -> list[dict]:
    """Scrape one department page and return all cross-listed course pairs found."""
    soup = get_soup(dept_url)
    if not soup:
        return []

    results = []

    # PSU bulletin structure: each course is in a div or dt/dd block
    # Try multiple selectors to handle layout variations
    course_blocks = (
        soup.select(".courseblock")
        or soup.select("dt")
        or soup.select("h3")
    )

    if not course_blocks:
        # Fallback: search full page text for cross-listing patterns
        text = soup.get_text(" ", strip=True)
        return _extract_from_text(text, dept_url)

    for block in course_blocks:
        # Get the full text of this course block (title + description)
        block_text = block.get_text(" ", strip=True)

        # Try to extract the course code from the block
        primary_match = CODE_RE.search(block_text)
        if not primary_match:
            continue
        primary_code = f"{primary_match.group(1)} {primary_match.group(2)}"

        # Get the course title (first meaningful text before description)
        title = _extract_title(block)

        # Look for cross-listing language
        for pattern in CROSSLIST_PATTERNS:
            m = pattern.search(block_text)
            if not m:
                continue
            raw = m.group(1).strip().rstrip(".")
            # Extract all course codes from the cross-listing note
            partners = CODE_RE.findall(raw)
            for prefix, num in partners:
                partner_code = f"{prefix} {num}"
                if partner_code == primary_code:
                    continue
                results.append({
                    "code_a":   primary_code,
                    "code_b":   partner_code,
                    "title":    title,
                    "evidence": m.group(0).strip(),
                })

    return results


def _extract_title(block) -> str:
    """Try to extract a clean course title from a block element."""
    # Look for strong/b tags (common in PSU bulletin)
    strong = block.find(["strong", "b"])
    if strong:
        return strong.get_text(strip=True)
    text = block.get_text(" ", strip=True)
    # Take first 80 chars as title approximation
    return text[:80].split(".")[0].strip()


def _extract_from_text(text: str, url: str) -> list[dict]:
    """Fallback: scan raw page text for cross-listing notes."""
    results = []
    for pattern in CROSSLIST_PATTERNS:
        for m in pattern.finditer(text):
            # Find the nearest course code before this match
            preceding = text[:m.start()]
            codes_before = CODE_RE.findall(preceding)
            if not codes_before:
                continue
            primary_code = f"{codes_before[-1][0]} {codes_before[-1][1]}"
            raw = m.group(1).strip().rstrip(".")
            partners = CODE_RE.findall(raw)
            for prefix, num in partners:
                partner_code = f"{prefix} {num}"
                if partner_code == primary_code:
                    continue
                results.append({
                    "code_a":   primary_code,
                    "code_b":   partner_code,
                    "title":    "",
                    "evidence": m.group(0).strip(),
                })
    return results


def deduplicate(pairs: list[dict]) -> list[dict]:
    """Remove duplicate pairs (A↔B and B↔A are the same)."""
    seen = set()
    unique = []
    for p in pairs:
        key = tuple(sorted([p["code_a"], p["code_b"]]))
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def write_csv(pairs: list[dict], path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["code_a", "code_b", "title", "evidence"])
        writer.writeheader()
        writer.writerows(pairs)
    print(f"\nCSV written: {path} ({len(pairs)} pairs)")


def write_python(pairs: list[dict], path: Path):
    lines = [
        '# PSU confirmed cross-listings — generated by scrape_crosslistings.py',
        '# Paste this into audit_engine.py as _EQUIVALENCE_PAIRS',
        '_EQUIVALENCE_PAIRS: list[tuple[str, str]] = [',
    ]
    for p in sorted(pairs, key=lambda x: (x["code_a"], x["code_b"])):
        title_comment = f"  # {p['title']}" if p["title"] else ""
        lines.append(f'    ("{p["code_a"]}", "{p["code_b"]}"),{title_comment}')
    lines.append(']')
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Python written: {path}")


def main():
    out_dir = Path(__file__).parent.parent / "scripts"

    print("Fetching department list...")
    depts = get_all_departments()
    print(f"Found {len(depts)} departments.\n")

    all_pairs = []
    for i, (name, url) in enumerate(depts, 1):
        print(f"[{i:>3}/{len(depts)}] {name}...", end=" ", flush=True)
        pairs = extract_cross_listings(url)
        if pairs:
            print(f"{len(pairs)} found")
        else:
            print("none")
        all_pairs.extend(pairs)
        # Be polite to the server
        time.sleep(0.3)

    all_pairs = deduplicate(all_pairs)
    print(f"\nTotal unique pairs: {len(all_pairs)}")

    write_csv(all_pairs, out_dir / "cross_listings.csv")
    write_python(all_pairs, out_dir / "cross_listings_pairs.py")


if __name__ == "__main__":
    main()
