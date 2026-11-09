"""
Option auto-pick for a student who chose "Undecided / No preference".

_pick_best_option() used to count every course an option lists, so the option
with the longest list won even when the transcript clearly belonged to another
(a transcript built to finish one Biology option was audited against a bigger
one). It now scores courses unique to an option first, then the share of the
option's own list covered, matching through renames and stored suffix forms.
Across every multi-option program in the catalog this took wrong picks from
86/580 to 18/580; the 18 are options whose course lists are identical or nested.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_option_autopick.py -v
  * plain python:  cd backend && python tests/test_option_autopick.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.audit import _filter_rows


def _rows(spec):
    return [{"program_name": "X", "requirement_group": g, "group_type": "required",
             "course_code": c} for g, cs in spec.items() for c in cs]


SPEC = {
    "Common Requirements for the Major (All Options)": ["BIOL 110"],
    "Small Option (20 credits)": ["BIOL 220", "BIOL 230", "BIOL 401"],
    # Longer list that shares most of Small's courses.
    "Big Option (30 credits)": ["BIOL 220", "BIOL 230", "BIOL 300", "BIOL 301",
                                "BIOL 302", "BIOL 303"],
}


def _picked(tx):
    return {r["requirement_group"] for r in _filter_rows(_rows(SPEC), None, set(tx))
            if "Option (" in r["requirement_group"]}


def test_finishing_small_option_picks_it_over_longer_overlapping_one():
    assert _picked({"BIOL 220", "BIOL 230", "BIOL 401"}) == {"Small Option (20 credits)"}


def test_unique_course_decides():
    assert _picked({"BIOL 220", "BIOL 300"}) == {"Big Option (30 credits)"}


def test_shared_only_prefers_higher_coverage():
    # 2 of Small's 3 vs 2 of Big's 6.
    assert _picked({"BIOL 220", "BIOL 230"}) == {"Small Option (20 credits)"}


def test_common_rows_always_kept():
    rows = _filter_rows(_rows(SPEC), None, {"BIOL 300"})
    assert any(r["course_code"] == "BIOL 110" for r in rows)


def test_writing_suffix_on_requirement_matches_stored_code():
    spec = {"A Option (x)": ["ENGL 202"], "B Option (x)": ["HIST 400W"]}
    got = {r["requirement_group"] for r in _filter_rows(_rows(spec), None, {"HIST 400"})}
    assert got == {"B Option (x)"}


def test_chosen_subplan_is_not_overridden():
    got = {r["requirement_group"] for r in _filter_rows(_rows(SPEC), "Big", {"BIOL 401"})
           if "Option (" in r["requirement_group"]}
    assert got == {"Big Option (30 credits)"}


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
           if n.startswith("test_")]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)} passed")
