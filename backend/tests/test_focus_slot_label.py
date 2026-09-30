"""
Application Focus plan slots are named after the student's focus state.

Before a focus is picked the slot isn't a course choice — the student has to
choose an area first — so it reads "please select one" and carries
`needs_focus`, which the app routes to the Account page's focus picker.

Run either way:
  * pytest:       cd backend && python -m pytest tests/test_focus_slot_label.py -v
  * plain python: cd backend && python tests/test_focus_slot_label.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.timeline import FOCUS_UNCHOSEN_LABEL, _label_focus_slots  # noqa: E402


def _sems():
    return [
        {"term": "FA 2026", "status": "current", "courses": [
            {"course_code": "Application Focus Course 1", "is_pool": True, "pool_ref": "application_focus"}]},
        {"term": "SP 2027", "status": "upcoming", "courses": [
            {"course_code": "Application Focus Course 1", "course_title": "Choose 3 credit(s)",
             "is_pool": True, "pool_ref": "application_focus"},
            {"course_code": "FIN 301", "is_pool": False, "pool_ref": "application_focus",
             "chosen_code": "FIN 301"},
            {"course_code": "Engineering Technical Elective (ETE)", "is_pool": True,
             "pool_ref": "major_selection"},
        ]},
    ]


def test_no_focus_asks_the_student_to_pick_one():
    sems = _sems()
    _label_focus_slots(sems, None, has_areas=True)
    slot, chosen, other = sems[1]["courses"]
    assert slot["course_code"] == FOCUS_UNCHOSEN_LABEL and slot["needs_focus"] is True
    assert chosen["course_code"] == "FIN 301" and "needs_focus" not in chosen   # a picked course stays
    assert other["course_code"] == "Engineering Technical Elective (ETE)"      # other pools untouched
    assert sems[0]["courses"][0]["course_code"] == "Application Focus Course 1"  # only upcoming terms


def test_chosen_focus_names_the_area():
    sems = _sems()
    _label_focus_slots(sems, "Business Competency", has_areas=True)
    slot = sems[1]["courses"][0]
    assert slot["course_code"] == "Business Competency course"
    assert "needs_focus" not in slot


def test_major_without_focus_areas_is_untouched():
    sems = _sems()
    _label_focus_slots(sems, None, has_areas=False)
    assert sems == _sems()


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} passed")
