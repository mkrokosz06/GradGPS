# GradGPS

AI-powered degree advisor for Penn State students. Upload your transcript, pick your major, and get an instant audit of every requirement — done, in progress, or missing — plus a projected semester-by-semester timeline to graduation.

Launching exclusively at **Penn State University Park**. Free during beta. B2C.

---

## What It Does

1. Student signs up with name + PSU email
2. Uploads their unofficial PSU transcript (PDF)
3. Selects their major (and subplan if applicable)
4. Gets an instant audit: every requirement marked **Done**, **In Progress**, or **Missing**
5. Views a projected timeline showing which future semesters remaining courses fall in
6. Taps any course to see professor ratings (via RateMyProfessors)

---

## Project Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | PSU catalog scraper | Complete |
| 2 | Audit engine + FastAPI backend | Complete |
| 3 | React Native mobile app | Complete |
| 4 | Deploy + App Store launch | Upcoming |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Mobile | React Native 0.81 + Expo SDK 54 + Expo Router v3 |
| Styling | NativeWind v4 (Tailwind for React Native) |
| Backend | Python + FastAPI |
| Database | AWS DynamoDB (DynamoDB Local in dev) |
| File storage | AWS S3 / MinIO (MinIO in dev) |
| Local dev | Docker — DynamoDB Local (port 8000) + MinIO (port 9000) |
| Scraper | httpx + BeautifulSoup4 |
| Transcript parsing | pdfplumber |

---

## Repository Structure

```
/
├── docker-compose.yml             # DynamoDB Local + MinIO S3
├── README.md
├── CLAUDE.md                      # Full architecture + dev guide
├── backend/
│   ├── main.py                    # FastAPI app entry point
│   ├── audit_engine.py            # Degree audit + gen ed audit logic
│   ├── transcript_parser.py       # pdfplumber PDF → course list
│   ├── db.py                      # DynamoDB + S3 clients
│   ├── deps.py                    # Shared FastAPI dependency (user_id header)
│   ├── requirements.txt
│   ├── routers/
│   │   ├── audit.py               # GET /audit
│   │   ├── timeline.py            # GET /timeline
│   │   ├── transcript.py          # POST /transcript/upload
│   │   ├── programs.py            # GET /programs/search, POST /programs/select
│   │   ├── courses.py             # GET /courses/:code + professor ratings
│   │   ├── users.py               # User profile
│   │   └── admin.py               # Admin utilities
│   └── scripts/
│       ├── setup_tables.py        # Create DynamoDB tables + S3 bucket
│       ├── load_catalog.py        # Load 31k PSU requirement rows
│       ├── rebuild_gen_ed.py      # Load gen ed requirements (scraped bulletin data)
│       ├── seed_matthew.py        # Seed test user + transcript + catalog patches
│       └── scrape_psu.py          # Original bulletin scraper → PSU_Major_Requirements.xlsx
└── mobile/
    ├── app/
    │   ├── _layout.tsx            # Root Stack + AuthProvider
    │   ├── (tabs)/                # Main app screens (tab bar hidden)
    │   │   ├── index.tsx          # Timeline screen
    │   │   ├── account.tsx        # Account + audit summary
    │   │   ├── major.tsx          # Major + subplan selection
    │   │   └── upload.tsx         # Transcript upload
    │   ├── onboarding/            # Welcome → signup → major → upload flow
    │   ├── course/[code].tsx      # Course detail + professor ratings
    │   ├── tos.tsx                # Terms of Service
    │   └── privacy.tsx            # Privacy Policy
    ├── components/
    │   └── NavHeader.tsx          # Top bar + hamburger side-menu
    ├── context/
    │   └── AuthContext.tsx        # Auth state + AsyncStorage
    ├── services/                  # Typed API wrappers (axios)
    └── constants/
        └── api.ts                 # API_BASE + dev USER_ID
```

---

## Local Development

### Prerequisites
- Docker Desktop
- Python 3.11+
- Node.js 20+
- Expo Go on your phone (or iOS/Android simulator)

### 1. Start infrastructure
```bash
docker-compose up -d   # DynamoDB Local (port 8000) + MinIO S3 (port 9000)
```

### 2. Seed the database
Data is in-memory — run these after every Docker restart:
```bash
cd backend
python scripts/setup_tables.py    # create tables/buckets
python scripts/load_catalog.py    # load 31k PSU requirement rows (~2 min)
python scripts/rebuild_gen_ed.py  # load gen ed requirements from scraped bulletin data
python scripts/seed_matthew.py    # seed test user + transcript
```

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

## DynamoDB Tables

| Table | PK | SK | Contents |
|-------|----|----|---------|
| `requirements` | `program_name` | `group_course` | All PSU major + gen ed requirements |
| `users` | `user_id` | — | User profile (major, subplan, timestamps) |
| `transcript_courses` | `user_id` | `course_code` | Parsed transcript courses |

Gen ed requirements are stored under `program_name = "__GEN_ED__"`.

---

## Audit Logic

```
For each requirement group in the student's major:

  required:        each course must be in done/in_progress list
  choose_one:      group by pair_group_id — at least one per pair must be done/in_progress
  choose_credits:  sum credits of completed pool courses >= group_threshold
  choose_courses:  count of completed pool courses >= group_threshold
```

---

## Authentication

Real sign-in via Google/Apple OIDC — ID tokens are verified in `backend/auth.py`
(JWKS signature, audience, issuer, expiry) and the canonical `user_id` is the
provider-scoped subject (`google:<sub>` / `apple:<sub>`). In dev,
`AUTH_DEV_BYPASS=1` in `backend/.env` accepts the legacy `x-user-id` header
(how Expo Go works with the test user). Never set the bypass in prod.
See CLAUDE.md § Auth for details.

## Official Transcripts

Students sometimes upload their **official** transcript instead of the
unofficial LionPATH one. The backend detects these (`official_detector.py`),
parses them with a dedicated parser, and gates storage behind a consent dialog
(409 + `acknowledge_official` re-submit). See
[`docs/official-transcript-handling.md`](docs/official-transcript-handling.md).

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/transcript/upload` | Accept PDF, parse, store to DB |
| GET | `/audit` | Full degree audit for user |
| GET | `/timeline` | Semester-by-semester projection |
| GET | `/programs/search` | Fuzzy search program names |
| POST | `/programs/select` | Save major + subplan selection |
| GET | `/courses/:code` | Course detail (title, credits, description) |
| GET | `/courses/:code/professors` | Auto-detect professors + RMP ratings |
| GET | `/users/me` | User profile |

---

## Test User

| Field | Value |
|-------|-------|
| user_id | `matthew-test-001` |
| major | Enterprise Technology Integration, B.S. |
| transcript | Real PSU unofficial transcript, 26 courses |

---

## Roadmap

- **Session refresh** — ID tokens expire after ~1 h; add a refresh/session mechanism
- **Deploy** — AWS backend + EAS Build for App Store / Google Play
- **Multi-school** — expand scraper and parser to other universities
- **Prerequisite warnings** — flag deep chains so students know what to take first

---

## Data Source

Penn State Undergraduate Bulletin — [bulletins.psu.edu](https://bulletins.psu.edu)

- `/undergraduate/` and `/programs/` permitted per robots.txt
- 0.35s delay between requests, 15s timeout, 3 retries
- Catalog accuracy maintained via periodic re-scrape
