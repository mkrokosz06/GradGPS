"""
Tests for patch_level_pools() (scripts/seed_matthew.py).

The scraper turned bulletin prose rules ("Select 12 credits from the following
ranges: Archaeology: ANTH 420-439 ...", "400-level CMPSC (other than ...)",
"Any LER 400-level course", "MATH 22 or ... placement beyond MATH 22") into
invented course codes, so those requirements could never be completed (or, in
Anthropological Science, demanded courses that don't exist). The patch replaces
them with `dept_credits` rules, real-course pool members, or choose-ones; these
tests run the patch's rows through the same filter + engine GET /audit uses.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_level_pools.py -v
  * plain python:  cd backend && python tests/test_level_pools.py

Hermetic — no network, no DynamoDB (the rows come from the patch's pure helper).
"""

import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from audit_engine import run_audit
from routers.audit import _filter_rows
from seed_matthew import LEVEL_POOLS, level_pool_rows, level_pool_invented, _bulletin

ANTH = "Anthropology, B.A."
ANTH_SCI = "Anthropological Science, B.S."
STAT = "Statistics, B.S."
CRIM = "Criminology, B.S."
SC   = "Statistics and Computing Option (41 credits)"
SSR  = "Social Science Research Option (22-23 credits)"


def _rows(program, group=None):
    return [r for r in level_pool_rows() if r["program_name"] == program
            and (group is None or r["requirement_group"] == group)]


def _spec(program, group):
    return next(s for s in LEVEL_POOLS if s["program"] == program and s["group"] == group)


def _tx(*codes, credits=3, status="done"):
    return [{"course_code": c, "status": status, "grade": "A", "credits_earned": credits}
            for c in codes]


def _pools(program, transcript, subplan=None):
    """{pool_seq: sub-group result} for the patched dept_credits pools."""
    rows = _filter_rows(_rows(program), subplan, set())
    res = run_audit(rows, transcript)
    out = {}
    for g in res["groups"]:
        # A one-pool group comes back homogeneous, without sub_groups.
        seq = next(int(r["pool_seq"]) for r in rows if r["requirement_group"] == g["name"])
        for s in g.get("sub_groups") or [dict(g, pool_seq=seq)]:
            out[s.get("pool_seq")] = s
    return res, out


def _group_results(rows, transcript):
    """{(group, pool_seq or None): result} for every bucket of an audit."""
    res = run_audit(rows, transcript)
    out = {}
    for g in res["groups"]:
        if g.get("sub_groups"):
            for sg in g["sub_groups"]:
                out[(g["name"], sg.get("pool_seq"))] = sg
        else:
            seq = next((int(r["pool_seq"]) for r in rows
                        if r["requirement_group"] == g["name"] and r.get("pool_seq")), None)
            out[(g["name"], seq)] = g
    return res, out


def _done(res):
    return all(g["satisfied"] for g in res["groups"])


# ── Shape ────────────────────────────────────────────────────────────────────

def test_rows_have_no_invented_codes():
    rows = level_pool_rows()
    bulletin = _bulletin()
    for r in rows:
        code = r["course_code"]
        if r["group_type"] == "dept_credits":
            assert code.startswith("__DEPT_CREDITS_")
        elif code != "MATH 40":   # named on the Kinesiology page, gone from the course list
            info = bulletin.get(code) or bulletin.get(code[:-1])   # HDFS 300H -> HDFS 300
            assert info, code
            assert r["course_title"] == info["title"], code
    codes = {r["course_code"] for r in rows}
    for fake in ("ANTH 400", "ANTH 420", "ANTH 440", "CMPSC 451", "LER 400"):
        assert fake not in codes
    # Every row keys uniquely (put_item overwrites → idempotent).
    assert len({(r["program_name"], r["group_course"]) for r in rows}) == len(rows)


