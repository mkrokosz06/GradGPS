# Timeline SAP Hybrid — Design & Implementation Plan

**Status:** Layer 1 (credit-band packing) live for all majors. Layer 2 (SAP hybrid) live
for **180 UP majors** — 87% of the 208 UP bachelor-degree programs — via templates
scraped from the bulletin, with match + reflow wired into `get_timeline`,
template-presence gated, and the Layer 1 packer as fallback for the rest. Phases 0-4c
done (incl. single-column grid support). Remaining tail: 1 SAP page that doesn't fit
(Premedical-Medical, a 96cr accelerated program) + ~27 bachelor's with no published SAP.
**Scope:** University Park (main campus) majors only
**Owner file:** `backend/routers/timeline.py` (audit engine untouched)

---

## 1. Problem

When a student has a major selected but a thin transcript (or none), the generated
timeline collapses in its back half: **spring of junior year and all of senior year
show only "Free Electives"** with no concrete course suggestions.

Two root causes, in order of impact:

1. **The catalog runs out of named courses.** A major like Accounting only exposes
   ~18 individually-named required courses. Once those are placed (~semester 5), the
   remaining degree credits are large `choose_credits` / `choose_courses` pools and
   free-elective padding — none of which carry a specific course.
2. **The packer mishandles pools.** Missing pools are:
   - emitted as **one synthetic entry** carrying their full credit weight
     (`_collect_missing`, lines 184-240 — e.g. a single 34-credit "Free Electives" blob),
   - appended **last** by `_sort_and_spread` (line 332, `result.extend(pools)`), and
   - packed by a **slot count**, not credits, where an oversized pool that lands first
     in a semester chunk (`slots_used == 0`) bypasses the overflow guard
     (packing loop, lines 591-598) and gets dumped whole.

The result is unbalanced semesters (some ~34 cr, some empty) and a back half that is
all filler.

A secondary correctness issue: the packer counts **slots** (≈ `round(credits/3)`),
so **1.5-credit courses** are mis-weighted — each burns a full 3-credit slot.

---

## 2. Goals

- Every projected semester lands in a realistic **~15-credit band** (14-17 cr).
- The back half shows a believable **mix** of real courses + typed placeholders,
  not a wall of "Free Electives."
- Course **ordering respects prerequisites** where we know them.
- Handle **1.5-credit** courses by real credit, not slot count.
- Degrade gracefully: any major we haven't templated still produces a sane plan.

---

## 3. Two layers

The work splits into two independent layers. **Layer 1 is a prerequisite and stands
on its own** — it fixes the reported bug for *every* major with no new data. **Layer 2**
adds a Penn State Suggested Academic Plan (SAP) backbone on top for sequencing and
completeness.

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 2 — SAP hybrid  (adds order + completeness)            │
│   plan_templates table → match vs audit → reflow             │
│              │ falls back to ▼ when no template exists       │
├─────────────────────────────────────────────────────────────┤
│ Layer 1 — Scheduling fix  (fixes the bug, no new data)       │
│   expand pools → pack by credit band → interleave            │
├─────────────────────────────────────────────────────────────┤
│ audit_engine.py  — UNCHANGED, source of truth for "satisfied"│
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Layer 1 — Scheduling fix (`timeline.py`, no new data)

Three touch points. All self-contained inside `timeline.py`.

### 4.1 Expand pools into placeholder slots — `_collect_missing` + new `_expand_pool`

Today a `choose_credits` pool emits one entry with `pool_needed_credits` = full
remaining credits (lines 196-215). Change: split each pool into **3-credit
placeholder slots**, each an independent, schedulable item tagged with a shared pool
id so we know they're fungible and can render a dropdown.

- A 12-credit World Language requirement → **4** slots of 3 cr, not 1 of 12.
- A 34-credit Free Electives pad → **~11** slots, not 1.
- Preserve `pool_courses` (the ≤15-option dropdown list) on each slot so the mobile UI
  is unchanged.
- Free-elective padding (lines 551-559) emits slots the same way.

New helper `_expand_pool(entry) -> list[dict]` owns this; `_collect_missing` and the
padding block both call it. A trailing remainder < 3 cr becomes one smaller slot.

### 4.2 Pack by real credits, not slot count — packing loop (lines 569-608)

Replace the `COURSES_PER_SEM = 5` slot logic and `_item_slots` (lines 486-492) with a
**credit band**:

- Target **~15 cr/semester**, accept **14-17**.
- Sum actual `credits` per item (so two 1.5-cr courses pack as one 3-cr line).
- Because every item is now ≤ 3-4 cr after §4.1, the `slots_used == 0` overflow-bypass
  bug (line 594) disappears — no single item can blow past the band.
- `_display_credits` (lines 494-498) simplifies to "sum real credits" — no more
  `3.0 * pool_needed_courses` estimation.

