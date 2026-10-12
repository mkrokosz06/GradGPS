"""
Tests for patch_adviser_defined_majors() (scripts/seed_matthew.py).

Integrative Arts B.A. and Multidisciplinary Studies B.A. publish no course list,
only credit buckets chosen with an adviser. Their scraped rows were all plan-grid
duplicates that routers.audit._filter_rows drops, so the audit came back empty.
The patch adds one `unstructured_credits` row per bucket; these tests run those
rows through the same filter + engine GET /audit uses.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_adviser_defined_majors.py -v
  * plain python:  cd backend && python tests/test_adviser_defined_majors.py

Hermetic — no network, no DynamoDB (the rows come from the patch's pure helper).
"""

import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from audit_engine import run_audit
from routers.audit import _filter_rows
from seed_matthew import ADVISER_DEFINED_MAJORS, adviser_defined_rows

IA  = "Integrative Arts, B.A. (Arts and Architecture)"
MDS = "Multidisciplinary Studies, B.A. (Liberal Arts)"

# The scraped plan-grid rows that stay in the table alongside the patch.
GRID = {
    IA:  [{"program_name": IA, "requirement_group": "Integrative Arts, B.A. at University Park Campus",
           "course_code": "ENGL 202B", "group_type": "choose_one", "credits": 3}],
    MDS: [{"program_name": MDS, "requirement_group": "Multidisciplinary Studies, B.A. at Commonwealth Campuses",
           "course_code": "ENGL 15", "group_type": "choose_one", "credits": 3}],
}


def _rows(program):
    return [r for r in adviser_defined_rows() if r["program_name"] == program] + GRID[program]


def _audit(program, transcript=()):
    return run_audit(_filter_rows(_rows(program), None, set()), list(transcript))


def test_row_counts_and_shape():
    rows = adviser_defined_rows()
    assert sum(r["program_name"] == IA for r in rows) == 3
    assert sum(r["program_name"] == MDS for r in rows) == 5
    assert len({(r["program_name"], r["group_course"]) for r in rows}) == len(rows)  # fixed, unique keys
    for r in rows:
        assert r["group_type"] == "unstructured_credits"
        assert r["min_grade"] == "C"
        assert r["pool_text"] and r["group_threshold"] > 0


def test_section_credits_match_bulletin():
    total = lambda p: sum(float(r["group_threshold"]) for r in adviser_defined_rows()
                          if r["program_name"] == p)
    assert total(IA) == 42   # "Requirements for the Major 42"
    assert total(MDS) == 36  # "Requirements for the Major 36"


def test_filter_keeps_patch_drops_grid():
    for program in (IA, MDS):
        kept = _filter_rows(_rows(program), None, set())
        assert {r["group_type"] for r in kept} == {"unstructured_credits"}
        assert len(kept) == len(ADVISER_DEFINED_MAJORS[program]["groups"])


def test_empty_transcript_missing_equals_sections():
    for program in (IA, MDS):
        res = _audit(program)
        n = len(ADVISER_DEFINED_MAJORS[program]["groups"])
        assert len(res["groups"]) == n
        assert res["missing"] == n and res["done"] == 0 and res["total"] == n


def test_never_auto_satisfied():
    # A transcript full of plausible arts / 400-level courses must not satisfy any bucket.
    transcript = [{"course_code": c, "status": "done", "grade": "A", "credits_earned": 3}
                  for c in ("ART 10", "ART 401", "MUSIC 5", "THEA 100", "ARTH 111",
                            "ARTH 112", "HIST 420", "PSYCH 490", "ENGL 202B", "CAS 100A")]
    for program in (IA, MDS):
        res = _audit(program, transcript)
        assert res["done"] == 0
        assert all(not g["satisfied"] for g in res["groups"])


def test_groups_carry_wording_and_needs_confirmation():
    for program in (IA, MDS):
        texts = {r["requirement_group"]: r["pool_text"]
                 for r in adviser_defined_rows() if r["program_name"] == program}
        for g in _audit(program)["groups"]:
            assert g["needs_confirmation"] is True
            assert g["pool_text"] == texts[g["name"]]


def test_groups_not_offered_as_tracks():
    # get_subplans derives "tracks" from group names; a bucket must never show up
    # in the major picker as an option (it would also narrow the audit to itself).
    import routers.audit as audit_router

    class _FakeTable:
        def __init__(self, rows):
            self.rows = rows

        def query(self, **_kw):
            return {"Items": [{"requirement_group": r["requirement_group"]} for r in self.rows]}

    original = audit_router.requirements_table
    try:
        for program in (IA, MDS):
            audit_router.requirements_table = _FakeTable(_rows(program))
            assert audit_router.get_subplans(program)["subplans"] == []
    finally:
        audit_router.requirements_table = original


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