def test_invented_selector_matches_only_the_fake_pool():
    spec = _spec(STAT, SC)
    scraped = [
        {"requirement_group": SC, "group_type": "choose_credits", "pool_seq": 1, "course_code": "CMPSC 221"},
        {"requirement_group": SC, "group_type": "choose_credits", "pool_seq": 1, "course_code": "CMPSC 451"},
        # The REAL CMPSC 451 in the 12-credit list must survive.
        {"requirement_group": SC, "group_type": "choose_credits", "pool_seq": 2, "course_code": "CMPSC 451"},
        {"requirement_group": SC, "group_type": "required", "pool_seq": None, "course_code": "CMPSC 465"},
    ]
    hit = level_pool_invented(spec, scraped)
    assert [(r["pool_seq"], r["course_code"]) for r in hit] == [(1, "CMPSC 221"), (1, "CMPSC 451")]
    # Already patched: nothing to delete.
    assert level_pool_invented(spec, scraped[2:]) == []
    # A re-scrape that put other courses in pool 1: refuse to touch it.
    other = scraped + [{"requirement_group": SC, "group_type": "choose_credits",
                        "pool_seq": 1, "course_code": "CMPSC 432"}]
    assert level_pool_invented(spec, other) is None


def test_invented_mode_deletes_only_prose_rows():
    spec = _spec("Physics, B.S. (Science)", "Nanotechnology/Material Science Option (24-25 credits)")
    g = spec["group"]
    fake = {"requirement_group": g, "group_type": "choose_credits", "pool_seq": 1,
            "group_threshold": 12, "course_code": "ESC 400",
            "course_title": "Supporting Course (consult with an academic adviser)",
            "group_course": f"{g}#ESC 400#87"}
    real = {"requirement_group": g, "group_type": "choose_credits", "pool_seq": 1,
            "group_threshold": 12, "course_code": "ESC 312",
            "course_title": "Engineering Applications", "group_course": f"{g}#ESC 312#85"}
    assert level_pool_invented(spec, [fake, real]) == [fake]
    # The real ESC 400 row the patch writes is never matched.
    mine = dict(fake, course_title="Electromagnetic Fields", group_course=f"{g}#ESC 400#LVLPATCH")
    assert level_pool_invented(spec, [mine, real]) == []
    # Neither the invented row nor the patch's rows: the page changed, skip.
    assert level_pool_invented(spec, [real]) is None
    # The invented row sits in some other pool now: skip.
    assert level_pool_invented(spec, [dict(fake, pool_seq=2), real]) is None


def test_choose_one_replaces_scraped_rows_for_its_codes():
    spec = _spec("Linguistics, B.A.", "Requirements for the Major")
    g = spec["group"]
    stat = {"requirement_group": g, "group_type": "required", "course_code": "STAT 200",
            "course_title": "appropriate statistics course", "group_course": f"{g}#STAT 200#1"}
    ling = {"requirement_group": g, "group_type": "required", "course_code": "LING 100",
            "course_title": "Foundations of Linguistics", "group_course": f"{g}#LING 100#2"}
    inserted = {"requirement_group": g, "group_type": "choose_one", "course_code": "STAT 250",
                "course_title": "Introduction to Biostatistics", "group_course": f"{g}#STAT 250"}
    assert level_pool_invented(spec, [stat, ling, inserted]) == [stat, inserted]


# ── Anthropology: 12 credits over three ranges, at least 3 in each ───────────

ANTH_SURVEY = ("ANTH 8", "ANTH 140")


def test_anthropology_completes_with_one_course_per_range_plus_one():
    res, p = _pools(ANTH, _tx(*ANTH_SURVEY, "ANTH 425", "ANTH 401", "ANTH 445", "ANTH 476"))
    assert p[3]["satisfied"] and p[101]["satisfied"] and p[102]["satisfied"] and p[103]["satisfied"]
    assert _done(res)


