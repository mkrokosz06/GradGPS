# GradGPS — CLAUDE.md

AI advisor app for Penn State students. FastAPI backend + React Native (Expo) mobile app.

---

## Running the project

### 1. Start infrastructure (Docker)
```bash
docker-compose up -d   # starts DynamoDB local (port 8000) + MinIO S3 (port 9000)
```

### 2. Seed the database (required after every Docker restart — data is in-memory)
```bash
cd backend
python scripts/setup_tables.py    # create tables/buckets
python scripts/load_catalog.py    # load 31k PSU requirement rows (~2 min)
python scripts/rebuild_gen_ed.py  # load gen ed requirements from scraped bulletin data
python scripts/seed_matthew.py    # seed test user + transcript (also patches ETI catalog)
```
`seed_matthew.py` accepts an optional PDF path: `python scripts/seed_matthew.py path/to/transcript.pdf`

> **Gen ed data:** `rebuild_gen_ed.py` loads the eight knowledge-domain / quantification / cultures
> pools (GA/GN/GH/GS/GHW/GQ/US/IL) from `scripts/gen_ed_courses.json` — authoritative data scraped
> from the PSU bulletin — keeps the fixed Communication (Writing/Speech) choose-one groups from
> `seed_gen_ed.py`, and writes one **Writing Across the Curriculum** rule (see below).
> To refresh the underlying data from the live bulletin (~10 min), run
> `python scripts/scrape_gen_ed_courses.py` first, then `rebuild_gen_ed.py`.
> **Do not run `seed_gen_ed.py` directly** for the domain pools — its hand-authored course lists
> have fabricated titles/attributes and are superseded (it now only supplies the fixed Communication groups).
>
> **Writing Across the Curriculum (WAC):** PSU requires 3 credits of writing-intensive (W/M/X/Y-suffixed)
> coursework. This is a *designation*, not a course list, so it's modelled as a single
> `group_type="writing_intensive"` requirement row (threshold 3), evaluated by
> `audit_engine._eval_writing_intensive()` against the `is_writing` flag the transcript parser sets from
> the course suffix (preserved through storage). The timeline also counts planned major W courses
> (requirement codes ending in W/M/X/Y, e.g. `ETI 300W`) toward it.

