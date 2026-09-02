"""
Scrape PSU minor / certificate requirement pages into credential_requirements.json.

    python scrape_credentials.py --report            # scrape (cached) + health report
    python scrape_credentials.py --dry-run --report  # no file written
    python scrape_credentials.py --only psychology   # one credential, for debugging
    python scrape_credentials.py --refresh           # ignore the local page cache

Pages are cached under .cache/ so re-runs are offline and instant — the parser is the
part that gets iterated on, and PSU shouldn't be re-crawled for every tweak.

Program discovery comes from the URLs already in PSU_Major_Requirements.xlsx (the
existing scrape found every credential page; what it got wrong was the *parse*).
Finding brand-new credentials needs a fresh crawl — out of scope here, see README.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from courseleaf import parse_courselist
from validate import validate, credit_range, manual_credits
from verify import check as verify_against_psu

HERE       = pathlib.Path(__file__).parent
CACHE_DIR  = HERE / ".cache"
# Written straight into the backend's bundled data directory: one copy, no
# chance of the app shipping a stale duplicate of what this tool produced.
OUT_PATH   = HERE.parent / "backend" / "credential_data" / "credential_requirements.json"
XLSX_PATH  = HERE.parent / "PSU_Major_Requirements.xlsx"

USER_AGENT = "Mozilla/5.0 (GradGPS credential catalog builder)"

# University Park resident-instruction colleges, from routers/programs.py.
# Credential names rarely carry a campus parenthetical — "Business, Minor" has none but
# lives under /colleges/university-college/ — so UP scoping keys off the URL's college
# slug, not the name.
UP_COLLEGE_SLUGS = {
    "agricultural-sciences", "arts-architecture", "business", "communications",
    "earth-mineral-sciences", "education", "engineering",
    "health-human-development", "information-sciences-technology", "intercollege",
    "liberal-arts", "nursing", "science",
}


def college_slug(url: str) -> str:
    parts = [p for p in url.split("/") if p]
    return parts[parts.index("colleges") + 1] if "colleges" in parts else ""


def discover() -> list[dict]:
    """Credential programs (name, kind, college, url) from the existing catalog."""
    import pandas as pd

    df = pd.read_excel(XLSX_PATH, sheet_name="All Requirements", dtype=str).fillna("")
    df = df[df["degree"].isin(["Minor", "Certificate"])]
    out = []
    for (name, degree), sub in df.groupby(["program_name", "degree"]):
        url = sub["url"].iloc[0]
        out.append({
            "program_name": name,
            "kind":         degree.lower(),
            "college":      sub["college"].iloc[0],
            "college_slug": college_slug(url),
            "url":          url,
        })
    return sorted(out, key=lambda p: p["program_name"])


def fetch(url: str, refresh: bool = False) -> str | None:
    CACHE_DIR.mkdir(exist_ok=True)
    key = CACHE_DIR / (url.rstrip("/").split("/")[-1] + ".html")
    if key.exists() and not refresh:
        return key.read_text(encoding="utf-8")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception as exc:
        print(f"    fetch failed: {exc}", file=sys.stderr)
        return None
    key.write_text(html, encoding="utf-8")
    time.sleep(0.4)   # be polite to bulletins.psu.edu
    return html


def build(program: dict, refresh: bool = False) -> dict:
    html = fetch(program["url"], refresh)
    if html is None:
        return {**program, "groups": [], "supported": False,
                "quarantine_reason": "page could not be fetched",
                "warnings": [], "manual_credits": 0}

    groups, warnings = parse_courselist(html)
    entry = {
        "program_name": program["program_name"],
        "kind":         program["kind"],
        "college":      program["college"],
        "url":          program["url"],
        "groups":       groups,
        "warnings":     warnings,
    }
    lo, hi = credit_range(groups)
    entry["credits"] = {"min": lo, "max": hi}

    blockers, review = validate(entry)
    entry["supported"] = not blockers
    entry["quarantine_reason"] = "; ".join(blockers) if blockers else None
    # Credits the student attests to because the bulletin defers them to an adviser.
    # Surfaced so the UI can label them and so coverage stays honest: a supported
    # credential is not necessarily a fully *automatic* one.
    entry["manual_credits"] = manual_credits(groups)
    entry["review_notes"] = review
    # Independent check against PSU's own published credit total (verify.py).  This is
    # the only signal that can catch a parse that is well-formed but wrong.
    entry.update(verify_against_psu(entry, html))
    if entry.get("agrees") is False:
        entry["review_notes"] = review + [
            f"reconstructed {lo:g}-{hi:g} cr but PSU states "
            f"{entry['stated_credits']:g} ({entry['stated_source']})"
        ]
    return entry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    ap.add_argument("--report",  action="store_true", help="print the health table")
    ap.add_argument("--only",    action="append", default=[],
                    help="only programs whose name contains this (repeatable)")
    ap.add_argument("--refresh", action="store_true", help="ignore the local page cache")
    args = ap.parse_args(argv)

    programs = discover()
    if args.only:
        needles  = [n.lower() for n in args.only]
        programs = [p for p in programs
                    if any(n in p["program_name"].lower() for n in needles)]

    # University Park only — same scope as the rest of the app.
    skipped_campus = [p for p in programs if p["college_slug"] not in UP_COLLEGE_SLUGS]
    programs       = [p for p in programs if p["college_slug"] in UP_COLLEGE_SLUGS]

    print(f"Credential pages: {len(programs)} University Park "
          f"({len(skipped_campus)} skipped as non-UP)")

    entries = []
    for i, p in enumerate(programs, 1):
        entry = build(p, args.refresh)
        entries.append(entry)
        if i % 25 == 0:
            print(f"  {i}/{len(programs)}…")

    supported   = [e for e in entries if e["supported"]]
    quarantined = [e for e in entries if not e["supported"]]
    fully_auto  = [e for e in supported if not e.get("manual_credits")]

    if args.report:
        _report(entries, supported, quarantined)

    if not args.dry_run:
        payload = {
            "_generated_by": "credentials/scrape_credentials.py",
            "_source":       "https://bulletins.psu.edu",
            "credentials":   entries,
        }
        OUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n",
                            encoding="utf-8")
        print(f"\nWrote {OUT_PATH} ({len(supported)} supported, "
              f"{len(quarantined)} quarantined)")
    else:
        print("\n(dry run — nothing written)")

    return 0


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def _report(entries, supported, quarantined) -> None:
    total = max(len(entries), 1)
    # "Supported" is not the same as "fully automatic".  A credential PSU defers to an
    # adviser is supported — the app shows the requirement in the bulletin's own words
    # and the student confirms it — but it is not audited end to end, and reporting
    # one number would hide that.
    fully_auto = [e for e in supported if not e.get("manual_credits")]
    partial    = [e for e in supported if e.get("manual_credits")]
    print("\n" + "=" * 78)
    print(f"SUPPORTED   {len(supported):>4} / {len(entries)}"
          f"   ({100*len(supported)/total:.0f}%)")
    print(f"   audited end to end        {len(fully_auto):>4}"
          f"   ({100*len(fully_auto)/total:.0f}%)")
    print(f"   + student-confirmed part  {len(partial):>4}"
          f"   ({100*len(partial)/total:.0f}%)   "
          f"median {_median([e['manual_credits'] for e in partial]):g} cr adviser-chosen")
    print(f"QUARANTINED {len(quarantined):>4} / {len(entries)}")

    # ── Agreement with PSU's own published total ─────────────────────────────
    verifiable = [e for e in entries if e.get("agrees") is not None]
    if verifiable:
        agree = sum(e["agrees"] for e in verifiable)
        by_src = {}
        for e in verifiable:
            by_src[e["stated_source"]] = by_src.get(e["stated_source"], 0) + 1
        print("\nagreement with PSU's own stated credit total:")
        print(f"   verified            {agree:>4} / {len(verifiable)}"
              f"   ({100*agree/len(verifiable):.0f}%)   "
              f"of {len(entries)} credentials")
        for src, n in sorted(by_src.items()):
            print(f"      via {src:<28} {n:>4}")
        bad = [e for e in verifiable if not e["agrees"]]
        for e in bad:
            print(f"      DISAGREES  {e['program_name'][:42]:44} "
                  f"mine={e['credits']['min']:g}-{e['credits']['max']:g} "
                  f"PSU={e['stated_credits']:g}")
        unver = [e for e in entries if e.get("agrees") is None]
        if unver:
            print(f"   no total published  {len(unver):>4}"
                  f"   ({', '.join(e['program_name'][:34] for e in unver[:4])})")

    # ── Secondary yardstick: PSU Senate policy credit bands ──────────────────
    # "No blockers" only says the parse is well-formed, not that it is right, and the
    # pages carry no machine-readable total to diff against.  PSU Senate policy does:
    # a minor is 18-21 credits.  Reconstructing each credential and asking how many
    # land in that band is the only independent accuracy signal available, and it is
    # what caught a 510-credit "minor" that passed every structural check.
    def _overlaps(e, lo, hi):
        return not (e["credits"]["max"] < lo or e["credits"]["min"] > hi)

    minors = [e for e in entries if e["kind"] == "minor"]
    certs  = [e for e in entries if e["kind"] == "certificate"]
    if minors:
        inband = sum(_overlaps(e, 18, 21) for e in minors)
        near   = sum(_overlaps(e, 15, 24) for e in minors)
        print(f"\naccuracy vs PSU's 18-21 credit policy for minors:")
        print(f"   in the 18-21 band   {inband:>4} / {len(minors)}"
              f"   ({100*inband/len(minors):.0f}%)")
        print(f"   within 15-24        {near:>4} / {len(minors)}"
              f"   ({100*near/len(minors):.0f}%)")
        off = [e for e in minors if not _overlaps(e, 15, 24)]
        if off:
            print(f"   outside 15-24 — worth an eyeball ({len(off)}):")
            for e in sorted(off, key=lambda e: -e["credits"]["max"])[:10]:
                print(f"      {e['program_name'][:46]:48} "
                      f"{e['credits']['min']:g}-{e['credits']['max']:g} cr")
    if certs:
        cin = sum(_overlaps(e, 9, 18) for e in certs)
        print(f"   certificates in the typical 9-18 band  {cin:>3} / {len(certs)}"
              f"   ({100*cin/len(certs):.0f}%)")

    notes = [n for e in entries for n in e.get("review_notes", [])]
    if notes:
        from collections import Counter
        import re as _re
        kinds = Counter(_re.sub(r"\d+", "N", n.split("(")[0].split(",")[0].strip())[:56]
                        for n in notes)
        print("\nreview notes (do not block support):")
        for kind, n in kinds.most_common(8):
            print(f"   {n:>4}  {kind}")

    # Credit-total distribution — the headline gate for this phase.
    bands = {"<12": 0, "12-24": 0, ">24": 0}
    for e in entries:
        lo = e["credits"]["min"]
        hi = e["credits"]["max"]
        mid = (lo + hi) / 2
        bands["<12" if mid < 12 else "12-24" if mid <= 24 else ">24"] += 1
    print("\nreconstructed credit total (midpoint of the stated range):")
    for k, v in bands.items():
        print(f"   {k:>6} cr  {v:>4}  {'#' * (v * 60 // max(len(entries), 1))}")

    by_kind = {}
    for e in entries:
        d = by_kind.setdefault(e["kind"], [0, 0])
        d[0] += 1
        d[1] += bool(e["supported"])
    print("\nby kind:")
    for kind, (total, ok) in sorted(by_kind.items()):
        print(f"   {kind:<12} {ok:>3}/{total:<3} supported")

    if quarantined:
        from collections import Counter
        reasons = Counter(
            (e["quarantine_reason"] or "").split(";")[0]
            .split("(")[0].strip()[:64] or "unknown"
            for e in quarantined
        )
        print("\nquarantine reasons:")
        for reason, n in reasons.most_common(12):
            print(f"   {n:>4}  {reason}")

    print("\nsample of quarantined credentials:")
    for e in quarantined[:12]:
        print(f"   {e['program_name'][:46]:48} {e['quarantine_reason'][:70]}")
    print("=" * 78)


if __name__ == "__main__":
    raise SystemExit(main())
