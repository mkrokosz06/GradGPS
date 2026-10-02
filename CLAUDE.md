# GradGPS — CLAUDE.md

AI advisor app for Penn State students. FastAPI backend + React Native (Expo) mobile app.

**Status:** publicly released on the App Store since Sept 28 2026 (1.1.0, app ID `6803643612`).
1.1.1 (build 11) released Oct 2 2026. OTA updates (`eas update`) target runtime 1.1.1 only — 1.1.0 installs get no new JS.
Prod has real users — a push to `main` deploys immediately.

## Answering style

Be brief. Be concise. Avoid being too verbose or giving unnecessary information.
Lead with the answer, give only the facts that back it, stop. Do the deep
investigation when it's needed — just report the conclusion, not the walkthrough.

## Keeping docs current

When a task is **finished** — a feature shipped, a bug fixed, a decision made — update the docs it
touches (this file, `mobile/CLAUDE.md`, the relevant `docs/*.md`) as part of finishing it. Once per
completed task, not after every message or intermediate step.

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
Scan the QR code in Expo Go. The app connects to `API_BASE` in `mobile/constants/api.ts`
(LAN fallback in dev; production bundles read `EXPO_PUBLIC_API_BASE` from `mobile/.env.production`).

---

## Production (AWS)

Live backend: **https://kjn2ysmnjr.us-east-1.awsapprunner.com** — App Runner service
`gradgps-backend` (us-east-1, account 209855137345), real DynamoDB + S3 (persistent — no
reseed ritual). The container runs under IAM role `GradGPSAppRunnerInstance` (no keys) with
`AUTH_DEV_BYPASS` **off**: only real Google OIDC tokens work; `x-user-id` → 401.

**Deploying backend changes:** push to `main`. `.github/workflows/deploy-backend.yml` builds
`backend/Dockerfile` and pushes to ECR via OIDC role `GradGPSGitHubActions` (no stored AWS
keys); App Runner auto-deploys the `:latest` tag (~2 min). Triggers only on `backend/**` paths.
The Dockerfile pins `python:3.12-slim` — the pinned pandas 2.2.2 has no Python 3.13 wheels.

**Running seed/maintenance scripts against prod** — auth is IAM Identity Center SSO (no access
keys exist). First `aws sso login --profile gradgps` (valid ~8 h), then run with the profile;
blank vars beat `.env` because `load_dotenv` doesn't override existing env:
```bash
AWS_PROFILE=gradgps DYNAMODB_ENDPOINT= S3_ENDPOINT= AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= python scripts/<script>.py
```
For prod catalog seeding use `scripts/apply_catalog_patches.py` (patches without the test user),
not `seed_matthew.py`.

**Monthly refresh cron:** EventBridge Scheduler `gradgps-monthly-refresh` (1st of month, 2 AM ET)
runs `scripts/monthly_refresh.py` as an ECS Fargate task (cluster `gradgps`, same backend image,
logs in `/ecs/gradgps-monthly-refresh`). It rescrapes PSU cross-listings into the
`__CROSSLISTINGS__` DynamoDB item and bounces App Runner via
`APP_RUNNER_SERVICE_ARN` so the running service reloads the pairs.

---

## Architecture

### Backend (`backend/`)
| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, router registration, CORS, static files |
| `audit_engine.py` | Core degree audit logic — `run_audit()` and `run_gen_ed_audit()` |
| `transcript_parser.py` | Parses PSU transcript PDFs (unofficial + official). `parse_and_detect()` is the entry point |
| `official_detector.py` | Scored heuristic that flags official transcripts (see below) |
| `plan_templates.py` | Loads/validates Suggested Academic Plan (SAP) JSON templates from `sap_templates/` (see below) |
| `sap_schedule.py` | SAP match stage — `match_template()` decides which template slots the student has already satisfied (pure, DB-free) |
| `substitutions.py` | Course-substitution store — per-user course equivalences (`requirement_code -> substitute_course`) |
| `entrance_parse.py` | Parses a bulletin "how to get in" tab into an Entrance to Major spec (see below) |
| `entrance_to_major.py` | Entrance to Major at runtime — gate progress, timeline slot attachment |
| `deps.py` | Shared FastAPI dependency — `get_user_id` extracts `x-user-id` header |
| `db.py` | DynamoDB + S3 clients (local in dev, real AWS in prod) |

SAP templates live as JSON under `backend/sap_templates/` (~180 University Park majors, e.g. `accounting-bs-business.json`, `marketing-bs-business.json`).

#### Routers
| Router | Prefix | Purpose |
|--------|--------|---------|
| `audit.py` | `/audit` | Degree audit + subplan detection |
| `timeline.py` | `/timeline` | Academic timeline (past + future semesters) |
| `transcript.py` | `/transcript` | PDF upload, parse, store + manual class editing (`POST`/`PATCH`/`DELETE /transcript/course`) |
| `programs.py` | `/programs` | Major search/select |
| `courses.py` | `/courses` | Course detail + class-selector search (gen-ed domains, pools, business breadth) |
| `substitutions.py` | `/substitutions` | Course substitutions — "the class I took counts for that requirement" (see below) |
| `users.py` | `/users` | User profile + `DELETE /users/me` account deletion (PDF, courses, profile, sessions) |
| `admin.py` | `/admin` | Admin utilities |
| `support.py` | `/support` | Support/contact form (mobile app + gradgps.com). Emails `SUPPORT_EMAIL` via SES with the sender as Reply-To; unset `SUPPORT_EMAIL` (local dev) = log only. No auth required (website form is anonymous); in-memory rate limit + honeypot field. SES setup: identity `mkrokosz06@gmail.com` verified, `ses:SendEmail` on the App Runner role (`GradGPSSupportSES` inline policy). |

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
Expo SDK 54, Expo Router v6, NativeWind (Tailwind).

#### Navigation
- `app/_layout.tsx` — root Stack + `AuthProvider`. `RootRedirector` bounces unauthenticated users to `/onboarding`.
- `app/(tabs)/_layout.tsx` — **Tabs layout with tab bar hidden** (`tabBarStyle: { display: "none" }`). Do NOT change this to Stack — it breaks `router.navigate()` between sibling screens. Navigation is via the hamburger menu in `NavHeader`.
- `app/(tabs)/index.tsx` — Home screen (main screen: greeting + current/next-semester registration dashboard)
- `app/(tabs)/timeline.tsx` — Full academic timeline screen
- `app/(tabs)/upload.tsx` — Transcript upload
- `app/(tabs)/major.tsx` — Major + subplan selection (two-step flow)
- `app/(tabs)/account.tsx` — Account / audit summary
- `app/(tabs)/support.tsx` — Contact-support form (posts to `/support/contact`)
- `app/onboarding/` — Onboarding flow (welcome → signup → major → upload)

#### Key components & context
| File | Purpose |
|------|---------|
| `components/NavHeader.tsx` | Top bar with hamburger side-menu. Routes use `router.navigate()`. |
| `components/SchreyerHonorsCard.tsx` | Account-page Schreyer Scholar declaration (`services/honorsService.ts`) |
| `context/AuthContext.tsx` | Auth state. Real path exchanges an OIDC token for a session (`signInWithIdToken`); a legacy dev `signIn(uid, name, email)` seeds the `x-user-id` model against `AUTH_DEV_BYPASS` backends. |
| `services/api.ts` | Base axios instance (uses `API_BASE`) |
| `services/*Service.ts` | Typed wrappers for each backend endpoint |
| `constants/api.ts` | `API_BASE` (device IP:8080, or `EXPO_PUBLIC_API_BASE` in prod) and the Google OAuth client IDs |

---

## Key decisions & known quirks

### Audit engine
- `choose_one` groups use `pair_group_id` to link alternatives (e.g. MATH 110 / MATH 140). A pair is satisfied if **any** course in it is done/in-progress (`pair_status`).
- `choose_credits` pools in `_collect_missing()` must be treated as a single slot — never iterate individual pool items into the timeline. Fixed with an early `continue` when `gtype == "choose_credits"`.
- PSU attribute suffixes W (Writing), H (Honors), N (Non-Western) are stripped from course codes for catalog matching. Section letters (A/B/C) are kept.

### Catalog patches (applied by `seed_matthew.py`)
**ETI fixes:**
1. **Junk rows** — credit counts ("3", "4") imported as `course_title` for 14 courses. Deleted on seed.

> **Two ETI patches were removed (Sept 2026) — do not re-add them.**
>
> **Pairs 580–583** (BA 243/BLAW 243, BA 301/FIN 301, BA 303/MKTG 301, BA 304/MGMT 301) took the
> **optional Business Competency application focus** and applied it as a mandatory major requirement,
> so every ETI student was told they owed four business courses. The bulletin's own footnote says
> otherwise: *"Note 3: One of these courses is required to be taken to satisfy major requirements.
> The student needs to take the remaining courses on this list to complete the application focus."*
> The major requirement is a single `Select 3-4 credits` pool over those nine courses — **one course**.
>
> **`patch_eti_select_groups()`** was a per-program workaround for the pool-merge bug (below); its
> docstring even said *"bulletin has 3 pools, scraper made 1"*. `pool_seq` fixes that properly, and
> the patch's guard fired on any unpaired `choose_credits` row, so keeping it would have re-merged
> the corrected pools on every seed. `scripts/apply_catalog_patches.py` (the **prod** entry point)
> imported it — check that file whenever a patch function is deleted, or the next prod catalog run
> dies on an `ImportError` before applying anything.

**PHYS 211 / PHYS 250 physics sequence alternatives (32 programs):**
The scraper captured both the calc-based sequence (PHYS 211) and algebra-based sequence (PHYS 250) as individually `required` in 32+ programs. In reality these are alternatives — MATH 22 track students take PHYS 250, others take PHYS 211. `patch_phys_alternatives()` in `seed_matthew.py` pairs them as `choose_one` with pair IDs 600+.

