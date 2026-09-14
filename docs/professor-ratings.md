# Professor ratings — withdrawn September 2026

The course detail screen used to show RateMyProfessors ratings for each professor
teaching a course: quality, difficulty, would-take-again, sortable five ways,
preferring course-specific aggregates and falling back to the professor's overall
numbers only when the course had none. It was removed on 2026-09-14. This note
records why, so nobody (including a future me) wires it back up without knowing
what it costs, and how it worked, so it is rebuildable.

## Why it was removed

Three separate problems, any one of which was enough.

**1. Their Terms of Use prohibit all three things we were doing.** Rate My
Professors, LLC forbids using "manual or automated software, devices, scripts,
robots or other means or processes to access, 'scrape,' 'crawl' or 'spider' any
web pages"; forbids reproducing, creating derivative works from, or distributing
their Material without express prior written consent; and forbids use of the site
"for commercial or business purposes." `build_rmp_index.py` crawled their whole
Penn State roster, `rmp_professor_courses` stored a copy of it, and
`monthly_refresh.py` re-crawled on the 1st of every month. Governing law is New
York, with binding arbitration and a class-action waiver.

**2. The access pattern was worse than ordinary scraping.** The client sent a
spoofed Chrome User-Agent, faked `Referer`/`Origin` headers, and a hardcoded
`Authorization: Basic dGVzdDp0ZXN0` (base64 `test:test`) to a private GraphQL
endpoint. *hiQ v. LinkedIn* (after *Van Buren*) protects scraping **public** web
pages — that is the whole basis of the holding. A non-public API behind an auth
header is not that, and sending a credential we were never issued is the fact
pattern that turns a contract problem into a CFAA / DMCA §1201 argument.

**3. Apple App Review guideline 5.2.2.** "If your app uses, accesses, monetizes
access to, or displays content from a third-party service, ensure that you are
specifically permitted to do so under the service's terms of use. **Authorization
must be provided upon request.**" We had no authorization and could not have
obtained it on demand. This was a submission blocker, not a theoretical risk.

## Why we didn't just hide it behind a flag

Considered and rejected. App Review guideline 2.3.1(a): "Don't include any
hidden, **dormant**, or undocumented features in your app; your app's
functionality should be clear to end users and App Review." 2.3.1(b) escalates to
"grounds for removal from the Apple Developer Program."

It also wouldn't have worked. The Terms violation is the crawl and the stored
index, both server-side. Hiding the UI would have left us crawling their roster
monthly and storing their data with zero user benefit — strictly worse than
either keeping the feature or removing it.

## What "dormant in the repo" means here, and why it's fine

`backend/rmp_client.py` and `backend/scripts/build_rmp_index.py` are still in the
repo, carrying a banner saying they are dormant. Nothing imports them, nothing
schedules them, no endpoint mounts them, and none of their code ships in the
mobile binary. That is dead code in version control, which is not a hidden
feature — App Review reviews the binary, not git history. The distinction that
matters is intent: code kept for recoverability is fine; code shipped disabled
with a plan to enable it after approval is 2.3.1.

## What was removed

| Where | What |
|---|---|
| `backend/routers/courses.py` | `GET /{code}/professors`, `GET /{code}/professor`, `_enrich_professor`, the `rmp_client` import |
| `backend/scripts/monthly_refresh.py` | the `refresh_rmp()` step |
| `backend/scripts/setup_tables.py` | the `rmp_professor_courses` table |
| `mobile/services/courseService.ts` | `ProfessorRating`, `getProfessors`, `getProfessorByName` |
| `mobile/app/course/[code].tsx` | `ProfessorCard`, `RatingBar`, `Stars`, `SortPills`, `sortProfessors`, the name-search fallback, and all ratings state |
| Privacy policy §4, ToS §9, marketing copy | claims about a feature we no longer offer — 2.3.1 cuts both ways |

The `rmp_professor_courses` DynamoDB table still exists in prod and should be
deleted by hand; nothing reads or writes it.

The choose-one pair switcher (MATH 110 vs MATH 140) was **kept** and moved to the
top of the screen — it is still useful for comparing two courses' descriptions
and credits.

## How it was implemented

