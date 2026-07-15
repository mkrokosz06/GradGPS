# Timeline SAP Hybrid — Design & Implementation Plan

**Status:** Layer 1 (pool expansion + credit-band packing) in progress in `timeline.py`; Layer 2 (SAP templates) not started
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

- **Harden the filter.** `_is_branch_campus()` in `programs.py` is a **denylist** and
  omits real campuses (`berks`, `abington`, `altoona`, `behrend`). It does **not** leak
  today (those variants aren't in the loaded catalog), but a denylist silently passes
  any campus you forgot. **Flip it to a positive allowlist of the ~12 UP resident
  colleges** (Engineering, Liberal Arts, Science, HHD, IST, Business, Education,
  Arts & Architecture, Ag Sciences, Earth & Mineral Sciences, Nursing, Communications,
  plus Intercollege). The scan already gives us that list.
- **Templates target majors, not all 487 programs.** The 487 is inflated by
  minors/certificates (no SAP). SAP-bearing degree majors ≈ **160-250** counting BA/BS
  and named options separately. Filter to bachelor's `degree` values.

One authoritative UP-major list, shared by the scraper and `programs.py`.

---

## 7. Phased implementation plan

Each phase is independently shippable and leaves the app in a working state.

### Phase 0 — Guardrails (½ day)
- Add a golden-output test: snapshot the current Accounting no-transcript timeline so
  Layer 1 changes are diffable.
- Add a credit-balance assertion helper (every projected semester ∈ [12, 18] cr) to
  reuse across phases.

### Phase 1 — Layer 1 scheduling fix (2-3 days) ← **fixes the reported bug**
1. Write `_expand_pool()`; route `_collect_missing` pools and the free-elective padding
   through it (§4.1).
2. Replace slot packing with the credit-band packer; retire `_item_slots` /
   `_display_credits` slot math (§4.2).
3. Interleave placeholders in `_sort_and_spread` (§4.3).
4. Verify: Accounting + no transcript → 8 balanced semesters, no empty back half,
   1.5-cr courses correct. Update the golden snapshot.

**Exit criteria:** every major's projected semesters sit in the 14-17 band; the back
half shows a mix; no regression in already-good majors.

### Phase 2 — UP-major list hardening (½ day)
1. Flip `_is_branch_campus` → `_is_up_college` allowlist in `programs.py` (§6).
2. Extract the UP-major list into one shared helper both the app and the (future)
   scraper import.
3. Test: the 487 filtered set is unchanged or *smaller* (no leaks); minors excluded
   from the "SAP-eligible majors" view.

### Phase 3 — Accounting proof-of-concept (3-4 days)
1. Scrape the Accounting SAP → one `plan_templates` JSON (typed slots, §5.1).
2. Implement `_match_template` (§5.2) and `_reflow` (§5.3) behind a feature flag; wire
   the fallback (§5.4).
3. Validate the generated Accounting plan against the official published SAP:
   credit totals per semester, prerequisite order, all requirement buckets present
   (World Language 12 cr, Business Breadth 6 cr, PSU 6, etc.).
4. Fix the ECON 102/104 mis-pairing surfaced during comparison.

**Exit criteria:** Accounting hybrid output matches the official SAP structure; a
transfer/off-sequence student still reflows to a valid, balanced plan.

### Phase 4 — Scraper generalization (1 week)
1. Generalize the Accounting scraper into a generic SAP parser + per-college footnote
   maps (Engineering ETM gates / tiered technical electives are the hard cases).
2. Add auto-validation gating per template: credits sum to the degree total, N
   semesters, every slot typed, every `fixed_course` exists in the catalog.
3. Run across all ~160-250 UP majors; a clean generic pass likely auto-covers ~70%
   (~110-175 majors). Log every template that fails validation.

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