### 3. Start the backend
```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### 4. Start the mobile app
```bash
cd mobile
npx expo start
```
Scan the QR code in Expo Go. The app connects to `API_BASE` in `mobile/constants/api.ts`.

---

## Architecture

### Backend (`backend/`)
| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, router registration, CORS, static files |
| `audit_engine.py` | Core degree audit logic — `run_audit()` and `run_gen_ed_audit()` |
| `transcript_parser.py` | Parses PSU unofficial transcript PDFs |
| `deps.py` | Shared FastAPI dependency — `get_user_id` extracts `x-user-id` header |
| `db.py` | DynamoDB + S3 clients (local in dev, real AWS in prod) |

#### Routers
| Router | Prefix | Purpose |
|--------|--------|---------|
| `audit.py` | `/audit` | Degree audit + subplan detection |
| `timeline.py` | `/timeline` | Academic timeline (past + future semesters) |
| `transcript.py` | `/transcript` | PDF upload, parse, store |
| `programs.py` | `/programs` | Major search/select |
| `users.py` | `/users` | User profile |
| `admin.py` | `/admin` | Admin utilities |

#### DynamoDB tables
| Table | PK | SK | Contents |
|-------|----|----|---------|
| `requirements` | `program_name` | `group_course` | All PSU major + gen ed requirements |
| `users` | `user_id` | — | User profile (major, subplan, timestamps) |
| `transcript_courses` | `user_id` | `course_code` | Parsed transcript courses |

#### Gen ed
Gen ed requirements are stored under `program_name = "__GEN_ED__"` in the requirements table. `run_gen_ed_audit()` enforces cross-group exclusivity (a course can only satisfy one gen ed category) with an exception for interdomain/multi-category courses (`multi_category=True`).

---

### Mobile (`mobile/`)
Expo SDK 54, Expo Router v3, NativeWind (Tailwind).

#### Navigation
- `app/_layout.tsx` — root Stack + `AuthProvider`. `RootRedirector` bounces unauthenticated users to `/onboarding`.
- `app/(tabs)/_layout.tsx` — **Tabs layout with tab bar hidden** (`tabBarStyle: { display: "none" }`). Do NOT change this to Stack — it breaks `router.navigate()` between sibling screens. Navigation is via the hamburger menu in `NavHeader`.
- `app/(tabs)/index.tsx` — Timeline screen (main screen)
- `app/(tabs)/upload.tsx` — Transcript upload
- `app/(tabs)/major.tsx` — Major + subplan selection (two-step flow)
- `app/(tabs)/account.tsx` — Account / audit summary
- `app/onboarding/` — Onboarding flow (welcome → signup → major → upload)

#### Key components & context
| File | Purpose |
|------|---------|
| `components/NavHeader.tsx` | Top bar with hamburger side-menu. Routes use `router.navigate()`. |
| `context/AuthContext.tsx` | Auth state. In dev, falls back to hardcoded `USER_ID` from `constants/api.ts` when AsyncStorage is empty. |
| `services/api.ts` | Base axios instance (uses `API_BASE`) |
| `services/*Service.ts` | Typed wrappers for each backend endpoint |
| `constants/api.ts` | `API_BASE` (device IP:8080) and `USER_ID` (hardcoded dev user) |

---

## Key decisions & known quirks

### Audit engine
- `choose_one` groups use `pair_group_id` to link alternatives (e.g. MATH 110 / MATH 140). A pair is satisfied if **any** course in it is done/in-progress (`pair_status`).
- `choose_credits` pools in `_collect_missing()` must be treated as a single slot — never iterate individual pool items into the timeline. Fixed with an early `continue` when `gtype == "choose_credits"`.
- PSU attribute suffixes W (Writing), H (Honors), N (Non-Western) are stripped from course codes for catalog matching. Section letters (A/B/C) are kept.

### Catalog patches (applied by `seed_matthew.py`)
**ETI fixes:**
1. **Junk rows** — credit counts ("3", "4") imported as `course_title` for 14 courses. Deleted on seed.
2. **Missing pairs** — BA 243/BLAW 243, BA 301/FIN 301, BA 303/MKTG 301, BA 304/MGMT 301 are choose-one alternatives not captured by the scraper. Pair IDs 580–583 are assigned on seed.

**PHYS 211 / PHYS 250 physics sequence alternatives (32 programs):**
The scraper captured both the calc-based sequence (PHYS 211) and algebra-based sequence (PHYS 250) as individually `required` in 32+ programs. In reality these are alternatives — MATH 22 track students take PHYS 250, others take PHYS 211. `patch_phys_alternatives()` in `seed_matthew.py` pairs them as `choose_one` with pair IDs 600+.

**MATH 250 / MATH 251 differential equations alternatives:**
MATH 250 (3cr) and MATH 251 (4cr) cover the same content and are interchangeable across all programs. `patch_math_alternatives()` in `seed_matthew.py` (pair IDs 700+) generically scans every `(program, group)` where MATH 250 appears and pairs it with MATH 251, inserting a MATH 251 row where absent. Skips `choose_credits` pools (no pairing needed) and already-paired rows (idempotent).

### Timeline semester projection
- `COURSES_PER_SEM = 5` courses per future semester
- Summer is skipped (`_next_term` jumps SP→FA, FA→next SP)
- Satisfied `choose_one` pairs are excluded via `pair_status` check
- Satisfied `choose_credits` pools are excluded entirely (skip the whole group)

### Auth (dev vs prod)
- **Real auth**: Google/Apple OIDC ID tokens, verified in `backend/auth.py` (JWKS signature, aud, iss, exp). Canonical `user_id` = provider-scoped sub (`google:<sub>` / `apple:<sub>`). Client IDs in `backend/.env` (`GOOGLE_CLIENT_IDS`, `APPLE_CLIENT_IDS`). Mobile: `expo-auth-session` in `signup.tsx` → `signInWithIdToken()` in `AuthContext` → token in SecureStore (AsyncStorage on web) → axios interceptor sends `Authorization: Bearer`.
- **Dev bypass**: `AUTH_DEV_BYPASS=1` in `backend/.env` accepts the legacy spoofable `x-user-id` header (and leaves `/admin/*` open + keeps legacy `POST /users/create` alive). This is how Expo Go on the phone works (test user `matthew-test-001`). NEVER set in prod.
- **Google OAuth cannot run in Expo Go** (auth proxy removed in SDK 50) — test the Google flow in Expo web (`npx expo start --web`, client ID allows localhost:8081/8082) or a dev build. Apple Sign In requires a dev build + Apple Developer Program (not yet done).
- **Known gap**: ID tokens expire after ~1 h → backend returns 401 and the user must sign in again. No refresh/session mechanism yet.
- **Admin**: `/admin/*` gated by `require_admin` — open under dev bypass, else `ADMIN_USER_IDS` allowlist (comma-separated provider-scoped ids).

### Stale uvicorn processes (Windows)
When running in WSL bash, multiple Python processes can bind to port 8080. If API changes aren't being picked up:
```bash
wmic process where "name like '%python%'" get ProcessId,Name
# kill all except the current uvicorn, then restart
```

---

## Test user
| Field | Value |
|-------|-------|
| user_id | `matthew-test-001` |
| major | Enterprise Technology Integration, B.S. (Information Sciences and Technology) |
| subplan | none |
| transcript | Real PSU unofficial transcript, 26 courses, FA 2026 in progress |

---

## Adding a new requirement pair to the catalog
If two courses should be choose-one alternatives but aren't paired in the catalog, add them to the `PAIRS` list in `seed_matthew.py`'s `patch_eti_catalog()` with a new pair ID (currently up to 583).