**Known course alternatives across the catalog (`patch_known_alternatives()`):**
A single generic pass in `seed_matthew.py` (pair IDs 800+) fixes choose-one pairing defects for a table of known interchangeable course groups (`KNOWN_ALTERNATIVE_GROUPS`) — MATH 250/251 (diff eq), MATH 110/140, the CAS 100 sections, STAT/SCM/DS options, chemistry, CMPSC, and business alternatives among them. Per `(program, group)` it pairs 2+ unpaired courses into a shared `pair_group_id`, skips `choose_credits` pools and `exclude`d combos (where both courses are genuinely required), and skips already-paired rows (idempotent).

> **Inserting an absent alternative is gated on the bulletin (Sept 2026).** `insert_missing` used to add
> "the other course" wherever one half of a pair appeared, and **280 of the 317** alternatives it added
> to UP majors appear nowhere on that major's bulletin page — CHEM 130 in every engineering major,
> MATH 110 in Physics, PHYS 250 in the calculus-based majors, ACCTG 201 *alone* for ACCTG 211 — so the
> audit told students they were done when they weren't. (MATH 110/140 *is* a real choice in many
> majors, but there the bulletin lists both and the scraper pairs them without any insert.)
> `scripts/verify_alternative_inserts.py` now checks every insert against independent sources — the
> live page's requirements / plan / entrance tabs, the raw HTML's course links (a second witness sharing
> no parsing), the bundled SAP templates and ETM spec, and the rest of the scrape — and writes
> `program_data/alternative_inserts.json`. The patch inserts **only** `keep` / `branch` verdicts;
> a `branch` ("ACCTG 211 or (ACCTG 201 and ACCTG 202)", Smeal ×8) goes in as a compound branch.
> A drop needs every source silent **and** the page to name the partner course (proof it was read).
> `scripts/remove_unverified_alternatives.py` removes the drops from a loaded catalog: dry run by
> default, re-validates each row live, backs up before-images to `backend/backups/`, `--restore` undoes.
> Inserted rows are recognisable by key: scraped rows are `group#code#<seq>`, inserts `group#code`.
> A partner is restored to plain `required` — **not** from the xlsx, whose pair ids are numbered per
> scrape run and collide with the loaded catalog's (restoring from it merged CED's STAT 200 into a
> CAS 100 pair). Tests: `tests/test_alternative_inserts.py` (23).

### Timeline semester projection

The timeline has **two paths**, both in `routers/timeline.py`:

**SAP-template path (preferred, for majors with a published plan).** If `load_template(major, subplan)` finds a Suggested Academic Plan template, the timeline follows it — see the SAP section below.

**Layer 1 credit-band packer (fallback, every un-templated major).** `_build_layer1_future()` builds future semesters from the audit alone:
- Packs each semester to a realistic credit **band** (`_TARGET_CREDITS = 15`, never past `_MAX_CREDITS = 18`) instead of a fixed course count — this replaced the old `COURSES_PER_SEM = 5` scheme (`be9495c`).
- `_expand_pool()` splits large `choose_credits` / free-elective pools into ~3-credit placeholder slots so the packer can spread them across the whole plan instead of dumping one big blob into a single semester. Each slot keeps the pool's identity/dropdown for the mobile UI.
- At most `_GEN_ED_PER_SEM = 2` gen-ed placeholders per semester.
- Summer is skipped (`_next_term` jumps SP→FA, FA→next SP).
- Satisfied `choose_one` pairs excluded via `pair_status`; satisfied `choose_credits` pools excluded entirely.

### Prerequisite / corequisite ordering

Both timeline paths now respect PSU's published requisites. Before, the SAP **rebalance** (every
student with a transcript) sliced the flattened template into even chunks straight across its
semester boundaries: ARCH 203 landed a term before its corequisites AE 421 / ARCH 231, ME 340 before
ME 320, and a student missing ACCTG 211 had FIN 301 pulled into the very term they make it up. A
check over 320 majors × 3 synthetic students found 98 violations for an on-track student and 211 for
one with gaps; after the fix, **0** real ones remain. The only hits the checker still reports are
"or concurrent" wording that the runtime parser reads more accurately than the checker does.

- **Data**: `scripts/bulletin_prereqs.json` (3,751 courses) — written by `scrape_bulletin_courses.py`
  alongside `bulletin_courses.json`, parsed by `course_prereqs.parse()`. `pre` clauses must be done in
  an earlier term, `co` clauses by the same term. The parse only ever *weakens*: a clause with an
  escape hatch (placement, permission, "or equivalent", standing) is dropped, and `A or (B and C)`
  flattens to "any of A, B, C". Missing file = no constraints = old behaviour.
- **`_pack_ordered()`** replaces `_slice_even()` in the SAP rebalance and the Layer 1 packer (and *is*
  `_slice_even` when no requisites apply). A critical-path bound starts a chain early enough to
  finish on time (a course with N courses still to follow must be done N terms before the end), and
  a fixpoint pass settles mutual corequisites (KINES 366/464/468 each name the others). Overloaded
  terms are relieved by moving placeholders first, then a course earlier, then a course with slack later.
- **`_enforce_prereq_order()`** is the last word on both paths, after `_hold_for_entrance`, and
  before pins (a pin is the student's call). It moves a course later and swaps a placeholder back.
  Moved courses carry `moved_for_prerequisite`.
- **PSU's plan overrides the bulletin**: a pair the template puts in the same semester (EBF 200 beside
  ECON 102) may share one; a pair the template orders the other way is waived. So a no-transcript
  student sees the official plan **unchanged — verified identical for all 307 templates**.
- Cost: 11 of 934 synthetic plans gain a term, each a genuine chain the old plan only fitted by
  breaking it (SPLED 415 → 395W → 404 → 409A → 495D; ARCH 491 → 492 → 499). Plans with a term over
  18 credits dropped from 411 to 180.

Tests: `backend/tests/test_prereq_order.py` (17, pytest or plain `python`).

**Moving a course to another semester (Sept 30 2026).** Pins used to lock a course only to the term
it was already in. Each upcoming slot now carries `movable_terms` (`_mark_movable_terms()`, after
`_apply_pins`): the Fall/Spring terms, plus one past the plan's end, where it can sit with its
prerequisites earlier, nothing planned later left without it (a choose-one slot only counts if *every*
alternative would be), and a major-only course not before `major_courses_from`. Placeholders may go
anywhere; an internship keeps its summer. The class selector shows these as semester chips, and a chip
sends `pinned_term`, which `_apply_pins` already honours. An older server sends no field, so the app
shows the one current term, the old "Lock to" behaviour. Tests: `tests/test_movable_terms.py` (4).

### Suggested Academic Plans (SAP hybrid)
For University Park majors with a published PSU bulletin plan, the timeline reflows the student's real state against the official, prerequisite-sequenced, credit-balanced plan instead of packing from scratch. Design doc: `docs/timeline-sap-hybrid.md`.

**Pipeline** (all in `routers/timeline.py` around the audit call):
1. `load_template(major, subplan)` (`plan_templates.py`) returns the SAP JSON, preferring an exact subplan match but falling back to the subplan-less base plan. `None` → fall back to the Layer 1 packer, so **only templated majors change behavior**.
2. `build_taken_set()` + `build_gen_ed_satisfied()` (`sap_schedule.py`) derive a taken-set (with course equivalences, e.g. IST→ETI) and per-gen-ed-category satisfaction from live audit/transcript data. **The audit engine stays the source of truth** — SAP only supplies order, completeness, and credit balance.
3. `match_template()` walks the template in order and marks each slot satisfied or not. `consumed` prevents one taken course from satisfying two slots. World-language pools and free electives are satisfied from **leftover** courses — transcript courses neither a template slot nor an audit consumed (`build_used_codes()` over the major + gen-ed audit results). Language slots take one leftover course each from the student's majority language dept (`_WORLD_LANGUAGE_DEPTS`, PSU-specific and deliberately conservative); elective slots draw on the surplus credit pool. Other un-anchored pools (business breadth) are still always scheduled.
4. `_reflow_template()` drops satisfied slots (transcript history) and pulls later semesters forward to fill the gap. A no-transcript student reproduces the official plan exactly; a partially-complete student sees remaining semesters pulled earlier. Light leftover fragments (< `_MERGE_MIN = 10` cr) merge forward; a required internship is lifted into its own summer term between junior and senior year.

