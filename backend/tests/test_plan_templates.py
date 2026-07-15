"""
Tests for SAP plan templates (data/plan_templates/*.json + plan_templates.py).

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_plan_templates.py -v
  * plain python:  cd backend && python tests/test_plan_templates.py

The structural/credit tests are hermetic.  An optional catalog cross-check runs
only when a DynamoDB catalog is reachable (set CHECK_CATALOG=1) — it confirms
every fixed course a template pins actually exists in the requirements catalog.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plan_templates import (
    _all_templates,
    load_template,
    validate_template,
    fixed_codes,
    pinned_course_codes,
    iter_slots,
    slot_credits,
)


def test_at_least_one_template_present():
    assert len(_all_templates()) >= 1


def test_every_template_is_structurally_valid():
    for tpl in _all_templates():
        problems = validate_template(tpl)
        assert not problems, f"{tpl.get('_file')}: {problems}"


def test_accounting_template_loads_and_totals_120():
    tpl = load_template("Accounting, B.S. (Business)")
    assert tpl is not None
    assert tpl["total_credits"] == 120
    assert len(tpl["semesters"]) == 8
    grand = sum(slot_credits(s) for sem in tpl["semesters"] for s in sem["slots"])
    assert abs(grand - 120) < 0.01


def test_accounting_template_has_sap_only_requirements():
    # These are exactly the buckets the pure-audit timeline was missing — their
    # presence is the reason the SAP backbone exists.
    tpl = load_template("Accounting, B.S. (Business)")
    labels = " ".join(
        (s.get("label") or "") + " " + (s.get("ref") or "")
        for sem in tpl["semesters"] for s in sem["slots"]
    ).lower()
    assert "world_language" in labels
    assert "business_breadth" in labels
    codes = fixed_codes(tpl)
    assert "PSU 6" in codes
    assert "ACCTG 211" in codes


def test_load_template_unknown_returns_none():
    assert load_template("Definitely Not A Real Major, B.S.") is None


def test_catalog_crosscheck_fixed_courses_exist():
    # Opt-in: needs a seeded DynamoDB catalog.
    if os.environ.get("CHECK_CATALOG") != "1":
        try:
            import pytest
            pytest.skip("set CHECK_CATALOG=1 to run the catalog cross-check")
        except ImportError:
            print("  SKIP: set CHECK_CATALOG=1 to run the catalog cross-check")
            return
    from db import requirements_table
    from boto3.dynamodb.conditions import Key
    import re

    def base(code):  # strip a trailing W/H/N attribute suffix for matching
        m = re.match(r"^([A-Z]+ \d+)[WHN]?$", code.strip().upper())
        return m.group(1) if m else code.strip().upper()

    # Collect every course code catalogued anywhere (major rows + gen ed).
    known: set[str] = set()
    for prog in ("Accounting, B.S. (Business)", "__GEN_ED__"):
        resp = requirements_table.query(KeyConditionExpression=Key("program_name").eq(prog))
        rows = resp.get("Items", [])
        while "LastEvaluatedKey" in resp:
            resp = requirements_table.query(
                KeyConditionExpression=Key("program_name").eq(prog),
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            rows.extend(resp.get("Items", []))
        for r in rows:
            known.add(base(r.get("course_code", "")))

    tpl = load_template("Accounting, B.S. (Business)")

    # (a) Every hard-pinned single course must exist (PSU 6 is a program-entry
    #     milestone, not a catalog course — excluded).
    missing = sorted(c for c in pinned_course_codes(tpl)
                     if base(c) not in known and c != "PSU 6")
    assert not missing, f"template pins courses absent from catalog: {missing}"

    # (b) Every choose_one group must have at least one option in the catalog,
    #     so the group is actually satisfiable.  Match is prefix-aware because the
    #     catalog keeps section letters (speech is catalogued as CAS 100A/B/C,
    #     while the SAP writes "CAS 100"); a template code satisfies a catalog code
    #     that starts with it.
    def catalogued(code: str) -> bool:
        b = base(code)
        return any(k == b or k.startswith(b) for k in known)

    unsatisfiable = []
    for _, _, slot in iter_slots(tpl):
        if slot.get("type") == "choose_one":
            if not any(catalogued(c) for c in slot.get("codes", [])):
                unsatisfiable.append(slot.get("codes"))
    assert not unsatisfiable, f"choose_one groups with no catalogued option: {unsatisfiable}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {t.__name__}: {e!r}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
