# GradGPS

A degree-planning app for Penn State students. Upload your transcript (or enter your classes), pick your
major, and get an audit of every requirement — done, in progress, or missing — plus a semester-by-semester
plan to graduation that respects prerequisites and PSU's own suggested academic plans.

**Live on the App Store** — [GradGPS for iOS](https://apps.apple.com/app/id6803643612) ·
[gradgps.com](https://gradgps.com) · Free for Penn State University Park students.

---

## What it does

- **Degree audit** — every major, gen-ed, and Writing Across the Curriculum requirement checked against
  the student's transcript, including choose-one alternatives, credit pools, and compound branches
  ("ACCTG 211 *or* (ACCTG 201 *and* ACCTG 202)").
- **Graduation timeline** — follows PSU's published Suggested Academic Plan for ~180 majors (and their
  options), reflowed around what the student has already taken; falls back to a credit-balanced planner
  for every other major. Prerequisites and corequisites are enforced.
- **Entrance to Major** — tracks gated majors' course, grade, and GPA requirements and holds major-only
  courses until the student is in.
- **Minors & certificates** — 200+ University Park credentials audited and merged into the plan.
- **Transcript parsing** — unofficial LionPATH PDFs, official (signed, two-column, watermarked)
  transcripts, AP/transfer credit, and honors courses. Students without a transcript can walk their
  major's plan and confirm what they've taken instead.
- **Plan editing** — swap in-progress classes, pick courses for elective/gen-ed slots, move a course to
  another semester, and declare adviser-approved substitutions.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Mobile | React Native + Expo SDK 54, Expo Router, NativeWind (Tailwind) |
| Backend | Python, FastAPI |
| Data | AWS DynamoDB, S3 |
| Hosting | AWS App Runner (container via ECR), GitHub Actions CI/CD with OIDC (no stored keys) |
| Scheduled jobs | EventBridge Scheduler → ECS Fargate (monthly catalog refresh) |
| Auth | Sign in with Apple, Google OIDC, email one-time codes; server-side sessions |
| Data pipeline | httpx + BeautifulSoup scrapers over the PSU Undergraduate Bulletin |
| PDF parsing | pdfplumber |
| Website | Static site on GitHub Pages, generated per-major SEO pages |

## How the data is built

Requirements come from the [Penn State Undergraduate Bulletin](https://bulletins.psu.edu) — ~31k
requirement rows across every program, plus course titles/credits, prerequisites, suggested academic
plans, and Entrance to Major rules. The scrapers parse the bulletin's HTML structure deterministically
(no LLM extraction), and every parse is checked by an independent verifier or against PSU's own published
credit totals before it ships — e.g. 206 of 207 minors/certificates match PSU's stated totals exactly.

## Repository layout

```
backend/            FastAPI app
  audit_engine.py     degree + gen-ed audit
  transcript_parser.py, official_detector.py
  sap_schedule.py, plan_templates.py   suggested-academic-plan matching
  routers/            audit, timeline, transcript, programs, courses, users, ...
  scripts/            scrapers, catalog loaders, maintenance jobs
  sap_templates/      suggested academic plans (JSON)
  tests/              pytest suite
credentials/        minor/certificate scraper + parser
mobile/             Expo app (screens in app/, API wrappers in services/)
website/            gradgps.com
docs/               design docs
```

## Local development

Requires Docker, Python 3.12, Node 20+.

```bash
docker-compose up -d                  # DynamoDB Local + MinIO (S3)

cd backend
python scripts/setup_tables.py        # tables + bucket
python scripts/load_catalog.py        # PSU requirements (~2 min)
python scripts/rebuild_gen_ed.py      # gen-ed requirements
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload

cd ../mobile
npx expo start
```

Run the tests with `cd backend && python -m pytest tests`.

## Docs

- [`docs/timeline-sap-hybrid.md`](docs/timeline-sap-hybrid.md) — how the timeline uses PSU's suggested plans
- [`docs/minors-certificates.md`](docs/minors-certificates.md) — minors & certificates
- [`docs/official-transcript-handling.md`](docs/official-transcript-handling.md) — official transcript detection and parsing
- [`CLAUDE.md`](CLAUDE.md) — full architecture notes

---

GradGPS is an independent project and is not affiliated with or endorsed by The Pennsylvania State University.
