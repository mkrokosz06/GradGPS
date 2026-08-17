"""
Charlie — the "add my school" agent.

Charlie is GradGPS's demand funnel and onboarding scout for schools we don't yet
support. It has two jobs, and deliberately NOT a third:

  1. Capture & normalize  — take whatever a student types ("Penn State" /
     "Pennsylvania State University" / "PSU") and resolve it to ONE canonical
     school so demand can be counted per school, not per spelling.
  2. Feasibility triage    — for a canonical school, probe how expensive it is to
     actually add: what catalog platform it runs, whether that platform matches
     PSU's (CourseLeaf), and where a human still has to step in. Produces a
     "readiness report" structured around the three honest questions (below).

  NOT autonomous onboarding. Charlie never ingests a school or flips it live —
  the whole value of GradGPS is audit accuracy, and a half-automated school with
  subtle errors is worse than no support. Triage informs the roadmap; a human
  builds and signs off. See docs/charlie.md.

This module is pure/DB-free except run_triage()'s optional catalog fetch, so the
normalizer and platform detector are unit-testable without network or DynamoDB.
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import httpx

_SEED_PATH = Path(__file__).parent / "charlie_schools.json"


# ── Seed roster ───────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    """Lowercase, drop punctuation, fold '&'→'and', collapse whitespace/hyphens."""
    s = (s or "").strip().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = re.sub(r"[\s-]+", " ", s).strip()
    return s


def _load_seed() -> list[dict]:
    raw = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    schools = raw["schools"]
    for sc in schools:
        # match_terms: every string a user might type, pre-cleaned. Split into
        # short (acronym-like, exact-match only) and long (fuzzy-eligible) so
        # "osu" can never fuzzy-collide with "asu".
        terms = {_clean(sc["name"]), *(_clean(a) for a in sc.get("aliases", []))}
        terms.discard("")
        sc["_terms_all"]   = terms
        sc["_terms_fuzzy"] = {t for t in terms if " " in t or len(t) > 5}
    return schools


SEED = _load_seed()

_FUZZY_THRESHOLD = 0.86


def get_seed_school(key: str) -> dict | None:
    for sc in SEED:
        if sc["key"] == key:
            return sc
    return None


# ── Normalization (job 1) ─────────────────────────────────────────────────────

def normalize_school(raw: str) -> dict | None:
    """
    Resolve a free-typed school name to a canonical record.

    Returns {"school_key", "canonical_name", "matched"} or None if the input
    isn't a plausible school name at all. `matched=False` means Charlie made a
    provisional canonical from the raw text (no roster hit) — still counted, but
    flagged for a human to confirm/merge.
    """
    cleaned = _clean(raw)
    if len(cleaned) < 2 or len(cleaned) > 100:
        return None

    # 1. Exact hit on any name/alias (covers acronyms like "psu", "ucla").
    for sc in SEED:
        if cleaned in sc["_terms_all"]:
            return {"school_key": sc["key"], "canonical_name": sc["name"], "matched": True}

    # 2. Fuzzy — long strings only. Short/acronym inputs must match exactly
    #    (step 1) or they fall through; fuzzing 3-letter codes is a collision trap.
    if len(cleaned) > 5 or " " in cleaned:
        best, best_ratio = None, 0.0
        for sc in SEED:
            for term in sc["_terms_fuzzy"]:
                r = SequenceMatcher(None, cleaned, term).ratio()
                if cleaned in term or term in cleaned:
                    r = max(r, 0.9)
                if r > best_ratio:
                    best_ratio, best = r, sc
        if best and best_ratio >= _FUZZY_THRESHOLD:
            return {"school_key": best["key"], "canonical_name": best["name"], "matched": True}

    # 3. No roster hit — provisional canonical from the raw text.
    slug = re.sub(r"\s+", "-", cleaned)[:60].strip("-")
    return {
        "school_key": f"unmatched-{slug}",
        "canonical_name": " ".join(w.capitalize() for w in cleaned.split()),
        "matched": False,
    }


# ── Feasibility triage (job 2) ────────────────────────────────────────────────

# Signatures that identify a catalog platform from its rendered HTML. CourseLeaf
# is the one PSU runs, so detecting it is the strongest "scraper reuse" signal.
_CATALOG_SIGNATURES: list[tuple[str, list[str]]] = [
    ("CourseLeaf", ["courseleaf", "sc_courselist", "sc_plangrid", "/coursesaz", "ribbit"]),
    ("Acalog",     ["acalog", "preview_program.php", "content.php?catoid", "preview_entity.php"]),
    ("Kuali",      ["kuali", "kuali.co", "/api/cm/"]),
    ("Ellucian/Banner", ["bwckctlg", "bwckschd", "ellucian"]),
]

_UA = "Mozilla/5.0 (compatible; GradGPS-Charlie/1.0; +https://gradgps.com)"


def detect_catalog_platform(html: str) -> str | None:
    """Sniff catalog-platform vendor from page HTML. Pure — unit-testable."""
    low = (html or "").lower()
    for name, sigs in _CATALOG_SIGNATURES:
        if any(sig in low for sig in sigs):
            return name
    return None


def _scraper_reuse(platform: str | None) -> tuple[str, str]:
    if platform == "CourseLeaf":
        return "high", "Runs CourseLeaf, same as PSU — the catalog scraper is largely reusable (verify the sc_plangrid/table structure matches)."
    if platform:
        return "low", f"Runs {platform}, not CourseLeaf — the catalog scraper needs a rewrite for this platform."
    return "unknown", "Catalog platform not detected — provide a catalog URL or identify it manually."


async def _fetch(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True,
                                     headers={"User-Agent": _UA}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception:
        return None


async def run_triage(school: dict, catalog_url: str | None = None) -> dict:
    """
    Produce a readiness report for a (canonical) school. `school` is a
    school_requests record or a seed record; both may carry key/name/domain/
    catalog_url/sis/rmp_school_id.

    The report is structured around the three honest questions from the design:
      can_get_data       — is the data reachable, and does the scraper transfer?
      code_grammar_risk  — will their course-code format break the parser's
                           PSU assumptions (suffixes, spacing, numbering)?
      gen_ed_distance    — how far is their gen-ed *ontology* from PSU's model?
    Plus supporting signals (sis, professor ratings) and an overall verdict.

    Only can_get_data is meaningfully automatable today; the other two are
    surfaced as explicit "needs manual review" prompts, never guessed.
    """
    seed = get_seed_school(school.get("school_key") or school.get("key") or "")
    url = catalog_url or school.get("catalog_url") or (seed or {}).get("catalog_url")

    # --- Q1: can I get the data? ---
    platform = (seed or {}).get("catalog_platform")
    fetched_url = None
    if url:
        html = await _fetch(url)
        fetched_url = url
        detected = detect_catalog_platform(html) if html else None
        platform = detected or platform
    reuse_level, reuse_detail = _scraper_reuse(platform)
    can_get_data = {
        "catalog_url": fetched_url,
        "catalog_platform": platform,
        "scraper_reuse": reuse_level,
        "detail": reuse_detail,
    }

    # --- Q2: does their course-code grammar break the parser? ---
    if platform == "CourseLeaf":
        code_grammar_risk = {
            "level": "medium",
            "detail": "CourseLeaf catalogs still vary in code format. Verify the parser's PSU assumptions hold: attribute suffixes (W/H/N), 'SUBJ NNN' spacing, and 1–4 digit numbering.",
        }
    else:
        code_grammar_risk = {
            "level": "unknown",
            "detail": "Sample a few course codes and compare against the parser's SUBJECT+NUMBER+suffix assumptions before trusting catalog matching.",
        }

    # --- Q3: how far is their gen-ed ontology from ours? ---
    gen_ed_distance = {
        "level": "unknown",
        "detail": "Requires manual review. Gen-ed is an ontology, not a course list — there is no reliable automated signal. Map their categories to the audit's gen-ed model by hand.",
    }

    # --- Supporting: SIS + professor ratings ---
    sis = (seed or {}).get("sis")
    sis_info = {
        "name": sis,
        "detail": (f"Known SIS: {sis}." if sis
                   else "SIS unknown — needed for the transcript parser. Obtain sample transcript PDFs; a parser can't be written without them."),
    }
    rmp_id = (seed or {}).get("rmp_school_id")
    ratings = {
        "available": bool(rmp_id) if rmp_id is not None else None,
        "detail": ("Professor-ratings source is mapped for this school."
                   if rmp_id else "Professor-ratings coverage not confirmed — check before promising the feature; gate the UI off it if absent."),
    }

    # --- Overall verdict ---
    if platform == "CourseLeaf" and sis:
        overall = "green"
        summary = "Same catalog platform as PSU and a known SIS — cheapest tier to add. Still needs gen-ed mapping and transcript samples."
    elif platform == "CourseLeaf":
        overall = "yellow"
        summary = "CourseLeaf catalog (scraper reusable), but SIS/transcript layout unknown — get sample transcripts next."
    elif platform:
        overall = "yellow"
        summary = f"{platform} catalog — scraper rewrite required. Estimate that cost before committing."
    else:
        overall = "unknown"
        summary = "Not enough signal yet — supply a catalog URL so Charlie can detect the platform."

    return {
        "can_get_data": can_get_data,
        "code_grammar_risk": code_grammar_risk,
        "gen_ed_distance": gen_ed_distance,
        "sis": sis_info,
        "professor_ratings": ratings,
        "overall": overall,
        "summary": summary,
    }