Keep the gen-ed cadence cap (≤ 2 gen eds/sem, line 577) but express it in credits.

### 4.3 Interleave placeholders across the plan — `_sort_and_spread` (lines 291-333)

Replace `result.extend(pools)` (line 332) — which dumps all pools at the very end — with
an **interleave**: distribute placeholder slots across all ~8 semesters so each gets a
realistic mix (a couple named courses + an elective or two). Named-course ordering
(level tier → round-robin by subject, lines 315-331) is preserved; only pool placement
changes.

**Net effect of Layer 1 alone:** no more empty back half. Semesters balance to the
credit band, placeholders spread out, 1.5-cr courses handled. Still greedy — it does
not know prerequisite *sequence*. That is Layer 2.

---

## 5. Layer 2 — SAP hybrid (adds sequencing + completeness)

### 5.1 New data: `plan_templates` table

One template per UP major, scraped from the bulletin SAP.

| PK | SK | Contents |
|----|----|----------|
| `program_name` | `catalog_year#subplan` | Ordered 8-semester plan; each slot typed |

Each semester slot is one of:

- `fixed_course` — a specific course, e.g. `ACCTG 211`.
- `requirement_pool` — a bucket, e.g. "Business Breadth, 3 cr", linked to the audit
  group it satisfies.
- `gen_ed` — a gen-ed category + credits, e.g. "GH, 3 cr".

The template is the **backbone** (order + completeness + credit balance). It is **not**
the source of truth for what a given student still needs — that stays the audit engine.

### 5.2 Matching pass — new `_match_template(template, audit_result, gen_ed_result)`

Walk the template in order. For each slot, ask the **audit engine** (unchanged) whether
it's already satisfied for this student:

