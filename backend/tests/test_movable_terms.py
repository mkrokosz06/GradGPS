"""Semester chips in the class selector: where each upcoming slot may be pinned.

Runs under pytest or plain `python`. Uses the real bulletin requisites:
ETI 420 needs ETI 301 + ETI 302 (+ IST 242); ETI 421 needs ETI 420.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routers.timeline import _mark_movable_terms  # noqa: E402

DONE = {"IST 210", "IST 220", "IST 242"}


def _c(code, **kw):
    return dict({"course_code": code, "credits_earned": 3.0, "slot_key": f"course:{code}"}, **kw)


def _sem(term, *courses):
    return {"term": term, "courses": list(courses)}


def _moves(future, **kw):
    _mark_movable_terms(future, DONE, None, **kw)
    return {c["course_code"]: c["movable_terms"] for s in future for c in s["courses"]}


def test_course_stays_after_its_prerequisite_and_before_what_needs_it():
    out = _moves([_sem("FA 2026", _c("ETI 301"), _c("ETI 302")),
                  _sem("SP 2027", _c("ETI 420")),
                  _sem("FA 2027", _c("ETI 421"))])
    assert out["ETI 420"] == ["SP 2027"]                 # 301/302 before, 421 after
    assert out["ETI 421"] == ["FA 2027", "SP 2028"]      # may slip one past the end
    assert out["ETI 301"] == ["FA 2026"]                 # ETI 420 needs it first


def test_placeholder_goes_anywhere_and_internship_stays_in_summer():
    out = _moves([_sem("FA 2026", _c("Elective", slot_key="pool:X#0")),
                  _sem("SU 2027", _c("IST 495")),
                  _sem("FA 2027", _c("GEOG 30"))])
    assert out["Elective"] == ["FA 2026", "FA 2027", "SP 2028"]
    assert out["IST 495"] == ["SU 2027"]


def test_major_only_course_not_before_entrance():
    out = _moves([_sem("FA 2026", _c("GEOG 30")), _sem("SP 2027", _c("ETI 301"))],
                 locked=lambda c: c["course_code"].startswith("ETI"), unlock_term="SP 2027")
    assert out["ETI 301"] == ["SP 2027", "FA 2027"]
    assert out["GEOG 30"] == ["FA 2026", "SP 2027", "FA 2027"]


def test_an_alternative_keeps_a_choose_one_slot_viable():
    # ETI 463 needs ETI 461, but ETI 435 (only IST 210) still fills the slot.
    out = _moves([_sem("FA 2026", _c("ETI 461")),
                  _sem("SP 2027", _c("ETI 435 or ETI 463", slot_key="one:ETI 435|ETI 463"))])
    assert "SP 2027" in out["ETI 461"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
