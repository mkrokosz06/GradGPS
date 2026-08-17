# Cloud-Deferred Features

Things we **can't do (or shouldn't bother doing) on the local dev setup**, but that become possible
or automatic once GradGPS is deployed to AWS. This is the running wishlist — add to it whenever we
say "that's a cloud thing" during development.

Local today = Docker DynamoDB (in-memory) + MinIO, backend on a laptop, no scheduler, no always-on
anything. Cloud = real DynamoDB + S3, an always-on backend, and EventBridge/Lambda for scheduled jobs.

> **Status (updated 2026-08-17).** GradGPS is **live on AWS** (App Runner backend, real DynamoDB + S3,
> CI/CD, monthly cron, cost guards). Most of this list has shipped — items are tagged below.
> Legend: ✅ done · 🟡 partial · ⬜ not started.
>
> **Still open:** semesterly catalog/gen-ed/SAP rescrape cron (§1), Apple Sign In + dev build (§3),
> push notifications (§4), CloudWatch alarms/metrics (§5).

---

## 1. Scheduled data refresh (the big one)

There is no scheduler locally, and the laptop isn't always on — so all scraped data goes stale
until someone manually re-runs scripts. In the cloud these become cron jobs.

### ✅ Monthly refresh — DONE (2026-07-29)
- **Script:** `backend/scripts/monthly_refresh.py`.
- **What it runs:** `scrape_crosslistings.py` (PSU bulletin cross-listings) + `build_rmp_index.py`
  (RateMyProfessors course→professor index).
- **Smart:** it auto-detects changes; cross-listings now write to the `__CROSSLISTINGS__` requirements
  item (no more `audit_engine.py` source-patching) and bounce App Runner to reload.
- **Shipped as:** EventBridge Scheduler `gradgps-monthly-refresh`, cron `0 2 1 * ? *` (1st of month,
  2 AM ET) → ECS Fargate task on cluster `gradgps` (same backend image). Logs in
  `/ecs/gradgps-monthly-refresh`. Validated with a one-off `run_task`.

### ⬜ Other rescrapes worth folding into a semesterly schedule (NOT scheduled yet)
| Data | Script | Current staleness risk |
|------|--------|------------------------|
| Full requirements catalog (31k rows) | `scripts/scrape_psu.py` + `scripts/load_catalog.py` | PSU updates the bulletin yearly; catalog changes silently drift |
| Gen ed pools (GA/GN/GH/GS/GHW/GQ/US/IL) | `scripts/scrape_gen_ed_courses.py` + `rebuild_gen_ed.py` | Course attributes change each catalog year (~10 min scrape) |
| SAP templates (Suggested Academic Plans) | `scripts/scrape_sap.py` | Bulletin plans revised yearly; `validate_template()` already guarantees a bad scrape never goes live, so this is safe to automate |

A sensible cloud cadence: cross-listings + RMP monthly (done); catalog + gen ed + SAP once per
semester (or also monthly — the validators make it low-risk). **This semesterly job is the one
remaining piece of §1.**

## 2. ✅ Persistent data — no more reseed ritual (DONE)

Local DynamoDB is **in-memory**: every Docker restart wipes everything and requires the 5-script
reseed (including the 20–40 min RMP rebuild). Real DynamoDB + S3 made that disappear:

- ✅ Data survives restarts/deploys — seed scripts became one-time migrations. Prod seeded via
  `scripts/apply_catalog_patches.py` (catalog 31,734 rows, gen ed 3,918 rows, RMP 21,311 pairs).
- ✅ The `rmp_professor_courses` table can never be "accidentally empty" in prod the way it is after a
  local Docker restart.
- ✅ Real S3 gives durable transcript storage — bucket `degreecheck-transcripts` (MinIO is dev-only).
- ✅ **PITR enabled** on users / transcript_courses / requirements / rmp_professor_courses
  (sessions skipped — ephemeral). CloudTrail `gradgps-management` live.

## 3. 🟡 Real auth, always on (mostly DONE)

- ✅ Flipped **off** `AUTH_DEV_BYPASS` in prod — no more spoofable `x-user-id`; Google/Apple OIDC only.
  Verified: spoofed `x-user-id` → 401.
- ✅ `/admin/*` gated by the `ADMIN_USER_IDS` allowlist instead of being wide open.
- ✅ **Token refresh / sessions — SHIPPED.** `POST /auth/session` exchanges the OIDC ID token for an
  opaque `sess_*` token (sessions table, DynamoDB TTL, 30-day sliding expiry); mobile stores it; the
  ~1 h logout is fixed. Verified live in prod.
- ⬜ **Apple Sign In** still pending — needs a dev build + Apple Developer Program (TestFlight).
  Real Google auth on device also needs a dev build (Expo Go can't do the OAuth proxy).

## 4. 🟡 Always-on backend unlocks

Things that make no sense against a laptop backend but do once the API is always up:

- ✅ **Real device access from anywhere** — `API_BASE` reads `EXPO_PUBLIC_API_BASE` (prod bundles →
  App Runner URL; LAN fallback keeps Expo Go on the local backend). Stable HTTPS domain live
  (`gradgps.com`). TestFlight/Play beta still gated on a dev build (§3).
- ⬜ **Push notifications** — e.g. "registration opens next week, here's your suggested schedule",
  "a seat opened in X". Not built. Needs both an always-on backend (have) and (see §1) fresh data.
- ✅ **Multi-user for real** — friends/testers can use it without being on the same network.

## 5. 🟡 Operations (only meaningful in cloud)

- 🟡 Logs/metrics/alarms (CloudWatch): App Runner + ECS logs flow; **alarms not yet configured**
  (scrape-job / cron failure, 4xx/5xx rates, transcript parse-failure rate). Budget alert ($10) exists.
- 🟡 `OFFICIAL_DETECT` shadow-mode telemetry at scale — detection + official parsing run and log in
  shadow mode; accumulating false-positive data before enabling the 409 consent dialog for everyone.
- ✅ CI/CD deploy pipeline instead of hand-run uvicorn — `deploy-backend.yml` auto-deploys on push to
  `main` (ECR via OIDC → App Runner `:latest`, ~2 min). Cost guards applied (App Runner max-2, DDB caps,
  log retention, ECR keep-5).

---

## Not cloud-blocked (don't park these here)

- Bug fixes and audit-engine/timeline work — all local.
- SAP template authoring for more majors — scraper runs fine locally.
- Expo web testing of Google OAuth — works today.
