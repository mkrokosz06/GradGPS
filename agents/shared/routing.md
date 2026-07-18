# Routing

Implemented in `agents/shared/routing.py`.

| Intent keywords | Intent |
|-----------------|--------|
| test, pytest, suite | `test` |
| analyze, analytics, coverage, metrics | `analyze` |
| recommend, backlog, prioritize | `recommend` |
| implement, fix, apply recommendation | `implement_fix` |

| Area keywords | Area |
|---------------|------|
| audit, choose_one, gen ed, wac | `audit` |
| timeline, packing, sap, semester | `timeline` |
| transcript, official, pdf, 409 | `transcript` |
| catalog, seed_matthew, scrape | `catalog` |
| mobile, expo, nativewind, tabs | `mobile` |
| auth, oidc, AUTH_DEV_BYPASS | `auth` (human-gated for product edits) |

Override with `--intent` / `--area` on the orchestrator.
