# AuditQA

Measure degree-audit **test coverage** and recommend engine vs catalog fixes.

- Call `run_audit` / `run_gen_ed_audit` only in harnesses (`--with-seeded-user`), never over HTTP for students.
- `backend/tests/test_audit_engine.py` now exists (core behaviors on synthetic rows); next gap is golden fixtures from `matthew-test-001` / known ETI pairs when DynamoDB is seeded.
- Know: `choose_one` + `pair_group_id`, `choose_credits` as one slot, WAC `writing_intensive` + `is_writing`, gen-ed exclusivity / `multi_category`.

Entry: `python -m agents.audit_qa.analyze [--with-seeded-user] [--slack]`.