Recorded here because the UI code was deleted, not kept dormant — only the two
RMP client modules survive in the tree. Everything below is recoverable from
**`f30516a`**, the last commit before the removal:

```bash
git show f30516a:mobile/app/course/[code].tsx       > /tmp/old-course-screen.tsx
git show f30516a:backend/routers/courses.py         > /tmp/old-courses.py
git show f30516a:mobile/services/courseService.ts   > /tmp/old-courseService.ts
```

### The two endpoints

`GET /courses/{code}/professors` — the primary path. Looked up
`rmp_professor_courses` (PK `course_code`, SK `professor_id`) to find who had
ratings for the course, then enriched each hit concurrently with
`rmp_client.get_course_ratings(teacher_id, code)` for course-specific
aggregates. Returned `{professors: [...], schedule_found: bool}`.

`GET /courses/{code}/professor?name=…` — manual fallback when the index missed.
Live `rmp_client.search_professor()` by name at `PSU_SCHOOL_ID`, top 3 results
enriched via `_enrich_professor()`. Returned `{professors: [...]}`.

Both degraded rather than failing: if the per-course enrichment threw, the card
fell back to the overall aggregates already stored on the index row.

### The response shape

```ts
type ProfessorRating = {
  id: string; name: string; department: string | null;
  course_avg_rating: number | null;      // this course only
  course_avg_difficulty: number | null;
  course_would_take_again: number | null; // percentage 0-100
  course_num_ratings: number;
  overall_avg_rating: number | null;     // all courses, for context
  overall_avg_difficulty: number | null;
  overall_would_take_again: number | null;
  overall_num_ratings: number | null;
};
```

### The display rule (the part worth preserving)

The interesting design problem was that course-specific ratings are more
relevant but much sparser than overall ones. The resolution, in `ProfessorCard`:

| `course_num_ratings` | Value shown | Badge |
|---|---|---|
| `>= 3` | course-specific | blue — "14 ratings for MATH 140" |
| `1`–`2` | course-specific | amber — "Only 2 ratings for MATH 140" |
| `0` | falls back to overall | grey — "No ratings for MATH 140 — showing overall" |

So a course-specific number was always preferred when one existed, but the badge
told the student how much to trust it. When the course had >= 3 ratings, a
footer line also gave the overall for context: "Overall: 3.9 ★ across 214
ratings." **Never show a bare aggregate without its sample size** — that was the
whole point of the badge, and it is the rule to carry into any replacement.

### The screen

Below the course description, a "Professor Ratings" section:

- A horizontally scrolling row of sort pills — **Most Ratings** (default), Best
  Rating, Easiest, Hardest, Would Take Again. `sortProfessors()` used a
  `nullLast()` comparator so professors missing a metric sank to the bottom in
  both directions rather than sorting as zero; `most_ratings` tie-broke on
  rating descending.
- One card per professor: name, department, the trust badge, then a 36px rating
  numeral beside a ★-row and the label "Quality"; a "Difficulty" row with a 6px
  `RatingBar`; and "N% would take again", coloured green >= 70, amber >= 40, red
  below.
- Below the list, a persistent name-search input ("Don't see your professor?"),
  which replaced the auto-loaded results with search hits when used.
- Empty/error states each steered to that same search box: "Loading professors
  for MATH 140…", "Couldn't load professors. Search by name:", "No professors
  found for MATH 140. Search by name:".

The choose-one pair switcher (MATH 110 | MATH 140) lived at the top of this
section and reloaded ratings on toggle, so a student could compare the two
options in a choose-one slot. That switcher is the one piece **kept** — it moved
to the top of the screen and now swaps the course description instead.

## If you want it back

Get written permission from Rate My Professors, LLC first, and keep the email.
Without it, none of the three problems above have changed.

A cleaner replacement that needs no permission from anyone: source the teaching
roster from PSU's own public class search (`public.lionpath.psu.edu`, no login
required) and deep-link out to RMP per instructor. Linking to a public page has
never required permission. That version is also *more* accurate than what we had
— the old list was "professors who happen to have RMP ratings for this code,"
which is historical and includes people who have left, rather than "who is
actually teaching this next term."
