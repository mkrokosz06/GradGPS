# Backend tests

Run with `pytest` from `backend/` (each file also runs standalone via `python tests/<file>.py` where noted).

## Existing

| File | Covers |
|------|--------|
| `test_audit_engine.py` | Degree audit logic |
| `test_official_detector.py` | Official-transcript detection heuristic (set `OFFICIAL_SAMPLE_PDF` for the real-sample e2e test) |
| `test_timeline_packing.py` | Pool expansion + credit-band packing (timeline Layer 1) |
| `test_plan_templates.py` | SAP template loading/validation |
| `test_sap_schedule.py` | SAP match stage (`match_template()`) |
| `test_scrape_sap.py` | SAP scraper parsing |
| `test_programs_scope.py` | Program search scoping |

## Layout

- `tests/` — unit tests: pure logic, no running services required.
- `tests/integration/` — API-level tests that exercise FastAPI routes end-to-end
  (TestClient + DynamoDB Local/MinIO from `docker-compose up`). See its README.

## Planned / ideas

See `integration/README.md` and the mobile side at `mobile/__tests__/README.md`.
High-value unit gaps:

- **Transcript parser golden files** — sample PDFs in `tests/fixtures/`, assert exact
  course lists: W/H/N suffix stripping, 1.5-credit courses, transfer credit,
  in-progress terms, `official_parse_looks_bad()` safety net.
- **Audit engine edges** — `choose_credits` exactly at / just below threshold,
  `choose_one` pair satisfied by in-progress course, gen-ed cross-group exclusivity
  vs `multi_category` exception, writing-intensive (WAC) evaluation.
- **SAP template lint** — sweep all ~180 JSON files in `sap_templates/`: schema shape,
  8 semesters, credits sum to a sane total, referenced requirement groups exist in
  the catalog.
- **Auth** — expired token → 401, wrong audience/issuer rejected, `AUTH_DEV_BYPASS`
  on/off behavior, `/admin/*` allowlist enforcement.
- **Catalog patch invariants** — after `seed_matthew.py`: no junk title rows, pair IDs
  580+/600+/700+ present and consistent, patches idempotent on re-run.
