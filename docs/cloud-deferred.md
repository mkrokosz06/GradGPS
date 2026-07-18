# Cloud-Deferred Features

Things we **can't do (or shouldn't bother doing) on the local dev setup**, but that become possible
or automatic once GradGPS is deployed to AWS. This is the running wishlist — add to it whenever we
say "that's a cloud thing" during development.

Local today = Docker DynamoDB (in-memory) + MinIO, backend on a laptop, no scheduler, no always-on
anything. Cloud = real DynamoDB + S3, an always-on backend, and EventBridge/Lambda for scheduled jobs.

---

## 1. Scheduled data refresh (the big one)

There is no scheduler locally, and the laptop isn't always on — so all scraped data goes stale
until someone manually re-runs scripts. In the cloud these become cron jobs.

### Monthly refresh — already written, just needs a trigger
- **Script:** `backend/scripts/monthly_refresh.py` (exists and works today, run manually).
- **What it runs:** `scrape_crosslistings.py` (PSU bulletin cross-listings) + `build_rmp_index.py`
  (RateMyProfessors course→professor index).
- **Smart:** it auto-detects changes and only patches `audit_engine.py` if cross-listings actually changed.
- **Cloud setup:** EventBridge Scheduler, cron `0 2 1 * ? *` (1st of each month, 2 AM), triggering a
  Lambda or ECS task. RMP indexing takes 20–40 min, so ECS (or a Lambda with a generous timeout) is safer.

### Other rescrapes worth folding into the same (or a semesterly) schedule
| Data | Script | Current staleness risk |
|------|--------|------------------------|
| Full requirements catalog (31k rows) | `scripts/scrape_psu.py` + `scripts/load_catalog.py` | PSU updates the bulletin yearly; catalog changes silently drift |
| Gen ed pools (GA/GN/GH/GS/GHW/GQ/US/IL) | `scripts/scrape_gen_ed_courses.py` + `rebuild_gen_ed.py` | Course attributes change each catalog year (~10 min scrape) |
| SAP templates (Suggested Academic Plans) | `scripts/scrape_sap.py` | Bulletin plans revised yearly; `validate_template()` already guarantees a bad scrape never goes live, so this is safe to automate |

A sensible cloud cadence: cross-listings + RMP monthly; catalog + gen ed + SAP once per semester
(or also monthly — the validators make it low-risk).

## 2. Persistent data — no more reseed ritual

Local DynamoDB is **in-memory**: every Docker restart wipes everything and requires the 5-script
reseed (including the 20–40 min RMP rebuild). Real DynamoDB + S3 make that disappear:

- Data survives restarts/deploys — seed scripts become one-time migrations, not a ritual.
- The `rmp_professor_courses` table can never be "accidentally empty" in prod the way it is after a
  local Docker restart.
- Real S3 gives durable transcript storage (MinIO is dev-only).
- Bonus once on real AWS: DynamoDB point-in-time recovery / backups.

## 3. Real auth, always on

- Flip **off** `AUTH_DEV_BYPASS` — no more spoofable `x-user-id`; Google/Apple OIDC only.
- `/admin/*` gated by the `ADMIN_USER_IDS` allowlist instead of being wide open.
- Apple Sign In needs a dev build + Apple Developer Program — pairs naturally with a real deployment
  (TestFlight), can't be tested in Expo Go anyway.
- **Token refresh / sessions:** ID tokens expire after ~1 h and users get logged out. A proper
  backend session (refresh token or server-issued session token) is worth building alongside the
  cloud deploy, since it needs a stable always-on backend to matter.

## 4. Always-on backend unlocks

Things that make no sense against a laptop backend but do once the API is always up:

- **Real device access from anywhere** — no more `API_BASE` pointing at a LAN IP; a stable HTTPS
  domain means the mobile app works off-campus/off-wifi, and TestFlight/Play beta testing becomes possible.
- **Push notifications** — e.g. "registration opens next week, here's your suggested schedule",
  "a seat opened in X". Needs both an always-on backend and (see §1) fresh data.
- **Multi-user for real** — friends/testers can use it without being on the same network.

## 5. Operations (only meaningful in cloud)

- Logs/metrics/alarms (CloudWatch): scrape-job failure alerts, 4xx/5xx rates, parse-failure rate on
  transcript uploads.
- `OFFICIAL_DETECT` shadow-mode telemetry at scale — real users' uploads validate the official-transcript
  detector's false-positive rate before the 409 consent dialog is enabled for everyone.
- CI/CD deploy pipeline instead of hand-run uvicorn.

---

## Not cloud-blocked (don't park these here)

- Bug fixes and audit-engine/timeline work — all local.
- SAP template authoring for more majors — scraper runs fine locally.
- Expo web testing of Google OAuth — works today.