- **Satisfied** → mark done; it renders in its historical semester.
- **Unsatisfied `fixed_course`** → schedule it in the template's semester.
- **`requirement_pool` / `gen_ed`** → fill with a concrete option from the audit's
  missing list if one exists; otherwise keep it as a **typed placeholder** (reusing
  Layer 1's `_expand_pool` machinery).

Output: an ordered list of scheduled + placeholder items with a *desired* semester
index from the template.

### 5.3 Reflow — new `_reflow(matched_items, current_term)`

A real student rarely matches the template exactly (transfer credits, off-sequence
courses, a retake). After matching, **reflow**:

- Push everything unsatisfied forward starting from the student's current term,
  preserving the template's relative order.
- Rebalance to the ~15-cr band using the **Layer 1 packer** (§4.2).

The template decides *what and in what order*; the Layer 1 packer decides *actual
placement given this student's real state*. This is the "hybrid."

### 5.4 Fallback

`get_timeline()` becomes:

```
template = load_template(program_name, catalog_year, subplan)
if template:
    items = _reflow(_match_template(template, audit, gen_ed), current_term)
else:
    items = _sort_and_spread(_collect_missing(audit))   # Layer 1 path
```

Any major without a template runs the pure Layer 1 packer. The engine always produces
something; templates just make it better where they exist.

### 5.5 What does NOT change

- **`audit_engine.py`** — untouched. Still the single source of truth for
  done / in-progress / missing. The timeline only *consumes* its output.
- **Mobile-facing schema** (`_emit_semester`, lines 500-522) — placeholders already
  carry `is_pool` / `pool_needed_credits` / `pool_courses`, so the client renders
  unchanged.
- **Gen-ed audit** — still separate (`run_gen_ed_audit`, lines 447-475), still feeds
  typed slots.

---

## 6. UP-only scoping (shared prerequisite)

The SAP set must equal the app's existing "what's a UP major" definition, or the
scraper and the catalog will mismatch and matching breaks. Two notes from the catalog
scan (551 distinct programs; 487 pass the current filter; kept parentheticals are all
UP colleges):

- **Harden the filter (done — but NOT the way first planned).** A parenthetical scan of
  the catalog corrected the earlier assumption: only **123 of 551** programs carry any
  parenthetical, and **428 have none**. The parenthetical exists *only* to disambiguate
  a program offered at more than one campus. So a positive "allowlist of UP colleges"
  would wrongly **drop all 428 unqualified UP programs** — the denylist structure is
  correct. The fix was to keep the denylist but make the campus list **exhaustive** (all
  ~20 Commonwealth/branch campuses + aliases, not just the two — Capital, University
  College — actually present), so a future re-scrape can't leak a campus. Zero behavior
  change today (487 kept before and after); pure future-proofing. Implemented as
  `is_up_program()` in `programs.py`, with `_UP_COLLEGE_QUALIFIERS` as the authoritative
  UP-college list the SAP scraper validates college paths against. Tests:
  `backend/tests/test_programs_scope.py`.
- **Templates target majors, not all 487 programs.** The 487 is inflated by
  minors/certificates (no SAP). SAP-bearing degree majors ≈ **160-250** counting BA/BS
  and named options separately. Filter to bachelor's `degree` values.

One authoritative UP-scope definition (`is_up_program`), shared by the scraper and
`programs.py`.

---

## 7. Phased implementation plan

Each phase is independently shippable and leaves the app in a working state.

### Phase 0 — Guardrails ✅ DONE
- Hermetic packing tests in `backend/tests/test_timeline_packing.py` (17 tests, run
  under pytest or plain `python`) lock pool-expansion, even-slicing, credit-band, and
  internship behavior — the regression guard for all later phases.
- Baseline captured empirically via the real `get_timeline` code path (Accounting,
  no transcript): back half was **6 / 34 / 3 cr** with a 31-cr Free-Electives blob.

### Phase 1 — Layer 1 scheduling fix ✅ DONE
1. ✅ `_expand_pool()` splits every requirement pool + the free-elective pad into
   ~3-cr placeholder slots (§4.1); per-slot relabel so cards don't repeat the whole-
   pool credit figure.
2. ✅ `_build_future_semesters()` replaces the slot packer with a credit-band packer;
   `_item_slots` / `COURSES_PER_SEM` retired, `_display_credits` reads real credits (§4.2).
3. ✅ `_sort_and_spread` → `_sort_named`; named courses spread across the whole plan via
   `_slice_even`, gen-ed/pool fillers interleaved and gen-ed capped per semester (§4.3).
4. ✅ Dynamic per-semester target (`total / n_sems`) evens out the tail.

**Result (Accounting, no transcript):** back half went from **6 / 34 / 3** to a clean
**16 15 16 15 15 15 15 13**, total exactly 120 cr, named courses (incl. ACCTG 471/472)
present in the final semester. Verified no regression on the real ETI test user and
across Psychology / Mechanical Engineering / English / Kinesiology (1.5-cr courses
correctly yield 15.5 / 12.5-cr semesters). Official-detector suite still green.

> **Surfaced, out of Layer 1 scope:** majors with **no subplan selected** (e.g.
> Psychology 221 cr, Kinesiology 142 cr) pull *every* option track in as required, so
> the plan runs well past 120 cr / 8 semesters. Pre-existing audit/catalog behavior,
> not introduced here — worth narrowing when a subplan is chosen.

### Phase 2 — UP scope hardening ✅ DONE
1. ✅ Data check reversed the plan: an allowlist would drop 428 unqualified UP programs,
   so kept the denylist and made the campus list **exhaustive** (§6).
2. ✅ `is_up_program()` in `programs.py` is the single shared UP-scope predicate; the SAP
   scraper will import it. `_UP_COLLEGE_QUALIFIERS` documents the authoritative UP-college
   set for scraper path validation.
3. ✅ Verified 487 kept before and after (no leaks, nothing UP wrongly dropped). Tests in
   `backend/tests/test_programs_scope.py` (5 tests, incl. campuses not in the catalog).

> **Still TODO for Phase 3:** the "SAP-eligible majors" view (filter the 487 to bachelor's
> `degree` values, excluding minors/certificates) — deferred to where the scraper needs it.

### Phase 3 — Accounting proof-of-concept ✅ DONE
1. ✅ Accounting SAP hand-encoded as a template (3a) — deferred the general scraper to
   Phase 4; the match/reflow *engine* was the real risk, not scraping.
2. ✅ `match_template` (`sap_schedule.py`, 3b) + `_reflow_template` (`timeline.py`, 3c),
   wired into `get_timeline` with the Layer 1 fallback (§5.4).
3. ✅ Validated against the official SAP: no-transcript Accounting reproduces the
   published plan **exactly** (PSU 6, World Language 12cr, Business Breadth 6cr, the
   2cr elective, ETM ordering, gen-ed distribution — all present, all in order,
   totalling 120). A partial student's finished courses drop and the light Year-1
   remnants merge forward into a balanced, shifted plan.

**No feature flag (per decision):** the SAP path activates purely on template
*presence*. Only Accounting has a template, so only Accounting changes; every other
major runs the unchanged Layer 1 packer (verified byte-identical on the ETI test user).

**Reflow design:** preserve the template's prerequisite-valid semester groupings, drop
satisfied slots, then **merge-forward only light fragments** (< `_MERGE_MIN` = 10 cr) a
partial student leaves behind. An on-track student's semesters are all full → nothing
merges → the official plan is reproduced exactly.

> **Deferred (not blocking):** the ECON 102/104 mis-pairing noted earlier is a
> Layer 1 / catalog issue and doesn't affect the SAP path (the template pins ECON 102
> and ECON 104 as separate courses in their correct semesters).

