"""
monthly_refresh.py
------------------
Scheduled monthly (EventBridge → ECS Fargate task in prod, or run by hand).
Refreshes two live data sources that change over time:

  1. PSU bulletin cross-listings  (scrape_crosslistings.py)
     Writes the scraped pair list to the __CROSSLISTINGS__ item in the
     requirements table — audit_engine loads it from there at startup
     (source patching does not survive container deploys). If
     APP_RUNNER_SERVICE_ARN is set, a new App Runner deployment is
     triggered so the running service picks the pairs up immediately.

  2. RateMyProfessors professor index  (build_rmp_index.py)
     Refreshes professor ratings in the rmp_professor_courses DynamoDB table.

Usage:
    python scripts/monthly_refresh.py
"""

import sys
import os
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

SCRIPTS_DIR   = Path(__file__).parent
BACKEND_DIR   = SCRIPTS_DIR.parent
LOG_PREFIX    = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]"

CROSSLIST_KEY = {"program_name": "__CROSSLISTINGS__", "group_course": "pairs"}


def log(msg: str):
    print(f"{LOG_PREFIX} {msg}", flush=True)


# ---------------------------------------------------------------------------
# 1. Cross-listing refresh
# ---------------------------------------------------------------------------

def _current_scraped_pairs() -> set[tuple[str, str]]:
    """Scraped pairs currently in effect: DynamoDB item, else bundled snapshot."""
    from db import requirements_table
    item = requirements_table.get_item(Key=CROSSLIST_KEY).get("Item")
    if item and item.get("pairs"):
        return {tuple(sorted([str(a), str(b)])) for a, b in item["pairs"]}
    from audit_engine import _BUNDLED_CROSSLISTINGS
    return {tuple(sorted(p)) for p in _BUNDLED_CROSSLISTINGS}


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


def refresh_cross_listings():
    log("=== Cross-listing refresh ===")
    before = _current_scraped_pairs()
    log(f"Scraped pairs currently in effect: {len(before)}")

    new_pairs = _scrape_bulletin_pairs()
    log(f"Scraped pairs from bulletin: {len(new_pairs)}")
    if not new_pairs:
        log("ERROR: scrape returned zero pairs — keeping existing data.")
        return

    after = {tuple(sorted([p["code_a"], p["code_b"]])) for p in new_pairs}

    added   = after - before
    removed = before - after
    if not added and not removed:
        log("No changes detected. DynamoDB item left as-is.")
        return

    log(f"Changes detected: +{len(added)} added, -{len(removed)} removed")
    for pair in sorted(added):
        log(f"  + {pair[0]} <-> {pair[1]}")
    for pair in sorted(removed):
        log(f"  - {pair[0]} <-> {pair[1]}")

    write_crosslistings_item(sorted(after))
    log(f"__CROSSLISTINGS__ item updated ({len(before)} -> {len(after)} pairs).")
    _redeploy_app_runner()


def write_crosslistings_item(pairs: list[tuple[str, str]]) -> None:
    """Store scraped pairs (manual renames live in audit_engine, not here)."""
    from db import requirements_table
    requirements_table.put_item(Item={
        **CROSSLIST_KEY,
        "pairs":      [[a, b] for a, b in pairs],
        "pair_count": len(pairs),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def _redeploy_app_runner():
    """
    audit_engine reads cross-listings at startup, so the running service only
    sees new pairs after a restart. Opt-in via APP_RUNNER_SERVICE_ARN.
    """
    arn = os.getenv("APP_RUNNER_SERVICE_ARN", "").strip()
    if not arn:
        log("APP_RUNNER_SERVICE_ARN not set — service picks up pairs on next deploy.")
        return
    try:
        import boto3
        boto3.client("apprunner").start_deployment(ServiceArn=arn)
        log("App Runner redeploy triggered.")
    except Exception as e:
        log(f"WARNING: App Runner redeploy failed (data is saved regardless): {e}")


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
