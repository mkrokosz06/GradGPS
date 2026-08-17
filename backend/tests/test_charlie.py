"""
Tests for Charlie's pure logic — school-name normalization and catalog-platform
detection. No network, no DynamoDB (run_triage's fetch is not exercised here).

Runnable two ways:
  * pytest:       cd backend && python -m pytest tests/test_charlie.py -v
  * plain python: cd backend && python tests/test_charlie.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from charlie import normalize_school, detect_catalog_platform


# ── Normalization: aliases collapse to one canonical school ──────────────────

def test_psu_spellings_all_resolve_to_penn_state():
    for raw in ["Penn State", "pennsylvania state university", "PSU",
                "penn state university", "Happy Valley", "  psu  "]:
        r = normalize_school(raw)
        assert r is not None, raw
        assert r["school_key"] == "penn-state", raw
        assert r["canonical_name"] == "Penn State", raw
        assert r["matched"] is True, raw


def test_fuzzy_handles_typos_and_extra_words():
    # Long strings are fuzzy-eligible; minor typos still land.
    assert normalize_school("pennsylvania state univ")["school_key"] == "penn-state"
    assert normalize_school("university of californa berkeley")["school_key"] == "uc-berkeley"


def test_acronyms_match_exactly_never_fuzzily():
    # osu and asu are one edit apart — exact-only matching must keep them distinct.
    assert normalize_school("osu")["school_key"] == "ohio-state"
    assert normalize_school("asu")["school_key"] == "arizona-state"


def test_penn_is_ambiguous_and_not_silently_matched():
    # Bare "penn" is deliberately not an alias of Penn State OR UPenn.
    r = normalize_school("penn")
    assert r["matched"] is False
    assert r["school_key"].startswith("unmatched-")


def test_upenn_distinct_from_penn_state():
    assert normalize_school("upenn")["school_key"] == "upenn"
    assert normalize_school("university of pennsylvania")["school_key"] == "upenn"


def test_unknown_school_gets_provisional_canonical():
    r = normalize_school("Slippery Rock University")
    assert r["matched"] is False
    assert r["school_key"] == "unmatched-slippery-rock-university"
    assert r["canonical_name"] == "Slippery Rock University"


def test_garbage_input_rejected():
    assert normalize_school("") is None
    assert normalize_school("x") is None
    assert normalize_school("!!!") is None      # cleans to empty
    assert normalize_school("a" * 200) is None


def test_punctuation_and_ampersand_folding():
    assert normalize_school("Texas A&M")["school_key"] == "texas-am"
    assert normalize_school("texas a and m")["school_key"] == "texas-am"


# ── Catalog-platform detection ────────────────────────────────────────────────

def test_detect_courseleaf():
    html = '<div class="sc_plangrid"><a href="/coursesaz/math/">Math</a></div>'
    assert detect_catalog_platform(html) == "CourseLeaf"


def test_detect_acalog():
    assert detect_catalog_platform('<a href="preview_program.php?catoid=1">') == "Acalog"


def test_detect_kuali():
    assert detect_catalog_platform('<script src="https://x.kuali.co/app.js">') == "Kuali"


def test_detect_none_on_plain_html():
    assert detect_catalog_platform("<html><body>Welcome</body></html>") is None
    assert detect_catalog_platform("") is None


# ── Plain-python runner ───────────────────────────────────────────────────────

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"  ERR  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
