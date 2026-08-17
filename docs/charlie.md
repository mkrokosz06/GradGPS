# Charlie — the "add my school" agent

Charlie is GradGPS's **school-demand funnel and onboarding scout**. It captures
requests for schools we don't support yet, tells the founder which school is
cheapest to add next, and drafts feasibility — but never adds a school
autonomously. Design rationale in the conversation that produced it; this doc is
the durable reference.

Related: [`docs/multi-school-copy.md`](multi-school-copy.md) (the copy/config layer
Charlie's onboarding output eventually feeds).

## Why not fully autonomous

"Type a school name → it goes live" optimizes for the wrong thing. GradGPS's
entire value is **audit accuracy**, and a half-automated school with subtle
errors is worse than no support. Adding a school is 5–6 heterogeneous,
per-school jobs, and the hard ones can't be done from a name alone:

- **Transcript parser** — every school runs a different SIS (Banner/Workday/
  PeopleSoft/LionPATH) with a different PDF layout. You physically cannot write a
  reliable parser without *sample transcript PDFs* from that school.
- **Catalog** — the scraper is bespoke to PSU's CourseLeaf HTML; another platform
  is a rewrite.
- **Gen-ed** — a different school's gen-ed is a different *ontology*, not a
  different list. Hand-modeled every time.
- Course content is, of course, 100% new per school — that's the *expected*,
  cheap part. The expensive part is the PSU conventions quietly baked into the
  supposedly-reusable machinery (code-suffix stripping, `SUBJ NNN` spacing,
  gen-ed taxonomy).

So Charlie's role is **demand capture + roadmap intelligence + drafting with a
human quality gate**, not automation of the judgment.

## The three tiers

### Tier 1 — Capture & normalize *(built)*
- Public `POST /charlie/request` takes free-typed school input (+ optional
  "notify me" email, + honeypot). No auth (same posture as the support form),
  in-memory rate limit.
- `charlie.normalize_school()` resolves aliases to one canonical school so
  "Penn State" / "Pennsylvania State University" / "PSU" all accumulate on one
  row. Exact match on a seed roster (incl. acronyms); fuzzy (difflib) only for
  longer strings so `osu`/`asu` can't collide; otherwise a provisional
  `unmatched-*` canonical flagged for human confirm. `penn` is deliberately
  ambiguous (matches neither Penn State nor UPenn).
- Votes accumulate atomically in the `school_requests` table (one row per
  canonical school).

### Tier 2 — Feasibility triage *(built)*
- Admin `POST /charlie/schools/{key}/triage?catalog_url=…` runs
  `charlie.run_triage()` and stores a **readiness report** structured around the
  three honest questions:
  1. **Can I get the data?** — fetches the catalog URL and sniffs the platform
     (`detect_catalog_platform`: CourseLeaf / Acalog / Kuali / Ellucian-Banner).
     CourseLeaf ⇒ scraper largely reusable; anything else ⇒ rewrite.
  2. **Course-code grammar risk** — will their code format break the parser's PSU
     assumptions (suffixes, spacing, numbering)? Surfaced as a review prompt.
  3. **Gen-ed ontology distance** — always "needs manual review"; there is no
     reliable automated signal.
  Plus supporting signals (SIS known?, professor-ratings coverage) and an overall
  green/yellow/red/unknown verdict. **Only Q1 is meaningfully automatable today**
  — the rest are explicit manual prompts, never guessed.

### Tier 3 — Automated build *(NOT built — design below)*
Supervised autonomy: the agent drafts and self-verifies an entire school, and a
human approves only the exceptions before it goes live in beta. Full pipeline in
**[Tier 3 — automated build](#tier-3--automated-build-design-not-built)** below.
Blocked on the `school_id` config layer (pulling PSU's conventions out of the
audit engine) — see [`docs/multi-school-copy.md`](multi-school-copy.md). Never
auto-publishes to "stable".

## Tier 3 — automated build (design, not built)

**Model: supervised autonomy — automate the work, gate the *trust*.** The build
runs itself; a human approves exceptions and the go-live, and correctness is
earned in stages behind a beta label rather than bet on an unverified guess.

**Why this is now feasible.** The old blocker was per-school bespoke scrapers and
transcript parsers. LLM extraction collapses that: an LLM reads an arbitrary
catalog page or transcript by *meaning*, not layout, so extraction is cheap and
general. That moves the bottleneck from extraction to **verification** — "how do
we know the automated build is correct without a human checking every row?" —
which is what most of this pipeline automates.

### Pipeline ( [auto] / [human] )

- **Trigger** — a school crosses a demand threshold on the dashboard, or you
  click **Start Build**. Demand-gated; never fires on a single request. **[human]**
- **A · Inputs** — Charlie has the catalog URL from triage. **No pre-sourced
  transcripts and no automatic emails** (see Communication below). The build
  proceeds on a **general LLM transcript extractor** — no school-specific parser
  required to launch. **[auto]**
- **B · Extract** — LLM extracts each major's requirements from the catalog; if
  the platform is known (CourseLeaf), the deterministic scraper runs too. LLM
  maps gen-ed categories onto the normalized model. **[auto]**
- **C · Reconcile** — diff the two independent extractions. Agreements
  auto-accept; disagreements → **exception queue**. Shrinks human review from
  "all requirements" to "only the conflicts". **[auto]**
- **D · Self-verify vs. ground truth** — run the school's *published* sample
  4-year plans through the audit engine; they **must** come out "graduates".
  Failures localize the bad requirement → exception queue. Plus structural checks
  (≈120-credit totals, valid prereq DAG, no orphans). **[auto]**
- **E · Confidence score** — composite of extraction agreement %, sample-plans
  reconciled, sanity checks passed. High → proceed to beta; low → route the whole
  school to a human. **[auto]**
- **F · Approve exceptions** — human reviews **only the flagged items**, sized to
  how messy the school was, not how big. **[human]**
- **G · Beta publish** — school goes live labeled *"new — verify with your
  advisor"*, features auto-gated off where data is missing (e.g. no professor
  ratings → tab hidden). **[auto]**
- **H · Validation loop** — real beta students validate on real transcripts; this
  is also where **transcript-format correctness and interpretation edge cases are
  caught** (transfer/AP/test credit, pass-fail, withdrawals, grade-replacement
  repeats, transcript↔catalog code alignment). Corrections feed back; error-rate
  spike auto-reverts / holds the beta label. **[auto + real users]**
- **I · Graduate to stable** — after the beta cohort runs clean, drop the beta
  label. **[human sign-off]**

### Transcript handling (tweak)
No school-specific transcript parser is a launch prerequisite. Launch on the
**general LLM extractor**; let beta students' real uploads validate the format;
**harden into a cheap deterministic parser only once volume justifies it** (saves
tokens/latency and keeps FERPA-sensitive data out of the LLM at scale). LLM
extractor = universal unblocker; deterministic parser = an earned optimization.

### Communication (tweak)
**Charlie never sends outbound email on its own.** All voter contact is a button
you press on the school's dashboard row, both via SES (same as the support form):
- **Request sample transcript** — emails opted-in voters asking for a sample.
  Optional; often unnecessary since beta uploads supply one naturally.
- **Notify voters** — emails opted-in voters that their school is live.

### Human touchpoints (the whole list)
Set the demand bar / Start Build · approve flagged exceptions · optionally press
*Request sample transcript* · press *Notify voters* · final go-live sign-off.
Everything between is automated.

### Dashboard additions this implies
Start Build action, exception queue + confidence score per school, beta/stable
status, and the two email buttons above.

## Surface

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `POST /charlie/request` | none | capture + normalize + `+1` vote |
| `GET /charlie/schools` | admin | demand ranking (votes desc) + rollup counts |
| `GET /charlie/schools/{key}` | admin | one record incl. last readiness report |
| `POST /charlie/schools/{key}/triage` | admin | run/refresh triage, store report |
| `GET /charlie/dashboard` | (local) | founder dashboard HTML |

Founder dashboard: **`/charlie/dashboard`** (`backend/static/charlie.html`) — demand
ranking, per-school triage button, readiness modal. Same "local tool" posture as
`/admin/` (admin data endpoints need dev-bypass or an `ADMIN_USER_IDS` id).

## Code map

| File | Role |
|------|------|
| `backend/charlie.py` | Core logic — `normalize_school`, `detect_catalog_platform`, `run_triage`. Pure/testable except the triage catalog fetch. |
| `backend/charlie_schools.json` | Seed roster (aliases → canonical, domains). Only PSU carries verified SIS/catalog/RMP fields; others null by design. |
| `backend/routers/charlie.py` | HTTP surface (public capture + admin triage/list). |
| `backend/static/charlie.html` | Founder dashboard. |
| `backend/tests/test_charlie.py` | Pure-logic tests (pytest or plain python). |
| `school_requests` DynamoDB table | PK `school_key`; votes/aliases_seen/notify_emails/readiness. Created by `scripts/setup_tables.py`. |

## Not done / next

- **Tier 1 front door on web + app** — the "Don't see your school? Tell us" input
  that POSTs to `/charlie/request`. Deliberately not built yet (no app work this
  pass).
- **Live DynamoDB smoke test** of the capture→dedup→triage round-trip (the
  `UpdateExpression` was validated at the serialization level only; Docker was
  unavailable). Run: `docker-compose up -d && python scripts/setup_tables.py`,
  then exercise `/charlie/request` and `/charlie/dashboard`.
- Optional: a real RMP *school*-search probe (currently ratings coverage is
  "known from seed / else manual").
- **Dashboard email buttons** — *Request sample transcript* and *Notify voters*
  (both SES, human-triggered; `notify_emails` set is already captured).
- **Tier 3 automated build** — designed above, blocked on the `school_id` config
  layer. Key pieces when unblocked: LLM catalog/transcript extractor, dual-extract
  reconcile + exception queue, published-plan reconciliation, confidence score,
  beta/stable rollout.