**Exit criteria met:** Accounting hybrid matches the official SAP structure; an
off-sequence student reflows to a valid, balanced plan. Tests: reflow cases in
`test_timeline_packing.py`, match cases in `test_sap_schedule.py`.

### Phase 4a — Scraper + validation gate ✅ DONE
1. ✅ `scripts/scrape_sap.py` — a **deterministic** parser of the bulletin's CourseLeaf
   `table.sc_plangrid` (NOT an LLM extraction, which mis-split credits). Each `<td>`'s
   `header` attribute pins its exact year/term, so placement is exact. Classifies
   courses / choose_one (merging linked + plain-text codes) / gen-ed (`(N)`→GN) /
   world-language / business-breadth / departmental-elective / free-elective pools.
2. ✅ Validation gate before write: structure, grand-total credits, and opt-in catalog
   cross-check of pinned courses. A bad scrape never goes live.
3. ✅ Proven on three programs: **Accounting** + **Marketing** pass and are written (both
   now live); **Psychology** correctly rejected (pins `LA 83`, absent from catalog).
   The deterministic parse also **corrected** the hand-encoded Accounting template
   (ECON 102 → Y1 Fall, the bulletin's real 15/14 split).

**Parser findings that generalize:** codes can be plain text, links, or shorthand
(`30H` = ENGL 30H) — merge all sources; `NXX` wildcards (`MKTG 4XX`) mark elective
pools; bulletin dashes/nbsp need normalizing. Tests: `test_scrape_sap.py`.

### Phase 4b — Scale to the UP major set ✅ DONE
1. ✅ `scrape_sap.py --all` discovers every UP program page from the bulletin **sitemap**
   (branch campuses excluded via the college-path allowlist), scrapes those with a plan
   grid, and matches each to its exact catalog `program_name` via the **page title**
   (which carries the college parenthetical, so the only 3-way collision — Data Sciences —
   self-disambiguates). Name matching was **100%** (0 unmatched).
2. ✅ **178 majors templated and live** — 85% of the 208 UP bachelor-degree programs. All
   178 resolve to real catalog majors, 0 duplicates.
3. ✅ The bulk pass drove four parser/gate fixes (header-exact credit pairing; no
   0-credit slots; fraction-based catalog check so language/area-studies majors aren't
   falsely rejected; sanity gate skips associate degrees, allows 5-year 170cr degrees).

**Coverage math (actual):** 459 UP program pages → 278 no SAP grid (minors/certs/info) →
181 SAP-bearing bachelor's pages → **178 pass the gate**, 3 tail cases fall back to Layer 1
(2 single-column grid variants, 1 accelerated 96cr program). The template-presence gate
means every non-templated major keeps its exact Layer 1 behavior.

> **Re-running:** `python scripts/scrape_sap.py --all --dry-run` (parse + validate, no
> write) then drop `--dry-run` to write. Pages cache under `scripts/.sap_cache/`. A new
> catalog year is a re-scrape; the gate re-flags anything that drifts.

### Phase 4c — Remaining polish
1. ✅ Single-column CourseLeaf grid variant (`yearN undefinedcodecol`) — parser detects it
   and splits each year's ~30cr course list into two ~15cr Fall/Spring semesters.
   Recovered Energy and Sustainability Policy (B.A. + B.S.).
2. Options/subplans that have their own distinct SAP pages (currently one template per
   base major; subplan-specific plans would key on `subplan`). *(open)*
3. Engineering ETM-gate / tiered-technical-elective annotations are captured as pools
   today; richer modelling (secondary list scrapes) would sharpen those majors. *(open)*

### Phase 5 — Hand-review the tail + rollout (ongoing, bounded)
1. Hand-review the flagged minority (~50-75, mostly Engineering + heavy-option majors).
2. Enable the hybrid per-major as each template passes validation; untemplated majors
   keep running the Layer 1 path (§5.4).
3. `log()` any coverage caps so gaps aren't silent.

---

## 8. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| SAP page format varies by college | Per-college footnote maps; auto-validation gates each template before it goes live |
| Template drifts from catalog (course renamed/retired) | `fixed_course`-exists check in Phase 4 validation; fall back to Layer 1 on any unresolved slot |
| Reflow produces an invalid order for off-sequence students | Reflow preserves template relative order but never *reorders* past a satisfied prereq; balance handled by the packer, not by breaking sequence |
| Scraper and app disagree on "UP major" | Single shared UP-major list (Phase 2) imported by both |
| 1.5-cr and pool estimation noise | Packer sums real credits; Layer 1 golden test locks behavior |

---

## 9. Open questions

- Catalog-year handling: templates are catalog-year-specific; do we store every year or
  only the current + snap older students forward?
- Options/subplans without a distinct SAP page: inherit the parent major template or
  require their own?
- Where prerequisite data lives: the SAP order encodes it implicitly — is that enough,
  or do we need an explicit prereq graph for reflow edge cases?