def test_anthropology_twelve_credits_in_one_range_is_not_enough():
    res, p = _pools(ANTH, _tx(*ANTH_SURVEY, "ANTH 401", "ANTH 402", "ANTH 410", "ANTH 465"))
    assert p[3]["satisfied"]                      # 12 credits in 400-479
    assert p[102]["satisfied"]                    # biological
    assert not p[101]["satisfied"] and not p[103]["satisfied"]
    assert not _done(res)


def test_anthropology_range_edges_and_unrelated_courses():
    # ANTH 480-499 is outside every range; another subject never counts.
    res, p = _pools(ANTH, _tx(*ANTH_SURVEY, "ANTH 492", "ANTH 493", "SOC 401", "ANTH 425"))
    assert p[3]["credits_earned"] == 3
    # 460-473 is biological, 474-479 cultural — not the other way round.
    _, p = _pools(ANTH, _tx("ANTH 470"))
    assert p[102]["satisfied"] and not p[103]["satisfied"]
    _, p = _pools(ANTH, _tx("ANTH 475"))
    assert p[103]["satisfied"] and not p[102]["satisfied"]


def test_anthropology_survey_pool_excludes_prescribed_and_listed_ranges():
    _, p = _pools(ANTH, _tx("ANTH 2", "ANTH 21", "ANTH 45", "ANTH 1", "ANTH 83", "ANTH 195",
                            "ANTH 296", "ANTH 401"))
    assert p[1]["credits_earned"] == 0
    _, p = _pools(ANTH, _tx("ANTH 297", "ANTH 140"))
    assert p[1]["satisfied"]


# ── Anthropological Science: the same ranges, sized per option ───────────────

def test_anthropological_science_options():
    cases = {
        "Archaeological Science Option (33 credits)":
            (("ANTH 420", "ANTH 425", "ANTH 428", "ANTH 432"), ("ANTH 401",), ("ANTH 445",)),
        "Biological Anthropology Option (33 credits)":
            (("ANTH 425",), ("ANTH 401", "ANTH 410", "ANTH 411", "ANTH 465"), ("ANTH 445",)),
        "Integrated Anthropological Science Option (33 credits)":
            (("ANTH 425", "ANTH 428"), ("ANTH 401", "ANTH 465"), ("ANTH 445", "ANTH 476")),
    }
    for group, (arch, bio, cult) in cases.items():
        rows = _rows(ANTH_SCI, group)
        assert all(r["group_type"] == "dept_credits" for r in rows)
        assert _done(run_audit(rows, _tx(*arch, *bio, *cult))), group
        # One course short in the option's main range: not done.
        main = max((arch, bio, cult), key=len)
        short = [c for c in (*arch, *bio, *cult) if c != main[0]]
        assert not _done(run_audit(rows, _tx(*short))), group


def test_anthropological_science_needs_each_range():
    rows = _rows(ANTH_SCI, "Human Ecology Option (33 credits)")
    # 18 credits, all cultural: the 3-credit archaeology and biological pools stay open.
    res, p = _group_results(rows, _tx("ANTH 440", "ANTH 445", "ANTH 450", "ANTH 455",
                                      "ANTH 476", "ANTH 478"))
    assert not _done(res)
    assert sum(1 for v in p.values() if not v["satisfied"]) == 2


def test_anthropological_science_survey_pool():
    rows = _rows(ANTH_SCI, "Common Requirements for the Major (All Options)")
    assert [r["group_type"] for r in rows] == ["dept_credits"]
    assert _done(run_audit(rows, _tx("ANTH 8", "ANTH 140")))
    assert not _done(run_audit(rows, _tx("ANTH 21", "ANTH 140")))   # ANTH 21 is prescribed


# ── Statistics and Computing: CMPSC 221 or 400-level CMPSC except 451/455 ────

