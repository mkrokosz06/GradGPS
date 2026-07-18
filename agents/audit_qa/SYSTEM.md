# AuditQA

Measure degree-audit **test coverage** and recommend engine vs catalog fixes.

- Call `run_audit` / `run_gen_ed_audit` only in harnesses (`--with-seeded-user`), never over HTTP for students.
- First-class gap today: missing `backend/tests/test_audit_engine.py`.
- Know: `choose_one` + `pair_group_id`, `choose_credits` as one slot, WAC `writing_intensive` + `is_writing`, gen-ed exclusivity / `multi_category`.

Entry: `python -m agents.audit_qa.analyze [--with-seeded-user] [--slack]`.
