"""
monthly_refresh.py
------------------
Runs on the last day of each month (scheduled via cron).
Refreshes two live data sources that change over time:

  1. PSU bulletin cross-listings  (scrape_crosslistings.py)
     Detects new/removed cross-listed pairs and auto-patches audit_engine.py.

  2. RateMyProfessors professor index  (build_rmp_index.py)
     Refreshes professor ratings in the rmp_professor_courses DynamoDB table.

Usage:
    python scripts/monthly_refresh.py

Cron (last day of month at 2 AM):
    0 2 * * * [ "$(date +\%d)" = "$(cal | awk 'NF{DAYS=$NF}END{print DAYS}')" ] \
        && cd /path/to/backend && python scripts/monthly_refresh.py >> logs/monthly_refresh.log 2>&1
"""

import sys
import os
import re
import subprocess
import asyncio
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

SCRIPTS_DIR   = Path(__file__).parent
BACKEND_DIR   = SCRIPTS_DIR.parent
AUDIT_ENGINE  = BACKEND_DIR / "audit_engine.py"
LOG_PREFIX    = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]"


def log(msg: str):
    print(f"{LOG_PREFIX} {msg}", flush=True)


# ---------------------------------------------------------------------------
# 1. Cross-listing refresh
# ---------------------------------------------------------------------------

def _current_pairs_in_engine() -> set[tuple[str, str]]:
    """Extract the current _EQUIVALENCE_PAIRS from audit_engine.py."""
    text = AUDIT_ENGINE.read_text(encoding="utf-8")
    pairs = re.findall(r'\("([^"]+)",\s*"([^"]+)"\)', text)
    return {tuple(sorted(p)) for p in pairs}


def _scrape_bulletin_pairs() -> list[dict]:
    """Run scrape_crosslistings and return the deduplicated pair list."""
    # Import inline so this file doesn't require bs4 at module load
    sys.path.insert(0, str(SCRIPTS_DIR))
    import scrape_crosslistings as sc
    log("Fetching department list from PSU bulletin...")
    depts = sc.get_all_departments()
    log(f"Found {len(depts)} departments. Scraping...")
    all_pairs = []
    for i, (name, url) in enumerate(depts, 1):
        pairs = sc.extract_cross_listings(url)
        all_pairs.extend(pairs)
        if i % 50 == 0:
            log(f"  {i}/{len(depts)} departments done ({len(all_pairs)} pairs so far)")
        import time; time.sleep(0.3)
    return sc.deduplicate(all_pairs)


def _build_pairs_block(new_pairs: list[dict], existing_manual_pairs: list[tuple[str, str]]) -> str:
    """Build the new _EQUIVALENCE_PAIRS block preserving manual IST/SRA renames."""
    lines = ['_EQUIVALENCE_PAIRS: list[tuple[str, str]] = [']

    # Manual renames always go first (not in bulletin)
    lines.append('    # -- IST -> ETI renames (effective Fall 2025) --')
    lines.append('    # Official IST advising doc: "course content has not changed; ONLY the prefix."')
    for a, b in existing_manual_pairs:
        lines.append(f'    ("{a}", "{b}"),')

    lines.append('    # -- PSU bulletin cross-listings (auto-refreshed monthly) --')
    scrape_set = {tuple(sorted([p["code_a"], p["code_b"]])) for p in new_pairs}
    manual_set = {tuple(sorted(p)) for p in existing_manual_pairs}
    for p in sorted(new_pairs, key=lambda x: (x["code_a"], x["code_b"])):
        key = tuple(sorted([p["code_a"], p["code_b"]]))
        if key in manual_set:
            continue  # already in manual section
        comment = (p.get("title") or p.get("evidence") or "")[:60]
        lines.append(f'    ("{p["code_a"]}", "{p["code_b"]}"),  # {comment}')

    lines.append(']')
    return '\n'.join(lines) + '\n'


MANUAL_PAIRS = [
    ("IST 301", "ETI 301"), ("IST 302", "ETI 302"),
    ("IST 420", "ETI 420"), ("IST 421", "ETI 421"),
    ("IST 311", "HCDD 311"), ("IST 331", "HCDD 331"),
    ("IST 411", "HCDD 411"), ("IST 412", "HCDD 412"),
    ("IST 413", "HCDD 413"), ("IST 446", "HCDD 446"),
    ("IST 451", "CYBER 451"), ("IST 454", "CYBER 454"),
    ("IST 456", "CYBER 456"), ("SRA 221", "CYBER 221"),
]


def refresh_cross_listings():
    log("=== Cross-listing refresh ===")
    before = _current_pairs_in_engine()
    log(f"Current pairs in audit_engine.py: {len(before)}")

    new_pairs = _scrape_bulletin_pairs()
    log(f"Scraped pairs from bulletin: {len(new_pairs)}")

    after = {tuple(sorted([p["code_a"], p["code_b"]])) for p in new_pairs}
    after |= {tuple(sorted(p)) for p in MANUAL_PAIRS}

    added   = after - before
    removed = before - after

    if not added and not removed:
        log("No changes detected. audit_engine.py unchanged.")
        return

    log(f"Changes detected: +{len(added)} added, -{len(removed)} removed")
    for pair in sorted(added):
        log(f"  + {pair[0]} <-> {pair[1]}")
    for pair in sorted(removed):
        log(f"  - {pair[0]} <-> {pair[1]}")

    # Patch audit_engine.py
    engine_text = AUDIT_ENGINE.read_text(encoding="utf-8")
    new_block   = _build_pairs_block(new_pairs, MANUAL_PAIRS)
    start       = engine_text.find('_EQUIVALENCE_PAIRS')
    end_marker  = ']\n\n\n# Build bidirectional'
    end         = engine_text.find(end_marker) + len(']\n')
    if start == -1 or end < len(']\n'):
        log("ERROR: Could not locate _EQUIVALENCE_PAIRS block in audit_engine.py")
        return
    patched = engine_text[:start] + new_block + '\n\n' + engine_text[end:]
    AUDIT_ENGINE.write_text(patched, encoding="utf-8")
    log(f"audit_engine.py updated ({len(before)} -> {len(after)} pairs).")


# ---------------------------------------------------------------------------
# 2. RMP index refresh
# ---------------------------------------------------------------------------

def refresh_rmp():
    log("=== RateMyProfessors index refresh ===")
    try:
        import build_rmp_index
        asyncio.run(build_rmp_index.main())
        log("RMP index refresh complete.")
    except Exception as e:
        log(f"ERROR during RMP refresh: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log("Monthly refresh starting.")

    refresh_cross_listings()
    refresh_rmp()

    log("Monthly refresh complete.")
