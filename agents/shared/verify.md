# Verify

## Catalog Excel

Regenerate (do not hand-author):

```bash
cd backend
python scripts/scrape_psu.py                                    # full UP catalog (~many minutes)
python scripts/scrape_psu.py --program "Enterprise Technology"  # ETI only (fast)
python scripts/load_catalog.py
python scripts/rebuild_gen_ed.py   # if tables were wiped
python scripts/seed_matthew.py
```

## Seed (after every Docker restart)

```bash
cd backend
python scripts/setup_tables.py
python scripts/load_catalog.py      # needs PSU_Major_Requirements.xlsx from scrape above
python scripts/rebuild_gen_ed.py
python scripts/seed_matthew.py
```

Test user: `matthew-test-001` (ETI, real unofficial transcript).

## Pytest map

| Area | Command |
|------|---------|
| All | `cd backend && python -m pytest tests -v` |
| Timeline/SAP | `python -m pytest tests/test_timeline_packing.py tests/test_sap_schedule.py tests/test_plan_templates.py tests/test_scrape_sap.py -v` |
| Transcript | `python -m pytest tests/test_official_detector.py -v` |
| Programs scope | `python -m pytest tests/test_programs_scope.py -v` |
| Audit engine | `python -m pytest tests/test_audit_engine.py -v` |

Or: `python -m agents.test_runner.run_tests --suite <area>`.

Install test deps once: `python -m pip install -r backend/requirements-dev.txt`.