def test_statistics_cmpsc_pool():
    res, p = _pools(STAT, _tx("CMPSC 221", "CMPSC 432", "CMPSC 442"), "Statistics and Computing")
    assert p[1]["satisfied"] and _done(res)
    # 451/455 named as exceptions; 465 is prescribed; 300-level and MATH don't count.
    _, p = _pools(STAT, _tx("CMPSC 451", "CMPSC 455", "CMPSC 465", "CMPSC 360", "MATH 451"),
                  "Statistics and Computing")
    assert p[1]["credits_earned"] == 0 and not p[1]["satisfied"]


# ── Criminology Social Science Research: HDFS 401, PLSC 490, any 400-level STAT

def test_criminology_stat_pool():
    res, p = _pools(CRIM, _tx("HDFS 401", "PLSC 490", "STAT 462"), "Social Science Research")
    assert p[2]["satisfied"] and _done(res)
    # STAT 480 is prescribed (and 1 credit); 300-level STAT and other HDFS don't count.
    _, p = _pools(CRIM, _tx("STAT 480", "STAT 301", "HDFS 411", "PLSC 491"), "Social Science Research")
    assert p[2]["credits_earned"] == 0


# ── Course-list pools expanded with the rule's real courses ──────────────────

def test_ler_400_level_rule_is_real_courses():
    for prog, group in (("Psychology, B.S. (Liberal Arts)", "Business Option (24 credits)"),
                        (CRIM, "Business/Public Administration Option (21 credits)")):
        rows = _rows(prog, group)
        codes = {r["course_code"] for r in rows}
        assert "LER 400" not in codes and "LHR 426" in codes and "LER 424" in codes
        assert {r["group_type"] for r in rows} == {"choose_credits"}
        assert {int(r["pool_seq"]) for r in rows} == {1}
        assert {int(r["group_threshold"]) for r in rows} == {15}
        assert all(400 <= int(r["course_code"].split()[1][:3]) <= 499 for r in rows)
        res, p = _group_results(rows, _tx("LHR 426", "LHR 434", "LER 424", "LHR 471", "LHR 480"))
        assert p[(group, 1)]["satisfied"]


def test_physics_esc_400_level():
    rows = _rows("Physics, B.S. (Science)", "Nanotechnology/Material Science Option (24-25 credits)")
    esc400 = next(r for r in rows if r["course_code"] == "ESC 400")
    assert esc400["course_title"] == "Electromagnetic Fields"
    assert "ESC 414M" in {r["course_code"] for r in rows}
    assert not any(r["course_code"].startswith("ESC 3") for r in rows)


def test_hdfs_research_examples_join_the_pool():
    rows = _rows("Human Development and Family Studies, B.S. (Health and Human Development)",
                 "Common Requirements for the Major (All Options)")
    assert {r["course_code"] for r in rows} == {"HDFS 300H", "HDFS 310M"}
    assert {int(r["pool_seq"]) for r in rows} == {5}
    assert all("Additional" not in r["course_title"] for r in rows)


# ── Named course with alternatives -> choose-one ─────────────────────────────

def test_kinesiology_math_is_a_choice_and_kines_1_99_pool():
    rows = _rows("Kinesiology, B.S. (Health and Human Development)",
                 "Exercise Science Option (55-58 credits)")
    math = [r for r in rows if r["group_type"] == "choose_one"]
    assert {r["course_code"] for r in math} >= {"MATH 22", "MATH 110", "MATH 140"}
    assert len({r["pair_group_id"] for r in math}) == 1
    assert not any(r["group_type"] == "required" for r in rows)
    assert _done(run_audit(rows, _tx("MATH 140", "KINES 13")))
    assert not _done(run_audit(rows, _tx("KINES 13")))               # no math course: still owed
    assert not _done(run_audit(rows, _tx("MATH 140", "KINES 101")))  # 101 is outside 1-99


def test_linguistics_stat_alternatives():
    rows = _rows("Linguistics, B.A.", "Requirements for the Major")
    for c in ("STAT 200", "STAT 250", "SCM 200", "DS 200"):
        assert _done(run_audit(rows, _tx(c))), c
    assert not _done(run_audit(rows, _tx("STAT 100")))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
