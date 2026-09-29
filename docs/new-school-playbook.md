# Adding a new school — playbook

Status: **Step 0 built and parked on branch `per-school-config` (not merged, 2026-09-29); no second
school planned.** Replaces the old "Charlie" add-my-school agent,
which was removed because its feasibility triage predated almost everything Penn State taught
us about where catalog data goes wrong.

The rule that runs through every step: **the school's own published data is the source of
truth, and no extraction is trusted until something independent agrees with it.** Every
serious PSU bug was an extraction that looked fine and was never checked against a second
source. Most of them told students they owed *less* than they did.

---

## Step 0 — Pull Penn State out of the engine (one-time, blocks everything)

> **Built, not merged.** Branch `per-school-config` has it: every coupling below lives on a
> `School` object in `backend/schools/psu.py`, read via `schools.current()` (defaults to PSU), with
> a per-request hook that is a no-op while PSU is the only school. Proven byte-identical for PSU
> (235 students' audit/timeline/class-picker responses snapshotted before and after). The branch's
> own copy of this doc describes it in full. Kept off `main` by choice until a second school is real.

A second school cannot run until PSU conventions stop being hardcoded. Known couplings:

| Coupling | Where |
|---|---|
| Course-suffix rules (W/H/N stripped, W/M/X/Y = writing-intensive) | `audit_engine.py`, `transcript_parser.py`, `routers/transcript.py` |
| Gen-ed model (`__GEN_ED__`, GA/GN/GH/GS/GHW/GQ/US/IL, WAC rule) | `audit_engine.run_gen_ed_audit()`, `rebuild_gen_ed.py` |
| Built-in equivalences (IST→ETI, first-year-seminar family) | `_EQUIVALENCE_PAIRS` in `audit_engine.py` |
| World-language depts | `_WORLD_LANGUAGE_DEPTS` in `sap_schedule.py` |
| University Park scoping | `is_up_program()` + `program_data/non_up_programs.json` |
| Transcript layout (LionPATH unofficial + official) | `transcript_parser.py`, `official_detector.py` |
| Catalog patches (PHYS 211/250, known alternatives) | `seed_matthew.py`, `apply_catalog_patches.py` |
| User-facing copy ("Penn State", "LionPATH") | see `docs/multi-school-copy.md` |

Deliverable: a `school_id` on the user row and per-school config, defaulting to `psu`, with PSU
behavior **byte-identical** — proven the same way the compound-branch change was, by running
the existing suite plus a characterization test against a frozen copy of today's output.

## Step 1 — Triage: can this school be done at all?

Check the school publishes, in a form we can read:

- [ ] a **course catalog** with titles and credits for every course
- [ ] **major requirements** per program
- [ ] **sample 4-year plans** (the ground truth for Step 6 — a school without them is much harder)
- [ ] **gen-ed / core curriculum** rules and course lists
- [ ] **entrance / admission-to-major** rules, if the school has them
- [ ] a **campus / location** marker for each program (branch-campus leakage cost PSU 41 bogus majors)
- [ ] **cross-listings**
- [ ] its catalog platform (CourseLeaf, Acalog, Coursedog, custom) — CourseLeaf reuses our scrapers
- [ ] the catalog site's terms of use and robots.txt — **read before scraping** (lesson from the
      RateMyProfessors withdrawal, `docs/professor-ratings.md`)

A school missing the catalog or the major requirements stops here.

## Step 2 — Course list first

Scrape every course's code, title, and credits into a per-school `bulletin_courses.json`
equivalent. Everything later checks against it: combo members take credits from it, pools are
credit-checked against it, and "courses" that are really instructions ("select 3 credits of
400-level") are caught because they don't exist in it.

Read title and credits from **separate fields** where the page has them — parsing one text blob
mangled 31% of PSU titles.

## Step 3 — Major requirements, extracted twice

Extract each program two independent ways (a deterministic scraper where the platform allows,
plus an LLM read of the same page) and diff them. Agreements pass; disagreements go to a human.
At PSU a second, independently written parser found six of the seven pool bugs and a regression
the fix itself introduced.

Check every program's parsed credit total against the school's own published total, and keep a
`--report` that reprints the match rate — a page edit that breaks a parse should show up as a
lower number, not a wrong plan.

## Step 4 — Run the known-traps checklist

Every one of these happened at PSU. Check each against the new school's pages:

- [ ] **Several pools in one section** — each "Select N credits from" is its own pool (`pool_seq`); merging them under-requires
- [ ] **"or" inside a pool** — options, not a standalone `choose_one`; lifting them out over-requires
- [ ] **Compound choices** — "A or (B and C)" needs `pair_branch_id`; half a branch satisfies nothing
- [ ] **Lecture + lab / "A & B"** in one cell — read every code, not the first
- [ ] **Short or hyphenated codes** (`ENGL 15`, `A-I 100`) — don't assume a 3-digit, letters-only format
- [ ] **Pool headers with filler words** ("Select 9 *additional* credits")
- [ ] **Standalone instructions** mistaken for pool headers
- [ ] **Two terms in one plan-grid row** — capture both courses
- [ ] **Cross-listed slash cells** (`EE 471/AERSP 490`) — one course, not three
- [ ] **Subplan/option pages** repeating shared requirements
- [ ] **Branch-campus programs** leaking into the major picker
- [ ] **Renamed courses** (old code on transcripts, new code in catalog) → equivalences
- [ ] **Unverifiable rules** (adviser-approved lists, portfolios, GPA ranges) → `needs_confirmation`, never auto-satisfied

## Step 5 — Gen eds, minors, entrance rules

- Map the school's gen-ed categories onto the engine's model (Step 0 makes this config).
  Scrape the course lists; never hand-author them (PSU's hand-written lists had invented titles).
- Minors/certificates via the `credential_catalog` pattern — bundled JSON, verified against
  published totals.
- Entrance rules via the `entrance_parse` pattern — anchor on the page's container, not the
  heading wording, and never report a gate cleared that we can't check.

## Step 6 — Self-verify against the sample plans

Extract each program's sample 4-year plan into an SAP template (must pass `validate_template()`,
≈120 credits). Then treat each template as a fake transcript and run it through the audit: **every
published plan must come out "graduates."** A failure points at the bad requirement row. Plans
are the only independent ground truth the school publishes, so this is the gate that matters
most.

## Step 7 — Transcripts

Start on a general LLM transcript extractor. Validate it on real beta uploads for AP/test credit,
transfer credit, repeats, withdrawals, pass/fail, and official-vs-unofficial layouts (all bit PSU).
Build a deterministic parser only once volume justifies it — it's cheaper and keeps FERPA data out
of the LLM.

## Step 8 — Beta launch

- Label the school *"new — verify with your adviser"*.
- Hide features with no data behind them (e.g. no sample plans → Layer 1 packer only).
- Keep a list of test students with known-correct outcomes per school, like `matthew-test-001`.

## Step 9 — Keep it fresh

Monthly rescrape (the `monthly_refresh.py` pattern). Alert when the credit-total match rate or
the plan-reconciliation rate drops. **A reload must re-run the school's patch scripts in the same
pass**, or injected alternatives vanish.

---

## Human checkpoints

Triage go/no-go · terms-of-use check · disagreements from Steps 3 and 6 · beta launch · dropping
the beta label. Everything else should be scripted.
