# DegreeCheck

AI-powered college advising app that tells students exactly what courses they still need to graduate — no advisor appointment required.

Launching exclusively at **Penn State University Park**. Free to use. B2C.

---

## What It Does

1. Student signs in with Google or Apple
2. Uploads their unofficial PSU transcript (PDF)
3. Selects their major
4. Gets an instant audit: every requirement marked **Done**, **In Progress**, or **Missing**

---

## Project Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | PSU catalog scraper | Complete |
| 2 | Audit engine + FastAPI backend | In Progress |
| 3 | React Native mobile app | Upcoming |
| 4 | Deploy + App Store launch | Upcoming |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Mobile | React Native + Expo (iOS + Android) |
| Backend | Python + FastAPI |
| Database | AWS DynamoDB |
| File storage | AWS S3 (transcript PDFs) |
| Local dev | LocalStack (emulates DynamoDB + S3 locally via Docker) |
| Scraper | httpx + BeautifulSoup4 |
| Transcript parsing | pdfplumber |
| Hosting | Railway |
| Error tracking | Sentry |

---

## Repository Structure

```
/
├── scrape_psu.py                  # PSU catalog scraper
├── PSU_Major_Requirements.xlsx    # Scraped output — 31,734 rows, 551 programs
├── PSU_Major_Requirements.txt     # Plain-text version of the above
├── docker-compose.yml             # LocalStack (DynamoDB + S3 local emulation)
├── briefing.html                  # Business briefing document
├── implementation-plan.html       # Technical implementation plan
├── README.md
└── backend/
    ├── main.py                    # FastAPI app entry point
    ├── db.py                      # DynamoDB + S3 client (LocalStack in dev, real AWS in prod)
    ├── audit_engine.py            # Degree audit logic (all 4 group types)
    ├── transcript_parser.py       # pdfplumber PDF → course list
    ├── requirements.txt
    ├── .env.example
    ├── routers/
    │   ├── audit.py               # GET /audit
    │   ├── transcript.py          # POST /transcript/upload
    │   └── programs.py            # GET /programs/search, POST /programs/select
    └── scripts/
        ├── setup_tables.py        # Create DynamoDB tables + S3 bucket
        └── load_catalog.py        # Load Excel data into DynamoDB
```

---

## Phase 1 — Catalog Scraper (Complete)

Scrapes [bulletins.psu.edu](https://bulletins.psu.edu) for all undergraduate program requirements.

**Output:** `PSU_Major_Requirements.xlsx`

| Stat | Value |
|------|-------|
| Programs scraped | 551 (University Park only) |
| Requirement rows | 31,734 |
| Colleges covered | All PSU colleges |
| Scrape frequency | Weekly cron (planned) |

### Requirement Group Types

Every requirement row is classified into one of four types:

| Type | Rule |
|------|------|
| `required` | Student must complete every course listed |
| `choose_one` | Take any one course from an OR-alternative pair (linked by `pair_group_id`) |
| `choose_credits` | Take courses from the pool until N credit hours are reached |
| `choose_courses` | Take any N courses from the listed options |

### OR Alternative Pairs

Penn State lists alternatives as table rows where the first cell is "or":

```
BA 302    Business Law             3cr
or
SCM 301   Supply Chain Management  3cr
```

Both courses share a `pair_group_id` integer. The audit engine checks: *at least one course per pair must be completed.*

### Output Columns

```
program_name, college, degree, campus, requirement_group, group_type,
group_threshold, course_code, course_title, credits, min_grade,
pair_group_id, url
```

### Running the Scraper

```bash
pip install requests beautifulsoup4 lxml pandas openpyxl
python scrape_psu.py
```

Takes approximately 5 minutes. Output written to `PSU_Major_Requirements.xlsx` and `PSU_Major_Requirements.txt`.

---

## Phase 2 — Audit Engine + Backend (In Progress)

### Local Development Setup

```bash
# 1. Start LocalStack (emulates DynamoDB + S3 on localhost:4566)
docker compose up -d

# 2. Install backend dependencies
cd backend
pip install -r requirements.txt

# 3. Copy env file and configure
cp .env.example .env

# 4. Create DynamoDB tables + S3 bucket in LocalStack
python scripts/setup_tables.py

# 5. Load PSU catalog data into DynamoDB
python scripts/load_catalog.py

# 6. Start the API
uvicorn main:app --reload
```

### DynamoDB Tables

Three tables:</p>

**`requirements`** — loaded from the scraped Excel (31,734 rows)
- PK: `program_name` / SK: `group_course` (requirement_group#course_code)
- GSI on `course_code` for reverse lookup

**`users`** — one row per student, stores major selection and transcript S3 path

**`transcript_courses`** — parsed courses from the student's uploaded PDF
- PK: `user_id` / SK: `course_code`

### Transcript Parsing

Uses `pdfplumber` to extract courses from the unofficial PSU transcript PDF.

Handles:
- Completed courses (grade earned)
- In-progress courses (attempted > 0, earned = 0, no grade)
- Transfer credits (grade = "TR")

### Audit Logic

```
For each requirement group in the student's major:

  required:        each course must be in done/in_progress list
  choose_one:      group by pair_group_id — at least one per pair must be done/in_progress
  choose_credits:  sum credits of completed pool courses >= group_threshold
  choose_courses:  count of completed pool courses >= group_threshold
```

### API Endpoints (FastAPI)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/transcript/upload` | Accept PDF, parse, store to DB |
| GET | `/audit` | Return full audit for authenticated user |
| GET | `/programs/search` | Fuzzy search program names for major picker |

---

## Phase 3 — Mobile App (Upcoming)

React Native + Expo. Single codebase for iOS and Android.

### Screens

1. **Login** — Google SSO + Sign in with Apple (required by App Store when offering Google)
2. **Major Picker** — searchable list of 551 programs
3. **Transcript Upload** — `expo-document-picker` → PDF → backend
4. **Audit** — requirement groups with Done / In Progress / Missing status
5. **Course Detail** — credits, min grade, OR pair info

### Key Packages

```
@react-native-google-signin/google-signin
expo-apple-authentication
expo-document-picker
@supabase/supabase-js
@sentry/react-native
```

---

## Phase 4 — Deploy (Upcoming)

- **Backend:** Railway (Docker, cron job for weekly scraper)
- **iOS:** EAS Build → TestFlight → App Store
- **Android:** EAS Build → Google Play internal track → production

---

## Post-V1 Roadmap

- **Rate My Professor** — show professor ratings on each course card (unofficial GitHub API wrapper)
- **Semester planner** — drag remaining courses into future semesters, check prerequisite conflicts
- **Prerequisite chain warnings** — flag deep chains so students know what to take first
- **Multi-school** — expand scraper to other universities

---

## Data Source

Penn State Undergraduate Bulletin — [bulletins.psu.edu](https://bulletins.psu.edu)

- `/undergraduate/` and `/programs/` are permitted per robots.txt
- `/archive/` is blocked — V1 uses current catalog year only
- 0.35s delay between requests, 15s timeout, 3 retries

---

## Notes

- Transcript storage is **unofficial PDF only** — avoids FERPA complications
- Catalog accuracy is maintained via weekly re-scrape
- OR-alternative pairs are tracked with `pair_group_id` — a globally unique integer assigned at scrape time so the audit engine knows which courses are interchangeable without any hardcoding