**Phantom generic gen-ed slots.** A bulletin plan lists most gen-ed credits as *category-less*
"General Education" cells (ETI's has 15 of them = 45 cr). `_assign_generic_gen_ed()` retires one per
completed gen-ed course, but a student who covered all eight domains with fewer courses (interdomain
courses count in two) was left with slots the class selector could not fill — the picker opened with
no domain chips and no results. `build_gen_ed_open()` (`sap_schedule.py`) reports whether any
**searchable** domain pool (the `choose_credits` groups) is still unmet; when none is, the leftover
generic slots are retired. The domain thresholds themselves sum to PSU's 45 gen-ed credits, so
"every domain satisfied" already means the credits are there. Fixed Communication groups and the WAC
rule are deliberately excluded from that test — they are not domains a picker can offer courses for.

**Bounded pools are pickable, not just readable.** A requirement pool with a small enumerated course
list (≤15 options — the mobile dropdown) now carries a class-selector identity from `_collect_missing()`:
`slot_key = pool:<GROUP_NAME>`, `slot_kind = "pool"`, `options = pool_courses`. `_expand_pool()` gives
each slice its own `#i` key so a course picked for one slice doesn't appear on all of them, and
`_apply_pool_choice()` swaps the placeholder for the chosen course (display/scheduling only — the audit
still decides whether the pool is satisfied). This is what makes a minor's "choose 2 of these 5"
actionable; the timeline's dropdown rows and the home screen's pool row open the same picker.

**Template schema & authoring.** Slot types: `course`, `choose_one`, `gen_ed`, `pool`, `elective` (`VALID_SLOT_TYPES` in `plan_templates.py`). `validate_template()` does structural + **grand-total** credit checks only — per-semester `credits` are advisory because PSU bulletin SAPs are frequently internally inconsistent per-semester but correct at the 120-credit total.

**Per-option plans (Sept 2026).** A major with options publishes one grid *per option*, but only the
first was scraped and `load_template()` fell back to it for every option — a Social Studies teaching
student got the Biology Teaching plan (278 wrong-option course slots across 134 major/option pairs;
20 after). `scrape_sap.py --options` writes one subplan template per University Park option grid
(**129**, across 47 majors), named with the catalog's option name — the value `/audit/subplans` offers and
the profile stores. PSU words the two differently ("Biology Teaching" / "Biological Science Teaching",
"Math" / "Mathematics 4-8"), so `match_option()` matches on word containment and refuses ties. A
**reworded** match must also not be contradicted by the plan's courses: two witnesses vote — the page's
own option sections (`page_option_codes()`) and the catalog's option groups — counting only courses
unique to one option *and* to this plan (every Biology plan takes CHEM 202/203, so they prove nothing).
Grids must *start* at University Park (a "Starting at Berks … Ending at University Park" 2+2 plan is
not the UP plan). `collapse_renamed_duplicates()` folds LA 83/LA 283-style double listings at scrape
time. **`load_template()`** now returns `None` (→ Layer 1 audit-driven planner) for an option with no
grid of its own when the program has option templates, instead of another option's plan; a program
without option templates keeps the shared-plan fallback. A "General …" grid no one can select becomes
the base (no-option) plan when the base is still an untouched first-grid scrape (Biology, Meteorology;
Mathematics' base was hand-edited and left alone). Rejected on purpose: RN to BSN (a 90-credit
completion degree). **PSU adds option grids after we scrape** — Cybersecurity Analytics and
Operations went from one shared grid to one per option, so an Operations student (Nate, Sept 30 2026)
got the Analytics plan while his audit listed Operations courses; a fresh-cache re-run of the options
build over every base template also found Secondary Education's new Mathematics Teaching grid. The
scraper reads `scripts/.sap_cache`, so a stale cache hides such changes — re-fetch before trusting a sweep. Tests: `tests/test_sap_options.py` (13).

**Placeholder slots + template refresh (Sept 2026).** A codeless grid cell the classifier didn't know
("400-Level HIST Course", "Option Course", "Application Focus Selection", "Chemical Engineering
Elective") fell through to a category-less gen-ed slot — and those are retired once a student's gen-eds
are done, so **1,137 major slots in 187 templates** (+133 B.A.-requirement slots) silently left the plans
of students far enough along. `scrape_sap._classify_placeholder` now types them:
- `major_selection` / `application_focus` pools (with `dept`/`level` when the label names them) —
  satisfied by `sap_schedule._assign_major_selections` from courses the **major audit** credited to a
  pool the template does **not** itemize (`build_major_pool_codes(audit, template)`; ETI's CMPSC 131 is
  the IST 140 slot's, not a focus course). **Never** from leftover electives. Unsatisfied → scheduled.
- `ba_requirement` pools ("BA Fields", "World Cultures") — satisfied from leftovers before free electives.
- Only an **unqualified** elective ("Elective", "General Elective") is free; "Technical/Engineering/
  CMPEN Elective" is `major_selection` (typed free, a ChemE student's unrelated surplus "completed" them).
- Supporting / breadth cells keep their named course as an anchor ("PHYS 213 (or Supporting Course)");
  `_normalize_breadth` keeps Smeal's two plain sequence slots (the 6f6fea7 hand edit, now scraped).
Slot keys carry dept/level (`pool:MAJOR_SELECTION:HIST:400#s12`) so `/courses` search scopes itself —
the placeholders are searchable in the existing app build.

`scripts/refresh_sap_templates.py --cache DIR [--write]` regenerates every template from today's
bulletin (27 were stale — ETI lacked ETI 100/200 entirely). Every earlier template edit is reproducible
by the scraper (git history is scraper output + LA 83/283 + 6f6fea7 + Forensic Chemistry, re-applied via
`SUBPLAN_PROGRAMS`). Verified: 300 of 307 fresh-student plans identical in length/credits (the 7 are the
majors PSU changed); every real-user plan change was traced. Tests: `tests/test_plan_placeholders.py`.

**Application Focus (Sept 2026).** Five majors require credits from ONE focus area the student picks —
ETI (12), Data Sciences IST (12), HCDD (12), Cybersecurity A&O (9), IT Ethics (12). ETI, Cybersecurity and
IT Ethics publish the areas as bulleted lists in the plan tab ("**Business Competency** Select 12 credits
from the courses below: …") and word the requirement "must *complete* 12 credits from a single
Application Focus" / "Focus Area: Select 12 credits", so the catalog had no focus requirement at all.
`scrape_psu._focus_areas` reads both layouts (codes only from list entries, never an area's notes, which
cite prerequisites; suffix twins like MKTG 301/301W merged so one course can't count twice) and emits one
pool per area (`focus_area` = its name) plus an any-area pool (`focus_area = "*"`).
`routers/audit._filter_rows(..., focus)` keeps the student's area, or the any-area pool until they pick.
ETI Business Competency's Note 3 ("one of these satisfies a major requirement … may not double-count") is
encoded as threshold 12 + the overlapping major pool's 3 = 15 — all five items. The student's choice lives
on the users row (`focus`); `GET /programs/focus-areas?major=`, `PUT /users/me/focus` (validated against
the major's areas; cleared when the major changes). Timeline `application_focus` slots search the chosen
area (`routers/courses._focus_universe`). Mobile: `components/ApplicationFocusCard.tsx` on Account,
`services/focusService.ts`. **Before a focus is picked, the slots aren't a course choice**: `_label_focus_slots()` (timeline,
post-pass, only majors with `focus_area` rows) renames unfilled ones "Application Focus (please select
one)" with `needs_focus`; after, "<area> course". The app sends a `needs_focus` tap (timeline + home) to
Account via `openFocusPicker()` — it scrolls to the card, opens the area list, and returns the student to
the screen they came from after they pick (a "‹ Back to your plan" link if they don't). Tests:
`tests/test_focus_slot_label.py`.

**Options another college offers.** The Data Sciences page is published once per college (IST,
Engineering, Science) and prints all three options, each under an `<h6>` "Only Available through the
College of …" note — every college offers one. `scrape_psu._offered_here` skips an option whose note
doesn't name the page's own college (from its URL), so each program lists only its option (IST: Applied,
with the focus; Engineering: Computational; Science: Statistical Modeling). The focus lists "missing" from
the Science/Engineering pages were never theirs — the focus is Applied-only.

**Scraper** — `python scripts/scrape_sap.py` (`--dry-run`, `--check-catalog`, `--options`). Deterministic HTML parse of the CourseLeaf `table.sc_plangrid` (each `<td>` `header` attr encodes exact year/term), **not** an LLM extraction. Only templates that pass `validate_template()` are written — a bad scrape never goes live. Smeal-style mirrored multi-family cells — `(MATH 110 or MATH 140) or (SCM 200 or STAT 200)` repeated once per family across semesters — are split by `_narrow_family_slots()` into one `choose_one` per family (each occurrence keeps its first-listed/suggested family), so the timeline shows "MATH 110 or MATH 140" and "SCM 200 or STAT 200" as distinct slots and the matcher can't satisfy both from a single family. A one-off multi-family cell stays flat (genuine N-way choice).

### Minors & certificates (credentials)

A student declares minors/certificates **from the Account page** (never onboarding — signup stays
"one major, one transcript, done"); the audit reports progress and the timeline schedules the
remaining courses. Design doc: `docs/minors-certificates.md`.

**Requirements are a bundled file, not table rows.** `backend/credential_data/credential_requirements.json`
(207 University Park credentials) + `credential_catalog.py`, the same pattern as `sap_templates/` +
`plan_templates.py`. `run_audit()` is pure — it takes requirement-row dicts, not a table handle — so
`to_requirement_rows()` converts JSON groups in memory and **the engine cannot tell a credential from
a major**. A bundled file avoids the per-table prod IAM grant and a prod seeding run on every data
refresh, and it diffs in git so a re-scrape is a reviewable PR. The `requirements` table still holds
the *old, broken* credential rows from `load_catalog.py`; nothing queries them any more.

> **The scraped credential rows were unusable** — only 52% had a plausible credit total and
> *Arts Entrepreneurship, Minor* demanded 660 credits, because `scrape_psu.py` reads pages as text
> and only resets group state on an `<h2>`–`<h5>`, while credential pages carry one heading and put
> all structure inside a single `table.sc_courselist`. The rebuild lives in **`credentials/`**
> (own README) and parses the CourseLeaf classes instead. **204 of the 205 credentials that publish
> a credit total now agree with PSU's own published number**; `python credentials/scrape_credentials.py
> --report` reprints that figure, so a PSU page edit that breaks a parse shows up as a drop in the
> number rather than as a wrong plan in a student's timeline.

**Two new group types** in `audit_engine.py`, both modelled on `_eval_writing_intensive()` (a *rule*
evaluated against the taken-set rather than a course list):
- `dept_credits` — "Select 11 credits (at least 6 at the 400 level) in PSYCH". Handles single/multi
  subject, level floors and ranges, exclusions, and the "at least N at level L" sub-constraint, which
  **gates satisfaction** (11 credits of 100-level PSYCH does not finish the Psychology minor).
  Courses named elsewhere in the credential are excluded — PSU's word is "*Additional*".
- `unstructured_credits` — a requirement PSU defers to an adviser ("Select 6 credits from an approved
  list in consultation with the minor adviser"). **Never auto-satisfied**: the bulletin states the
  size but not the rule, and inventing one would tell a student they'd finished a minor they hadn't.
  It carries the bulletin's exact wording and is flagged `needs_confirmation` for the UI. 53 of the
  207 credentials have one (median 9 cr).

**Storage**: a `credentials: [{program, kind}]` list on the existing **users** row, capped at 3
(`MAX_CREDENTIALS` in `routers/users.py`) — same reasoning as `MAX_PER_USER` on substitutions. No new
table, so no infra change. Absent/empty is a byte-identical no-op, which is what makes this safe to
ship to live beta users.

| Endpoint | Purpose |
|---|---|
| `GET /programs/credentials?q=` | Declarable minors/certificates. Deliberately separate from `/programs/all`, which still returns **degree programs only** so an older build can never put a minor in the major slot. |
| `PUT /users/me/credentials` | Replace the whole list (idempotent). Validates catalog membership, the cap, duplicates, and "not your major". |

`credentials_audit.audit_declared_credentials()` is shared by `routers/audit.py` and
`routers/timeline.py` so the two can never disagree. **A course may count toward both the major and a
credential** — PSU's double-count rule varies by department and isn't in the catalog, and enforcing
one would silently pick which program loses the course; the UI labels the overlap instead.

**Timeline** — `_merge_credential_slots()` runs *after* both timeline paths converge, so the SAP and
Layer 1 paths behave identically: the major's plan is built first and stays authoritative, credential
work fills the leftover headroom, and only then are terms added. Departmental pools are split by the
existing `_expand_pool()` so a 6-credit requirement can fill two semesters' headroom instead of
forcing a new year; an adviser-deferred block is **never** split. Summer terms are skipped (a summer
term in the plan is there for a reason — the SAP path lifts a required internship into one). Slots
carry a `credslot:`-namespaced `slot_key`, so class-selector pin/swap works unchanged (`cred:` itself
is *reserved* in `user_choices.py` for adviser attestations, and a slot keyed under it could never be
saved — hence the distinct prefix), and a
`credential` tag the mobile card badges. `credential_added_terms` reports when declaring a credential
genuinely pushes graduation out, rather than letting a term appear unexplained.

**Mobile**: `services/credentialService.ts`, `components/CredentialPickerModal.tsx`, the
"Minors & Certificates" card in `app/(tabs)/account.tsx`, a pointer on `app/(tabs)/major.tsx` (search
screen + "Major Saved" screen), and a violet chip on timeline cards.

Tests: `backend/tests/test_credentials.py` (18, pytest or plain `python`) plus 31 parser tests in
`credentials/tests/`.

**Degree-program scoping.** `is_degree_program()` in `routers/programs.py` keeps minors/certificates
out of the **major** list (`/programs/all`, `/programs/search`: 487 → 225 programs, then 184 after UP scoping below) and `POST
/programs/select` refuses one with a 400, because the major is the single program the whole plan is
built from. They are now offered separately via `GET /programs/credentials` (above). It keys off the
row's `degree` attribute with the `", Minor"` / `", Certificate"` name suffix as a fallback, keeping
anything unlabelled — dropping only what is positively identified as non-degree.

**University Park scoping.** `is_up_program()` in `routers/programs.py` is the single authoritative definition of "a UP program" — a **denylist** (fail-safe: an unknown name is kept) with two parts: non-UP campus keywords in the name, plus `program_data/non_up_programs.json`, every degree program the bulletin's index lists *without* University Park. The name test alone leaked **41** branch-campus majors with no campus parenthetical (`Law and Society, B.A.`, `Engineering, B.S.`, `Social Work, B.S.W.` …) into the picker; with the file it shows **184**, exactly the bulletin's UP degree list minus ROTC ×3 and the B.Phil. Refresh with `python scripts/scrape_program_campuses.py`. It only scopes the *picker* — `/programs/select` and the audit don't consult it, so an existing user on one of those 41 keeps working. SAP templates are UP-only.

### Manual class editing (transcript course CRUD)
Students who registered classes in summer sometimes swap one before the term starts — not worth
re-uploading a whole transcript. `POST`/`PATCH`/`DELETE /transcript/course` (in `routers/transcript.py`)
add/swap/drop individual `transcript_courses` rows. Because the audit (`audit.py`) and timeline
(`timeline.py`) query that table **live** every request, an edit flows through to the audit, timeline,
home dashboard, and gen-ed check with no extra wiring.
- **Edit scope: in-progress only.** Endpoints refuse any row whose `status != "in_progress"`
  (`_EDITABLE_STATUSES`) — graded/transfer history stays read-only so students can't fabricate grades.
  Added courses are stored `status="in_progress"`, `grade=""`, `source="manual"`.
- **Consistency with the parser.** `_clean_course_code()` reuses `transcript_parser._normalise_code`
  and the `[WMXY]$` writing-suffix rule, so a hand-typed `IST 440W` stores identically to a parsed one
  (`course_code="IST 440"`, `is_writing=True`). Section letters (`CAS 100A`) are preserved.
- **Re-upload wipes manual edits** — the upload path deletes all rows first, which is correct: a fresh
  transcript is the new source of truth. `source="manual"` is surfaced in `GET /transcript` (an "EDITED"
  badge in the mobile UI) and future-proofs a "reset to uploaded" affordance.
- **Mobile**: `transcriptService.{addCourse,swapCourse,dropCourse}`; edit UI (Swap / ✕ drop / "+ Add a
  class") lives on the in-progress semester in `app/(tabs)/upload.tsx`.

### Two patch-script bugs that only surface against prod

Both were found by actually loading the catalog into production, and neither could have been caught by
the local rehearsal — the local DB is rebuilt by **dropping** the `requirements` table, while a prod
reload **preserves** the sentinel rows and re-patches a catalog whose pair ids differ.

**1. `patch_choose_credits_option_groups` crashed on the `__CROSSLISTINGS__` sentinel.** It scans the
whole table and did `r["requirement_group"]`; that row carries `pairs`/`pair_count` and no requirement
fields, so it raised `KeyError`. Sentinels are now skipped. The three other sites that index
`requirement_group` are safe — they operate on `scan_code(...)`/`course_code`-filtered rows, which a
sentinel can never reach.

**2. `patch_known_alternatives` orphaned one half of every pair it re-assigned.** `by_pg` is an
in-memory snapshot taken *before* any writes, and the "skip if already paired" guard reads it. So a
course appearing in several `GROUPS` entries got re-paired by the later one while its earlier partner
kept the old id **alone** — and a lone `choose_one` row evaluates as *individually required*, turning
the orphan into a phantom requirement. STAT 200 sits in three entries:

```
STAT 200  pair=1987   (re-paired by the DS 200 entry)
STAT 250  pair=1595   (orphaned, alone -> now "required")
```

That produced **262 singleton pairs across the 225 UP degree programs** — 191 STAT 250, 56 PHYS 211 —
each one a course the student was told to take despite already satisfying the alternative. `assign_pair()`
now writes the assignment back onto the cached dict; the count drops to **1**. Worth remembering as a
shape: *any* patch script that caches a scan and then mutates rows has this hazard.

### Compound choose-one branches — "A or B or (C and D)"

PSU writes alternatives whose branches are themselves *pairs* of courses:
`Accounting - ACCTG 211 or ACCTG 211H or (ACCTG 201 and ACCTG 202)`. A flat `pair_group_id` links
only **flat** alternatives, so the scraper stored that as `choose_one(ACCTG 201, ACCTG 211)` — and a
student holding just ACCTG 201 read as **finished** while still owing ACCTG 202. The audit told them
they needed *less* than they did, which is the dangerous direction.

Rows sharing a `pair_group_id` **and** a non-empty **`pair_branch_id`** now form one branch, satisfied
only when *every* member is done/in-progress. A row without one is its own singleton branch — exactly
the previous semantics. `_branch_status()` returns `done` / `in_progress` / **`partial`** / `missing`,
and **`partial` never promotes the pair**: that is the entire fix. Branch credits are summed (201+202
counts 6, not 3).

- **Both evaluators change in lockstep** — `_eval_choose_one()` *and* `_eval_choose_one_consumed()`
  (the gen-ed exclusivity twin 240 lines away). No gen-ed row carries a branch id today; without the
  twin, the first one added would silently evaluate under the old any-one-wins rule.
- **Timeline** — a branch the student has *started* is a choice already made: `_collect_missing()`
  emits the still-missing members of **that** branch as ordinary `course:` slots and takes the whole
  pair off the table, so the plan surfaces ACCTG 202 and never re-offers ACCTG 211. A student who has
  started nothing still gets a normal `choose_one` slot. Everything emitted uses the **existing** slot
  vocabulary, and `mobile/` reads neither `pair_group_id` nor `pair_status` (zero hits), so an older
  TestFlight build renders a compound branch as plain course cards.
- **Backward compatibility is proven, not asserted.** `test_legacy_choose_one_characterization` runs
  all **729** done/in-progress/absent combinations over a branch-id-free fixture against a *frozen copy*
  of the pre-change loop and asserts equality; legacy items also gain no new keys. With zero rows
  patched the change is a no-op, so **the engine ships ahead of any data patch**.
- `credential_catalog.to_requirement_rows()` passes `pair_branch_id` through — `run_audit()` is shared
  and cannot tell a credential from a major.

**Where a combo sits decides how it is tied together** — getting this wrong made the first attempt
*worse* than the bug. Forcing every combo to `choose_one` labelled a lecture+lab as "BIOL 114 **or**
BIOL 115" and gave each sibling option its own `pair_group_id`, so a student who took BIOL 114+115 was
then told to take BIOL 116 as well. Both errors over-required. The rule:

| Surrounding group | Emitted as | Enforced by |
|---|---|---|
| an `or` chain — "ACCTG 211 or (201 and 202)" | `choose_one` + `pair_group_id` + `pair_branch_id` | branch status — half a branch satisfies nothing |
| a credit pool — "Select 4-5 credits from…" | pool rows + `pair_branch_id`, **no** pair id | the credit threshold |
| anything else (lecture + lab) | both individually required | plain requirement |

A combo inside a credit pool needs no branch machinery: `BIOL 114` is 3 credits against a 4-5 credit
pool, so it cannot satisfy it without the lab. That only holds because combo members now take **real
credits** from `bulletin_courses.json` — every collapsed row in prod has `credits=None`, and
`_eval_choose_credits` defaults a missing value to 3.0, which would let a 1-credit lab count as 3.

**Scraper side** — `scrape_psu.py` now reads *every* code in a CourseLeaf code cell instead of the
first. PSU writes "both of these" as one `<td class="codecol">` holding several `<a>` links joined by
`&` (`BIOL 114 & BIOL 115`), and keeping only the first match dropped the lab or the second half of a
sequence from the program entirely. Combo members are emitted as one row each sharing a
`pair_branch_id`, and each takes its authoritative title from `bulletin_courses.json` rather than the
concatenated blob (splitting that on `" and "` is unreliable — *"Biology: Basic Concepts and
Biodiversity"* contains one). A re-scrape recovers **687 rows in 296 branches across 94 programs**,
including 3- and 4-course chains like `PHYS 211 + 212 + 213 + 214`.

The change is **strictly additive**: running the old and new scrapers over the combo-heavy programs
side by side loses nothing (0 of 5 programs lost a course) and gains only the recovered members.

> **A re-scrape is safe; a re-*load* is not.** `scrape_psu.py` writes Excel/TXT only and never touches
> DynamoDB — `load_catalog.py` does. Diffing a fresh scrape against prod shows **656 (program, course)
> pairs "missing"**, but **629 of them are injected by `patch_known_alternatives(insert_missing=True)`**
> (CAS 100B/C, DS 200, CHEM 130, STAT 250, ENGL 202C/D, PHYS 250/251 …) rather than scraped. So a load
> **must** re-run the patch scripts in the same pass or those alternatives vanish. The remaining 27 are
> pre-existing prod-vs-current-bulletin drift, not a scraper regression — verified by running the old
> scraper against the same pages and getting byte-identical output (ETI: 66 rows / 53 codes, zero diff).

**Short codes are fixed**: `_CODE_IN_CELL_WIDE` matches 1–3 digits (`ENGL 15`, `SOC 1`), gated on
`bulletin_courses.json` so a stray number can't become a course. **Still unfixed in the scraper**
(each deserves its own diff): `title[:120]` truncates 416 titles mid-word; "select 3 credits of 400-level courses" is still
parsed as a course, inventing codes like `PSYCH 400` with the title `"3"`; and a **plan-grid row
captures only one course code**, because that path does a single `search()` over the whole `<tr>`.
The grid holds two terms side by side (`A-I 100 | 3 | ENGL 15 | 3`), so the second is dropped — and
which one survives can change under you: `ENGL 15` disappeared from the AI major the moment the
hyphen fix below made `A-I 100` matchable.

**Loaded in prod** (Sept 22 2026 reload): 757 rows carry a `pair_branch_id`.

### Requirement pools — one section holds SEVERAL of them

A CourseLeaf section routinely holds several independent pools, each introduced by its own
`Select N credits from the following:` comment row and each listing its members in a
`<div class="blockindent">`. ETI's "Additional Courses" has **six**. The scraper noticed the first
and the audit engine bucketed rows by `(group_type, threshold)`, so every same-threshold pool in a
section **merged into one**: ETI's four 3-credit pools (speech, writing, intro programming, intro
IST) became a single 3-credit pool that a lone `ENGL 15` satisfied, and `CYBER 100`, `IST 140` and
the speech requirement vanished from the audit and the plan. **The app told students they owed less
than they did.** 116 of the 225 UP degree programs had more than one pool in a section.

**`pool_seq`** numbers the pools within a section. The scraper stamps it, `load_catalog.py` carries
it, and `run_audit()` keys on `(group_type, threshold, pool_seq)`. Rows loaded before the column
existed have no `pool_seq`, bucket as `None`, and behave exactly as before — **the engine is a no-op
until the catalog is reloaded**, the same discipline as `pair_branch_id`.

**Seven distinct bugs, all in pool boundaries.** They are listed because each is a different way the
same mechanism failed, and a re-scrape can reintroduce any of them:

| | Bug | Direction |
|---|---|---|
| 1 | consecutive pools merged | **under**-requires |
| 2 | `or` chain inside a pool lifted out to `choose_one` | **over**-requires |
| 3 | pool header without the word "credits" not detected | merges pools |
| 4 | a comment row with no list treated as a pool header | swallows real requirements |
| 5 | a pool leaking across tables and `areaheader` rows | prescribed courses become optional |
| 6 | an adjacent table read as its own instruction text | re-opens the leak |
| 7 | a filler word between the number and "credits" | **over**-requires |

Detail on the ones that are easy to reintroduce:

- **(2)** An `or` chain inside a credit pool is a set of *options*, not a standalone choice.
  Administration of Justice's `Select 3-4 credits` list of ten became `BA 243` required outright (a
  lone `choose_one` row evaluates as individually required), **plus** one of PHIL 106 / PHIL-STS 107,
  **plus** one of STS 101 / STS-PHIL 107 — three mandatory courses where the bulletin asks for one.
  Same rule as an `&` combo in a pool: leave the rows in the pool, let the threshold enforce it.
- **(4)** Not every `Select N` row introduces a list. Aerospace's "Additional Courses" opens with
  *"Select 1 credit of First-Year Seminar"* — a standalone instruction — followed by the ordinary
  requirement `AERSP 413 or AERSP 450`, and treating the comment as a header swallowed both.
  **Indentation decides**: a comment row opens a *pending* pool, and it is only real once an
  indented row actually arrives. An unindented first row discards it.
- **(5)/(6)** Pools were only ever closed by an `<h2>`–`<h5>`, but CourseLeaf also starts sections
  with `<tr class="areaheader">` rows and with whole new tables. Fixing that exposed a second problem
  underneath: the "instruction before the table" heuristic calls `find_previous_sibling()`, and when
  two courselist tables are adjacent **the previous sibling is the first table**, whose own
  `Select 3 credits` row re-opened a pool over the next table's prescribed courses. Only a *prose*
  sibling counts now.
- **(7)** Spanish B.A. heads two pools *"Select 9 **additional** credits from the following"*. The
  filler word broke the match, and the areaheader fix in (5) removed the accidental type-leak those
  rows had been riding on — so 34 SPAN courses came out **individually required**. A regression
  introduced by the fix and caught by the verifier; filler words (`additional`, `more`, `elective`,
  `total`…) are now allowed between the count and "credits".

Also fixed: **hyphenated subject prefixes**. `A-I 100` was invisible to `[A-Z]{2,6}`, so ETI's intro
pool offered six options instead of seven.

**Over-requiring shapes (Sept 2026).** A second family of bugs stored elective lists as individually
*required* courses — Biology 272-495 credits for a 50-55 credit option, Psychology's Business Option 183
for 24, Data Sciences (IST) 620, HCDD 386. Fixed in `scrape_psu.py` (tests: `test_scraper_shapes.py`,
real-page fixtures `tests/fixtures/req_*.html`):
- **Qualifier before the number** — "Select *a minimum of* 12 credits", "Select *at least* 6" (`_POOL_HEADER`).
  A cap ("A maximum of 3 credits may be chosen from") is deliberately *not* a header.
- **A header whose prose names a course** — "…can be replaced by LA 495", "not to include PSYCH 294",
  "except MATH 401". The code made the row read as a course: the pool never opened, and an *excluded*
  course became required. A `courselistcomment` row that reads as a pool header is a header.
- **Pick one block** (`_PICK_BLOCK`) — "Select one concentration", "Select an emphasis", "Select one
  sequence of the following", "Select course set A or B", "…with selected emphasis area". Modelled like the
  existing sequence pools: one credit pool, low end of the stated hours, over every block's courses
  (which block isn't enforced). Indented "Select N" rows inside an open block don't open new pools.
  World Languages' emphases sit in separate `<h6>` tables after "Select an emphasis"; they continue that
  pool — but only a block-wording header may be continued (a plain "Select one of the following: 3" inside
  the French emphasis once filed German–Spanish under a 3-credit pool, the *under*-requiring direction).
- **Application Focus lists** live in the Suggested Academic Plan tab; each area became its own required
  group. Now the plan tab contributes only its semester grids, and "Select 12 credits from the Application
  Focus lists" becomes one 12-credit pool over all areas' courses (can't enforce "your chosen area").
- **Options without "Option"** — Data Sciences' "Applied Data Sciences (DATSC_BS…): 47 credits" under
  "Requirements for the Option" gets " Option" inserted, so the audit narrows to one; the subplan name the
  student sees is unchanged. `alternative_inserts.json` keys were renamed to match.

Verified with `verify_pool_split.py`, updated *independently* (codes from cell text vs the scraper's own
rules): disagreements 20 → 9, none new (the 9 are prose-invented codes, below). 0 of 171 size-stated
option groups now exceed their size (was 10). Every course the new scrape drops (28) was checked: all were
codes invented from prose. **Loaded with `scripts/reload_programs.py`** — re-scrapes and replaces only
named programs (41), offsets pair/branch ids above the table max, backs up, runs the patch pipeline in the
same pass, `--restore` undoes. Rehearsed locally: nothing outside the 41 changes, restore is exact.

**`build_satisfied_req_codes()` now counts in-progress work** when deciding a pool is covered. Its
docstring already named the case (*"once the pool is met, e.g. via CMPSC 131"*) but `satisfied` on a
`choose_credits` pool is **completed credits only**, so a student sitting in CMPSC 131 was still
scheduled `IST 140` for the following fall. This stayed hidden while pools were merged, because a
merged pool was always already satisfied by something finished elsewhere in it.

> **The scraper is not allowed to be its own witness.** `scripts/verify_pool_split.py` re-fetches
> every changed program and re-derives its pools with a **second, independently written parser**,
> then compares. Final run: **136 of 225 programs changed, 0 disagreements**. Bugs 2–7 were all found
> this way, and so was the Spanish regression. Two caveats learned the hard way — a slash cell
> (`EE 471/AERSP 490/NUCE 490`) is **one** course cross-listed three ways, not three requirements;
> and a non-pool comment row does **not** end a list (pages use them as sub-headings), while an
> `areaheader` does. Getting either wrong swings the disagreement count by 20+, all of it noise.

**Pool slot keys.** One section can hold several pools, and they would all collide on the section
name, so `_pool_slot_key()` appends `@<seq>`. The **first** pool keeps the bare historic key, so no
stored `user_course_choices` row is orphaned by the change. `_apply_pool_choice()` and `_apply_pins()`
fall back to the base key when `_expand_pool()` has split a pool into `#0`/`#1` slices, so a choice
made against the whole pool still lands.

> **The catalog data is gitignored.** `PSU_Major_Requirements.xlsx` is not in the repo, so this ships
> as code only — every environment needs its own `scrape_psu.py` → `load_catalog.py --replace`, and
> that reload **must re-run the patch scripts in the same pass** or the ~629 injected alternatives
> vanish. **Prod was reloaded on Sept 22 2026** (`load_catalog.py --replace` + `apply_catalog_patches.py`):
> 11,896 rows carry `pool_seq`, ETI's `CYBER 100` sits in its own pool, and there are 0 singleton pairs.

Tests: `backend/tests/test_pool_split.py` (37, pytest or plain `python`); the fixture
`tests/fixtures/eti_courselist.html` is the real ETI courselist table.

### Entrance to Major

**A gate, not extra credits.** Of the 88 programs with a course gate and catalog rows, **87** have
every gate group satisfiable from requirements the major already lists (the exception is Music
Education's `ENGL 15`, which lives in `__GEN_ED__`). So it is modelled as its own bundled spec, never
as requirement rows — those would double-count the credits and schedule the same course twice. What
the gate adds is a **deadline** (PSU expects it by the end of the fourth semester), a **minimum
grade**, and a **GPA floor**. Not one row in the 35k-row catalog carried any of this before: it lives
in prose in a tab, and `scrape_psu.py` only reads tables.

| File | Purpose |
|---|---|
| `entrance_parse.py` | Bulletin parser — sections, groups, branches, GPA, and what we refuse to model |
| `entrance_to_major.py` | Runtime: `evaluate()`, `attach_slots()`, `priority_codes()` |
| `entrance_data/entrance_requirements.json` | Bundled spec, 322 programs (same pattern as `credential_requirements.json` — no new table, no prod IAM grant) |
| `scripts/scrape_entrance_to_major.py` | Re-scrape; `--report` reprints the health stats |

**Anchor on the tab container, never the heading.** PSU writes `Entrance to Major` (ETI, Astronomy),
`Direct Admission to the Major` (Nursing, Law and Society) and `Entrance Procedures` (Architecture)
for the same thing. Matching the heading covered **186 of 225** selectable majors and silently
reported "no section" for the other 39 — every Nursing and Architecture program among them. Every
page wraps it in `<div id="howtogetintextcontainer">`. Now **207 of 225**; the other 18 publish no
gate at all (16 associate degrees plus two bachelor's verified by hand).

**A gate is never reported cleared when we cannot check it.** 81 of the 207 carry something
unverifiable — portfolios, enrollment controls, application deadlines, World Languages' 80 documented
volunteer hours. Those return `needs_confirmation` with PSU's exact wording, the same discipline as
`unstructured_credits` on credentials. Two traps worth keeping:

- **Contradictory GPA figures.** Accounting names **3.10** for entrance and **2.60–3.09** for "space
  availability". Whichever matched first became the answer, so the student was told the bar was 2.60.
  Multiple distinct figures now assert *none* of them and say so.
- **Over-eager flagging.** A bare `"application"` substring flagged the *Artificial Intelligence
  Methods and **Applications*** major off its own name, so phrases are word-bounded and specific. But
  under-flagging is worse: Architecture's gate is a portfolio plus an external application, and
  reading "no courses, no GPA" as "no gate" would tell that student there is nothing to clear.

**Compound branches are AND, not OR.** `ACCTG 211 or ACCTG 211H or (ACCTG 201 and ACCTG 202)` — a
group is a list of *branches*, each a list of codes that must **all** be taken. Reading the inner
pair as alternatives clears the gate for a student holding only ACCTG 201. Inline annotations are
stripped first: `HCDD 113S (FYS) or CYBER 100S (FYS)` split ETI's single 7-way alternative into three
groups, a gate three times harder than the real one.

**Wiring.** `GET /audit` returns the gate as **status only**. `GET /timeline` returns it with each
unmet group's `slot_key` attached, because slots are the timeline's to know and **the two vocabularies
disagree**: a templated major emits `one:CYBER 100|IST 110` where the Layer 1 packer would say
`course:ETI 100`. Attaching the wrong one stores a choice against a slot the student's plan never
renders — it saves successfully and does nothing. `attach_slots()` scores candidate slots by how many
of the group's options they offer, so a 7-option group doesn't bind to a bare named slot with nothing
to choose from.

Gate courses also sort first on the Layer 1 path (`_sort_named(priority=…)`) and carry an
`entrance_to_major` flag on both paths.

**Major-only courses wait for entrance.** PSU's flow: the semester a student finishes their last gate
course is when they *conditionally declare*; major-only courses open the **semester after**.
`_hold_for_entrance()` (`routers/timeline.py`, runs on both paths before pins) finds the last planned
term holding an unmet gate course and moves any locked course sitting at or before it into the next
term, swapping a pool/gen-ed placeholder back so credits balance (a named course is never pulled
earlier). A gate `semester_standing` can push entrance later; a gate already done/in-progress locks
nothing. The response's gate carries `major_courses_from`; moved slots carry `held_for_entrance`.
- **"Locked" is a heuristic** — no source publishes per-course major restrictions we may read (the
  bulletin has prerequisites only; public LionPATH's `robots.txt` is `Disallow: /`). A course is locked
  if it is 300/400-level (incl. `FIN 4XX` placeholders) in the major's dominant upper-level prefix
  (`major_depts()`) and is **not** a gate course (Smeal's gate includes FIN 301).
- **The gap is filled, not left empty**: with no pool/gen-ed placeholder to trade back, the hold pulls
  forward a later course that isn't locked or pinned and whose prerequisites are met by then
  (`_eligible_in`, via `course_prereqs`). Without it an ETI student whose ETI 301/302 waited got a
  9-credit spring while BA 302 and ENGL 202C — open to them — sat a term later.
- **A full term trades, it doesn't skip** (Sept 30 2026): with no placeholder to swap back, the hold
  trades an open, eligible named course out of a full term rather than skipping to the next one. Skipping
  pushed an ETI student's ETI 302 past a full fall and slid ETI 420 → 421 a whole term. When the hold
  moved anything, `_relieve_overload()` then moves unpinned placeholders out of terms above
  `_TARGET_CREDITS` into the lightest later Fall/Spring term, because the traded-back placeholders stacked
  both Application Focus slots into one 18-credit spring. The Application Focus picker
  (`_focus_universe`) also drops courses already on the transcript. And `_chosen_first()` (both paths,
  after prereq order) swaps a picked pool slot ahead of a still-blank one from the same pool: the packer
  moves blank placeholders freely but a picked slot is a named course that keeps its template spot, so a
  chosen BA 301 sat behind a blank focus slot.
- **PSU's plan overrides the heuristic**: anything a SAP template schedules in or before its own entrance
  semester is open (`_template_open_codes()` — SCM 301 sits beside FIN 301 in Supply Chain's plan). With
  that, a fresh student in all 157 gated templated majors sees **zero** moves; it only bites for students
  who are behind on the gate or ahead elsewhere. Being wrong schedules a course later, never earlier.

**Mobile**: `components/EntranceToMajorCard.tsx`, a checklist on the Account page only — no
onboarding step, no blocking. Choosing a course writes an ordinary `user_course_choices` row against
the slot the timeline **already** emits for that requirement, which is what lets the pick flow into
the plan without scheduling a second copy. The semester is optional; the default is "GradGPS
decides". The card hides entirely once the gate is cleared with nothing left to confirm.

Tests: `backend/tests/test_entrance_to_major.py` (38); the `tests/fixtures/etm_*.html` fixtures are
real bulletin sections covering each shape.

### Course title & credits come from the bulletin, not the catalog

The `requirements` table stores one row per **(program, requirement slot, course)**, so a widely
required course has hundreds of rows — MATH 140 has **478 across 138 programs**, because a bulletin
page repeats a shared requirement once per subplan (Information Technology B.S. alone carries 26
`MATH 140` rows, each its own `choose_one` pair, all of them "MATH 110 or MATH 140"). Those rows were
scraped at different times from inconsistently formatted pages and **they disagree**: of MATH 140's
478, 355 say 4 credits, 37 say 3, 14 say 1, and 70 carry no credits at all.

`_get_course_meta()` used to take `items[0]` and coerce a missing value to 0, so the credits a student
saw came down to scan order — and a null row rendered as "0 credits", which the mobile badge
(guarded on `credits > 0`) hid entirely. Voting across the rows fixed the zeros but not the data:
prod's STAT 200 splits **217 rows saying 3 against 139 saying 4**, and PSU publishes 4.

So **`backend/scripts/bulletin_courses.json` is now the source of truth** for title + credits —
PSU's own published number for all **9,479** undergraduate courses, built by
`python scripts/scrape_bulletin_courses.py` (~5-10 min). The lookup is a dict hit rather than a
35k-row table scan, so the course screen got ~2000x faster too (≈4-6 s cold → ≈2 ms). The majority
vote survives as the fallback for anything the bulletin doesn't list (e.g. `IST 301`, renamed to
`ETI 301`), and an unreadable data file degrades to that fallback rather than 500-ing.

> **Why the scraper reads `.course_codetitle` and `.course_credits` separately:** the old
> `scrape_course_titles.py` took `.courseblocktitle` as one text blob and regex-stripped the credits
> back out, which is how KINES 1 got stored as *"Introduction to Outdoor Pursuits 1.5-/Maxi"*. The
> bulletin puts the two in separate elements — reading each directly fixed **2,904 mangled titles,
> 31% of the file**. `scrape_bulletin_courses.py` writes `bulletin_course_titles.json` too, so
> `fix_junk_titles.py` keeps working and gets the corrected titles.

**The bulletin keys writing courses with their suffix** (`CHEM 423W`; 359 have no bare twin, and 16
are a *different course* from it — FRNSC 485W is 4 cr, FRNSC 485 is 2). So `_get_course_meta()` tries
the raw code before the stripped one **and caches under the code as asked** (keying on the stripped code
served whichever twin was looked up first for both); the timeline's transcript cards re-attach the suffix
from `is_writing` (`_transcript_display_code()`, letter taken from the bulletin), and
`_fill_future_titles()` fills recommended cards *and* dropdown options (title + credits) from the
bulletin before the catalog vote — catalog rows carry junk like FRNSC 475 = *"Supporting Course
(consult your adviser) \*3"*.

Variable-credit courses (2,270 of them) carry `credits_max`; the API adds a `credits_label`
("4", or "1.5-3") which the mobile badge prefers when present.

### Professor ratings — withdrawn (Sept 2026)

The course screen used to show RateMyProfessors ratings. It was removed because RMP's Terms of Use
prohibit automated access, storing a copy of their index, and commercial use; because the client
sent a spoofed User-Agent and a hardcoded `Authorization: Basic` header at a **private** GraphQL
endpoint (which is outside what *hiQ*/*Van Buren* protect — that holding is about **public** pages);
and because Apple guideline 5.2.2 requires authorization to be produced on request. Hiding it behind
a flag was considered and rejected — guideline 2.3.1 names "dormant" features specifically, and it
would not have stopped the monthly crawl anyway.

`backend/rmp_client.py` and `backend/scripts/build_rmp_index.py` remain in the repo, **dormant** —
imported by nothing, scheduled by nothing, shipped in no binary. Do not wire them back up without
written permission from Rate My Professors, LLC. Full rationale and the replacement plan
(PSU public class search + deep link, which needs no one's permission): `docs/professor-ratings.md`.

### Course substitutions (the advisor workaround)
Departments routinely accept one course in place of a requirement — Connor took **ESC 120
"Design for Failure"**, which his adviser counts for **CHE 100** — but the catalog only knows the
requirement's own code, so GradGPS kept telling him to take CHE 100 and the timeline scheduled a
phantom course. `PUT`/`DELETE /substitutions` let the student declare the swap themselves.

- **A substitution is a per-user course equivalence** — exactly the shape of the built-in
  `_EQUIVALENCE_PAIRS` in `audit_engine.py` (IST→ETI renames, cross-listings, first-year seminars),
  just declared by one student for one requirement. So it is applied at the same choke point:
  `_build_taken(transcript_courses, substitutions)` registers the requirement's code against the
  substitute course's transcript entry. Every downstream consumer — major audit, gen-ed audit,
  timeline, home dashboard, SAP template matcher — inherits it with no extra wiring. `run_audit()`,
  `run_gen_ed_audit()` and `sap_schedule.build_taken_set()` all take an optional `substitutions` arg
  (omitting it is a byte-identical no-op).
- **The substitute must be on the transcript**, and it is registered with `setdefault` — so a
  substitution can only ever re-point credit the student already earned into a slot nothing else
  filled, never overwrite a course they really took. A stale declaration satisfies nothing.
  `min_grade` still applies; an in-progress substitute reads as in-progress.
- **Guardrails** (`routers/substitutions.py`): codes are format-validated, self-substitution is
  refused, one course may back only one requirement (no silent double-count), and `MAX_PER_USER = 20`
  keeps the feature from being used to mark a whole degree complete. The mobile UI labels it as the
  student's own declaration, not an approved exception.
- **Storage reuses the `user_course_choices` table** under a `sub:` slot_key namespace rather than
  adding a table — prod DynamoDB IAM is per-table scoped, so a new table needs an infra change first,
  and a substitution is the same kind of row the table already holds (a student's decision about
  their own plan). `routers/user_choices.get_user_choices()` skips that namespace, and its
  `PUT`/`DELETE` refuse a `sub:`-prefixed slot_key.
- **`GET /substitutions/candidates?requirement_code=…`** returns the student's own transcript
  courses, **ones the audit hasn't already credited first** — that's almost always the course the
  adviser approved. Already-credited courses stay in the list (advisers do approve double-counts) but
  carry an `already_used` flag the UI badges.
- **Mobile**: `services/substitutionService.ts` + `components/SubstitutionModal.tsx`. Entry point is
  a row in `CoursePickerModal` ("I already took a class that counts for this"), shown for
  named-course slots only (a gen-ed/pool slot is a category — you pick a course for it there
  instead). Wired on both the timeline and home screens; saving refetches so the plan reflows.
- Tests: `backend/tests/test_substitutions.py` (runs under pytest or plain `python`).

### Auth (dev vs prod)
- **Real auth**: Google/Apple OIDC ID tokens, verified in `backend/auth.py` (JWKS signature, aud, iss, exp). Canonical `user_id` = provider-scoped sub (`google:<sub>` / `apple:<sub>`). Client IDs in `backend/.env` (`GOOGLE_CLIENT_IDS`, `APPLE_CLIENT_IDS`). Mobile: `expo-auth-session` in `signup.tsx` → `signInWithIdToken()` in `AuthContext` → token in SecureStore (AsyncStorage on web) → axios interceptor sends `Authorization: Bearer`.
- **Dev bypass**: `AUTH_DEV_BYPASS=1` in `backend/.env` accepts the legacy spoofable `x-user-id` header (and leaves `/admin/*` open + keeps legacy `POST /users/create` alive). This is how Expo Go on the phone works (test user `matthew-test-001`). NEVER set in prod.
- **Google OAuth cannot run in Expo Go** (auth proxy removed in SDK 50) — test the Google flow in Expo web (`npx expo start --web`, client ID allows localhost:8081/8082) or a dev build.
- **Sign in with Apple is implemented** (`expo-apple-authentication` in `signup.tsx` → `signInWithIdToken()` in `AuthContext`; backend verifies Apple ID tokens in `auth.py` → `apple:<sub>`). The native Apple button only renders where the module is available (`AppleAuthentication.isAvailableAsync()`) — iOS dev build / TestFlight / App Store, **not** Expo Go or web. Apple returns the user's name **only on the first authorization**, so `signup.tsx` captures it then and passes it via the `profile` arg (the ID token itself omits it). `APPLE_CLIENT_IDS` in `backend/.env`.
- **Sessions**: the mobile app exchanges the ~1 h ID token for a server-issued opaque session token
  (`POST /auth/session` → `sess_*`, stored SHA-256-hashed in the `sessions` table, 30-day sliding
  expiry via DynamoDB TTL + read-time check in `sessions.py`). `get_current_user` resolves `sess_*`
  bearers from the table; other bearers still get full OIDC verification. `DELETE /auth/session` =
  sign-out. A 401 with a token armed auto-clears mobile auth state (`setOnUnauthorized` in
  `services/api.ts`) and routes back to sign-in.
- **Admin**: `/admin/*` gated by `require_admin` — open under dev bypass, else `ADMIN_USER_IDS` allowlist (comma-separated provider-scoped ids).
- **App Review demo account**: App Review cannot obtain a PSU transcript, and Google/Apple
  sign-in would land a reviewer in their own empty account — guideline 2.1 rejects an app the
  reviewer can't evaluate. `_review_account()` in `routers/email_auth.py` short-circuits the
  **code check** inside the existing `/auth/email/verify` for one env-configured address:
  `REVIEW_EMAIL` + `REVIEW_CODE` (exactly 6 digits). Either unset = the path does not exist, so
  it is a byte-identical no-op. It is **not**
  a bypass: the session is minted by the normal path as `email:<that address>`, no other user id
  is reachable, and `get_current_user` is untouched. Unlike a real OTP the code is static and
  never burns, so the demo branch carries its own rate limit (10/hr per IP, 60/hr global).
  Populate the account with `scripts/seed_demo_account.py` (wholly synthetic — fabricated
  student, real catalog codes, an SAP-templated major so the timeline shows its richer path);
  `scripts/make_demo_transcript_pdf.py` regenerates the sample upload PDF in
  `scripts/demo_assets/`, which needs the `.gitignore` exception to the blanket `*.pdf` PII rule.
  Submission paperwork: `docs/app-store-submission.md`.
  **Live in prod since 2026-09-22** (`REVIEW_EMAIL=appreview@gradgps.com`, account seeded).
  1.1.0 (build 10) **cleared App Review on 2026-09-28**. Keep the path and account in place — every
  future version submission is reviewed with them. **`REVIEW_CODE` rotation is still pending** — the
  current value has been in App Store Connect; rotate it and update the review notes there together.

### App version gate & client version reporting
The mobile `UpdateGate` (`components/UpdateGate.tsx`) polls `GET /config/app` at launch and
compares the running build to `latest_version` (dismissible "update available" banner) and
`min_supported_version` (hard block). Two related pieces:
- **Admin-published gate.** `GET /config/app` resolves each field **stored override → env var →
  fail-open default** (`backend/app_config.py`). The override lives as a singleton row in the
  **users** table (`user_id="__APP_CONFIG__"`, same sentinel pattern as `__GEN_ED__`) so an admin
  can bump the banner live from the dashboard with **no redeploy** — the App Runner role already
  writes the users table, so no new IAM/table. `GET`/`POST /admin/app-config` read/publish it; the
  "App Version & Updates" panel in `static/admin.html` is the UI. The sentinel row is filtered out
  of `/admin/users` and `/admin/stats`.
- **Client version reporting.** The mobile app tags every request with an `X-App-Version` header
  (`services/api.ts`, from `Application.nativeApplicationVersion`). `client_meta.touch_client_meta()`
  stamps `app_version` + `last_seen` onto the user row — called only from endpoints the app already
  hits on launch (`GET /audit`, `GET`/`POST /users/me`), never the hot auth path, and **throttled**
  to ~one write per user per active day. The admin dashboard shows a per-user version column and a
  build-distribution bar (`/admin/stats` → `versions`).

### Honors (Schreyer) courses
Phase 1 of `docs/honors-plan.md` (Sept 29 2026): stop penalizing honors coursework. Plus the Schreyer
declaration and the first per-major thesis rule (ME). Still not built: honors-credit tracker, GPA,
thesis for other majors.
- **RCL fills ENGL 15 / CAS 100 / the First-Year Seminar, one way.** ENGL/CAS 137H → ENGL 15,
  ENGL/CAS 138T → CAS 100 + every UP seminar code (`HONORS_FILLS`, `_FYS_CODES` in
  `audit_engine.py`). Applied in `_build_taken()` with `setdefault` after real courses, as a tagged
  copy (`_fill_of`), so rule pools (`dept_credits`, writing-intensive) skip it; seminar fills are also
  hidden from credit pools (`_pool_taken()`) because many seminars carry gen-ed attributes (GER 83 is
  GH/IL/US). Not `_EQUIVALENCE_PAIRS` — those are symmetric, and ENGL 15 must never fill an RCL slot.
  SAP side: `sap_schedule._taken_tokens()` (transcript side only; also used for leftover detection so
  137H can't double as a free elective).
- **M (honors + writing) is stripped like W** by `_normalise_code`; the audit's suffix strip is
  `_strip_attr()` (`[WHMN]`). Old prod rows still holding `BIOL 230M` match via a normalized key.
- **Cross-listings are keyed on storage form too** — `CAS 137H`/`ENGL 137H` and 165 other suffixed
  pairs never fired because the transcript row is stored stripped.
- **Storage keeps `raw_code` + `is_honors`** (H/M/T/U suffix, `is_honors_code()`) on upload, manual
  add/swap and `reparse_stored_transcript.py` (which also now writes `credits`/`course_title` like the
  upload route). The timeline's past cards show `raw_code` when present. Existing rows need a reparse.
- **ENGL 202H covers ENGL 202A–D** (product decision): a one-way fill, named-only like the seminar
  fills so a pool listing 202C and 202D can't count one 202H twice; the plan matcher skips it
  (`honors_fills(for_plan=True)`) because its section-letter rule already pairs `ENGL 202` with a 202C slot.
- **Schreyer declaration** (`honors.py`): `honors = {program: "schreyer", entry: first_year |
  second_year | third_year}` on the users row, set by `PUT /users/me/honors` (null program clears),
  returned by `GET /users/me`. Absent = no-op. Mobile: `components/SchreyerHonorsCard.tsx` on Account,
  `services/honorsService.ts`.
- **Thesis in place of electives** — `honors.THESIS_RULES`, applied by `apply_thesis_rule()` right
  after `load_template()` in the timeline (SAP path only; deep-copies, never mutates the cached
  template). Each swap replaces the first slot with a given label, credits preserved overall.
  Only ME so far: ME 494H (5) + ME 493 (1) for one ETE + the GTE. Add a major only from a published
  department rule.
- **Live in prod Sept 29 2026** (backend `dc5f92e` + `bd6dc58`, Account card via EAS update `eaaf8151`).
  Prod transcripts were re-parsed the same day to restore `raw_code`/`is_honors` for 6 of 7 users with a
  stored PDF (backup `backend/backups/honors_reparse_20260929_205315.json`); the 7th has manual class
  edits a re-parse would wipe, so it picks the fields up on its next upload.
- Tests: `backend/tests/test_honors.py` (22).

### Official vs unofficial transcripts
Students sometimes upload their **official** transcript instead of the unofficial LionPATH one. Official transcripts have a different layout that the plain-text parser mangles (validated against a real signed sample: 13 partly-wrong courses, every term `Unknown`). Handling:
- **Detection** — `official_detector.detect_official(pdf_bytes, full_text)` returns a scored `OfficialDetection`. Byte anchor is `/ByteRange` + `adbe.pkcs7` (a certified PDF; **do not** test the spaced `/Type /Sig` — the real sample has `/Type/Sig` with no space) worth +4, plus the "OFFICIAL TRANSCRIPT" header (+3), registrar language (capped +2), and a `UNOFFICIAL` hard veto (−5). Threshold 4 → the signature bytes alone trigger.
- **Dedicated official parser** — `parse_official_transcript()` exists because official transcripts are (a) two term-columns side by side, (b) overlaid with a diagonal "Copy of Transcript" watermark, (c) full-name terms ("Fall 2025"). It uses `page.extract_words()` with coordinates, drops watermark glyphs by **font size** (real text is 6–9 pt, watermark is 16–22 pt; threshold `_WATERMARK_MIN_SIZE`), splits words at the page mid-x into two columns, rebuilds lines per column, and normalizes full-name terms via `FULL_TERM_PATTERN`. `parse_and_detect()` routes to it when detection says official.
- **Safety net** — `official_parse_looks_bad()` (too few courses, or >30% `Unknown` terms) makes the route return a 422 steering the user to their unofficial transcript rather than storing a garbled parse. The de-interleaver is tuned from a **single** sample — validate against more before trusting it broadly.
- **Consent gate (single-endpoint 409)** — `POST /transcript/upload` takes an `acknowledge_official` form flag. When `OFFICIAL_DETECT=1` (in `backend/.env`) and an official transcript is detected without the flag, it returns **409** `{needs_official_ack: true, ...}`; the client warns the user and re-submits with `acknowledge_official=true`. `OFFICIAL_DETECT` unset = **shadow mode**: detection + official parsing still run and log, but never 409 (validates false-positive rate before the dialog goes live).
- **Consent audit trail** — an acknowledged official upload writes `transcript_kind="official"` and `official_transcript_ack_at` to the user record (both cleared on DELETE / a later unofficial upload); S3 object gets `transcript-kind` metadata. Response adds `transcript_kind` and, for official, a `parse_warning`.
- **Mobile** — `transcriptService.isOfficialAckError(e)` detects the 409; both `upload.tsx` screens show a consent `Alert` and re-upload on confirm. The error handler guards `typeof detail === "string"` because the 409 `detail` is an object (else `[object Object]`).
- Tests: `backend/tests/test_official_detector.py` (runs under pytest or plain `python`; set `OFFICIAL_SAMPLE_PDF` to exercise the real-sample end-to-end test).

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

Useful as a fixture because he exercises both new mechanisms: his ETI plan has **six** requirement
pools (the merge bug's original report was that `CYBER 100` never appeared), and he has cleared only
**1 of 6** Entrance to Major groups, so the gate checklist renders with real content.

---

## Website SEO — per-major pages
gradgps.com is static (`website/`, GitHub Pages via `deploy-website.yml`). `python tools/site/majors.py`
generates `website/majors/<slug>.html` + `/majors/` index + the `<!-- majors -->` block of `sitemap.xml`
from the SAP template, the Entrance to Major spec and `bulletin_courses.json` titles, flagging gate
courses inside the plan. Pilot is 5 majors (`MAJORS` list); widen once Search Console shows them indexed.
A GPA floor is published only when the bulletin names exactly one figure (`gpa_candidates` is unreliable
otherwise). `build.py` now walks subdirectories. Search Console is verified (Domain property via GoDaddy).

**Download CTA.** GradGPS is public on the App Store (app ID `6803643612`, since Sept 28 2026). Every
"Get the app" CTA points at `/download`; `website/beta.html` is a noindex redirect stub kept so the old
beta link still works. The Smart App Banner meta lives in `tools/site/partials/head-common.html`.
The mobile `UpdateGate` falls back to the App Store page when `ios_update_url` is blank.

## Adding a new school
No second school is planned. Step-by-step plan: `docs/new-school-playbook.md` (replaced the removed
"Charlie" agent).

**Step 0 (per-school config) is built but parked on branch `per-school-config`, not merged.** It moves
every PSU convention onto one `School` object (`backend/schools/psu.py`) that the engine and routers
read via `schools.current()`; it was proven byte-identical for PSU by snapshotting 235 students'
responses before and after. Merge it when a second school is actually on the way — expect conflicts
in `audit_engine.py`, `routers/courses.py` and `routers/timeline.py` if those change first. Until
then, PSU values stay hardcoded on `main`.

## Adding a new requirement pair to the catalog
If two courses should be choose-one alternatives but aren't paired in the catalog, add them to
`KNOWN_ALTERNATIVE_GROUPS` in `seed_matthew.py` (pair IDs 800+), which is the generic catalog-wide
pass. Pairing courses that are both present needs nothing else; an **inserted** alternative also
needs a verdict — re-run `scripts/verify_alternative_inserts.py` (needs the local catalog + xlsx). ETI's old hand-written `PAIRS` list is gone — see the warning above.

**First check whether the bulletin actually says "or".** Two courses listed inside one
`Select N credits` pool are *not* alternatives that need pairing: the credit threshold already does
the enforcing, and re-typing them to `choose_one` makes each one individually required. That is how
the removed ETI patch turned a pick-one pool into four mandatory courses. `patch_known_alternatives()`
skips `choose_credits` pools for exactly this reason.
