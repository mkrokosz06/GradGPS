# Honors (Schreyer) support — findings and plan

Status: **Phase 1 built**, plus ENGL 202H, the Schreyer declaration (Phase 2 item 1) and the ME thesis rule
(first Phase 3 rule) — Sept 29 2026, see CLAUDE.md "Honors (Schreyer) courses". Remaining: credit tracker,
GPA, thesis timeline for other majors, the 88 unmapped thesis courses. Triggered by a new beta user, Jack Vantine,
a Schreyer Scholar. His own data is not reviewed yet (prod SSO had expired) — see the last section.

## What PSU requires of a Schreyer Scholar

Source: [SHC requirements](https://www.shc.psu.edu/academics/requirements/),
[Scholar Handbook](https://www.shc.psu.edu/academics/handbook/).

| Admit type | Years 1–2 | Years 3–4 | Always |
|---|---|---|---|
| First-year (UP) | **21** honors credits, incl. **ENGL/CAS 137H + 138T** (C or better, first two semesters) | **14** honors credits | 3.40 semester **and** cumulative GPA; honors thesis; Schreyer Plan |
| Second-year (incl. Paterno Fellows) | 9 in year 2 | 14 | same |
| Third-year | — | 14 | same |

What counts as an honors credit (C or better):
- Any course with the Honors attribute — suffixes **H, M** (honors + writing), **T**, **U** — or none.
- **Honors options** on a regular course. **Not marked on the transcript**, so we can't see them.
- 400-level courses in years 1–2; 500-level in years 3–4.
- 294 / 296 / 496 independent study set up as honors.
- Thesis: usually `<DEPT> 494H`, **max 6 credits** toward the 14.
- Study-abroad waivers: 3 cr / semester, 6 cr / year.

RCL I/II (ENGL/CAS 137H → 138T) replace **ENGL 15** (writing) and **CAS 100** (speech), and 138T
satisfies the **First-Year Seminar for every major**. Honors students do not take ENGL 15, CAS 100, or
their college's FYS.

## What's wrong today

GradGPS has no honors concept at all: no flag on the user, no `is_honors` on courses, no GPA parsed,
nothing in the mobile app. The concrete bugs, found by running a synthetic student through all **307**
plan templates twice — once with regular courses, once with the honors version of every course that
has one (same credits, same terms):

**297 of 307 plans (all 180 templated majors) show at least one false "still needed".**

1. **Gen-ed Writing and Speech fail — 269 of 281 plans.** The fixed Communication groups
   (`seed_gen_ed.py`, kept by `rebuild_gen_ed.py`) accept only ENGL 15/ENGL 30 and CAS 100A/B/C.
   137H and 138T are not there. Every first-year Scholar is told they still owe ENGL 15 and CAS 100.
2. **Phantom First-Year Seminar — 206 plans** have an FYS slot in year 1. 138T isn't in
   `_FIRST_YEAR_SEMINARS` (`audit_engine.py`), so the timeline schedules PSU 6 / CHE 100 / etc.
3. **Plan slots don't list the honors sequence** — only 69 templates mention 137H and 65 mention
   138T. The SAP matcher leaves `ENGL 15/ENGL 30H/ESL 15` (92 plans), `CAS 100A/B/C` (52),
   `ENGL 15` (47), `CAS 100` (25)… unsatisfied, so they reappear in the future plan.
4. **Major audit fails honors versions — 75 plans.** The audit engine only strips `W/H/N`
   (`audit_engine.py:1505`, `:1812`), while `sap_schedule.py` strips `WHNMXYRSU`. So the two disagree:
   - `M` (honors + writing) never matches: BIOL 220M/230M/240M vs 220W/230W/240W, MATH 311M vs 311W.
   - ENGL 202H vs "ENGL 202C or ENGL 202D" (12 plans) — the timeline says done, the audit says missing.
   - ENGL 137H vs "ENGL 15 or ENGL 30H" (28), CAS 138T vs "CAS 100A or CAS 100B" (9).
5. **Cross-listings with a suffix are dead — 165 of 828 pairs**, 14 of them honors
   (CAS 137H/ENGL 137H, CAS 138T/ENGL 138T, ANTH/BIOL 460H…). The parser stores `ENGL 137H` as
   `ENGL 137`, but the alias table is keyed on `ENGL 137H`, so the lookup never fires. This one isn't
   honors-only — every N-suffixed cross-listing (AFAM 101N/WMNST 101N…) is affected too.
6. **Wrong credits for 9 honors courses** whose credits differ from the regular twin (CHEM 210H 4 vs 3,
   BIOL 460H 4 vs 3, MATH 494H 3 vs 1…), because the stored code has the H stripped before the
   bulletin lookup.
7. **Nothing tracks the Schreyer requirements**: honors credits (21 / 14), the 3.40 GPA, the thesis
   (no plan schedules a 494H), the thesis-proposal deadline (a year ahead).

Limits of the simulation: local catalog, synthetic student, years 1–2 of each plan. It shows where an
honors version is *rejected*; it doesn't prove every honors twin is an accepted substitute everywhere
(ENGL 202H for a major that names 202C specifically needs checking against the bulletin).

## Plan

### Phase 1 — stop penalizing honors courses (bug fixes, no UI, every honors student benefits)

**Done.** Rerun of the simulation: gen-ed Writing/Speech failures 269 → 0, plan-slot failures 202 → 0,
major-audit failures 75 → 14 (all ENGL 202H vs 202C/202D, left on purpose). Regular students across
921 plan/stage cases: no losses. Jack's graduation: FA 2028 → SP 2028. Items 1–3 and 5 below are in;
item 4 is in for M-suffix courses only; item 6 is `tests/test_honors.py`.

1. **One suffix normalizer** shared by the parser, audit engine, SAP matcher, timeline, courses router
   and ETM (today there are six, with different letter sets). Strip `H/M/T/U` for matching; keep
   `raw_code`; add `is_honors` alongside `is_writing` (M sets both). Normalize alias-table keys the
   same way — this also revives the 165 dead cross-listings.
2. **RCL counts as ENGL 15 + CAS 100**: add ENGL/CAS 137H to Communication: Writing and ENGL/CAS 138T
   to Communication: Effective Speech in `rebuild_gen_ed.py`; add the same equivalences to the major
   audit and the SAP matcher, so the 307 templates don't need hand edits.
3. **138T satisfies the First-Year Seminar** — as a one-way rule (138T fills any FYS slot), not a pair
   in `_FIRST_YEAR_SEMINARS`, which would also let PSU 6 fill a 138T requirement.
4. **Honors twins satisfy the regular requirement in the audit** the way they already do in the SAP
   matcher (M for W, 202H for 202C/D once verified). Audit and timeline must agree.
5. **Bulletin lookups use the raw code** so honors credits/titles are right.
6. Tests: rerun this simulation as a test — honors student and regular student must produce the same
   missing list for all 307 templates.

Needs a prod transcript backfill (parser change) — same shape as the AP/transfer backfill.

### Phase 2 — Schreyer track (feature)

1. **Declare it** on the Account page, like minors: `honors: {program: "schreyer", entry: "first_year" |
   "second_year" | "third_year"}` on the users row. No onboarding step.
2. **Honors credit tracker**: 21 (years 1–2, incl. RCL) and 14 (years 3–4), counted from `is_honors`,
   400-level in years 1–2, 500-level in 3–4, 294/296/496, and up to 6 thesis credits. **Honors options
   are declared by the student** (the transcript doesn't show them) — same "your declaration" labeling
   as substitutions.
3. **GPA**: parse semester + cumulative GPA from the transcript and warn below 3.40. (We parse no GPA
   today; it also helps the ETM GPA floor.)
4. **Timeline**: RCL I/II in year 1 instead of ENGL 15 / CAS 100 / FYS; show the honors section where
   one exists ("MATH 140 — honors: MATH 140H"); schedule the thesis (6 cr of `<DEPT> 494H`, senior
   year) and a thesis-proposal marker one year earlier.

### Phase 3 — per-major honors data

1. **Thesis course per major.** 219 of 307 plans map automatically to `<main dept> 494H`; **88 are
   unmapped** (interdisciplinary majors, and depts like CMPSC/ETI/THEA with no 494H in the bulletin) —
   research each from the department's honors page. Some majors let the thesis replace the capstone;
   record that per major where the department says so.
2. **Honors sections per major**: the appendix counts how many of each plan's courses have an honors
   version, so the timeline can suggest them.
3. Out of scope for now: Paterno Fellows' separate Liberal Arts requirements, and campus honors
   programs outside University Park.

## Jack Vantine

`google:117575626909030296220` — Mechanical Engineering, B.S., entered FA 2024, 5th semester (FA 2026).
Reviewed in prod Sept 29 2026 with `scripts/inspect_user_timeline.py`.

- **Phantom ENGL 15 + CAS 100** scheduled in SP 2027 (6 cr). He took ENGL 137H (stored as `ENGL 137`)
  and CAS 138T; both the gen-ed audit and the ME audit ("ENGL 15 or ENGL 30H", "CAS 100A or CAS 100B")
  still list them as missing. Bugs #1, #3, #4.
- **Honors marks are gone from storage.** Stored rows have no `raw_code`, so `ENGL 137H`,
  `MATH 220H` ("Hnr Matrices") and `ME 494H` ("Senior Thesis", in progress) are saved as plain
  `ENGL 137` / `MATH 220` / `ME 494`. Honors credits can't be counted for any existing user until the
  stored PDFs are re-parsed (`scripts/reparse_stored_transcript.py`).
- **Thesis not credited.** ME's rule: for Schreyer students, 5 cr of ME 494H + 1 cr of ME 493
  substitute for 3 cr of Engineering Technical Elective + 3 cr of General Technical Elective
  ([ME technical electives](https://www.me.psu.edu/students/undergraduate/curriculum-metechnicalelectivescoursedescriptions.aspx)).
  His ME 494 sits in "leftover" and his plan still schedules 2 ETEs + a GTE.
- **Result: graduation shows FA 2028**, one semester past his 8th (SP 2028). The phantoms (6 cr) and
  the thesis electives (6 cr) are 12 cr too many.
- Not affected: FYS (the ME plan has no seminar slot); transfer MATH 140 / PHYS 250 read fine.

This adds a Phase 3 data shape: **"thesis replaces electives"** per major (ME: 494H + 493 → ETE + GTE).

**Resolved Sept 29 2026, confirmed by Jack.** Phase 1 shipped (`dc5f92e`) and his transcript was
re-parsed (honors codes restored); the Schreyer declaration + ME thesis rule shipped in `bd6dc58`
with the Account card over the air (EAS update `eaaf8151`). His plan: no ENGL 15 / CAS 100, ME 494H
fills the thesis slot, ME 493 in SP 2028, one ETE + the GTE gone, graduation SP 2028.

## Appendix — per major

"FYS slot" = the plan's year-1 seminar the timeline will schedule for a Scholar (138T covers it).
"Plan slots" = SAP slots left unsatisfied only because the course was the honors version.
"Audit rows" = major-audit items missing only because of the honors version.
269 plans also have the gen-ed Writing/Speech failure (#1), not repeated here.

| Major (option) | Thesis course | FYS slot → phantom | Plan slots an honors version fails | Audit rows an honors version fails | Honors versions of plan courses |
|---|---|---|---|---|---|
| Accounting, B.S. (Business) | ACCTG 494H | PSU 6 | — | — | 13 |
| Acting, B.F.A. | **unmapped** (THEA) | THEA 1S | ENGL 15/ENGL 15A/ENGL 30H | — | 5 |
| Actuarial Science, B.S. | STAT 494H | PSU 6 | — | — | 17 |
| Advertising/Public Relations, B.A. | COMM 494H | PSU 9 | ENGL 15 | — | 9 |
| Advertising/Public Relations, B.A. — Advertising | COMM 494H | PSU 9 | ENGL 15 | — | 9 |
| Advertising/Public Relations, B.A. — Public Relations | COMM 494H | PSU 9 | ENGL 15 | — | 9 |
| Aerospace Engineering, B.S. | AERSP 494H | AERSP 1 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B | CAS 100A or CAS 100B; ENGL 15 or ENGL 30H | 16 |
| African American Studies, B.A. | AFAM 494H | LA 283 | — | — | 7 |
| African Studies, B.A. | **unmapped** (?) | LA 283 | — | — | 9 |
| Agribusiness Management, B.S. | AGBM 494H | — | ENGL 15/ENGL 30H/ESL 15 | — | 13 |
| Agricultural Science, B.S. | AEE 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | CAS 100; ENGL 15 | 6 |
| Agricultural and Biorenewable Systems Management, B.S. | ABSM 494H | — | ENGL 15; CAS 100A/CAS 100B | CAS 100A or CAS 100B; ENGL 15 | 8 |
| Agricultural and Extension Education, B.S. | AEE 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | ENGL 202C | 7 |
| Agricultural and Extension Education, B.S. — Environmental Science | AEE 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | ENGL 202C | 7 |
| Animal Science, B.S. | ANSC 494H | ANSC 150S | ENGL 15/ENGL 30H; CAS 100A | — | 8 |
| Anthropological Science, B.S. | ANTH 494H | LA 283 | — | — | 0 |
| Anthropological Science, B.S. — Archaeological Science | ANTH 494H | LA 283 | — | — | 0 |
| Anthropological Science, B.S. — Biological Anthropology | ANTH 494H | LA 283 | — | — | 0 |
| Anthropological Science, B.S. — Human Ecology | ANTH 494H | LA 283 | — | — | 0 |
| Anthropological Science, B.S. — Integrated Anthropological Science | ANTH 494H | LA 283 | — | — | 0 |
| Anthropology, B.A. | ANTH 494H | LA 283 | — | — | 0 |
| Applied Linguistics, B.A. | **unmapped** (APLNG) | LA 283 | ENGL 15/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 4 |
| Architectural Engineering, B.A.E. | AE 494H, AE 494M | AE 124 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B | Common Requirements for the Major (All Options) | 16 |
| Architecture, B.Arch. | **unmapped** (ARCH) | — | ENGL 15/ENGL 15A/ENGL 30H | — | 6 |
| Art Education, B.S. | AED 494H | AED 101S | ENGL 15/ENGL 15A/ENGL 30H | — | 8 |
| Art History, B.A. | **unmapped** (ARTH) | ARTH 1S | ENGL 15/ENGL 15A/ENGL 30H; CAS 100 | — | 2 |
| Art, B.A. (Arts and Architecture) | **unmapped** (?) | — | ENGL 15/ENGL 15A/ENGL 30H | — | 5 |
| Art, B.F.A. | **unmapped** (?) | — | ENGL 15/ENGL 15A/ENGL 30H | — | 5 |
| Artificial Intelligence Engineering, B.S. | **unmapped** (A-I) | — | ENGL 15; CAS 100A/CAS 100B | — | 6 |
| Artificial Intelligence Methods and Applications, B.S. (Information Sciences and Technology) | **unmapped** (CMPSC) | — | ENGL 15; CAS 100A/CAS 100B/CAS 100C | — | 6 |
| Asian Studies, B.A. | **unmapped** (ASIA) | LA 283 | — | — | 4 |
| Astronomy and Astrophysics, B.S. | **unmapped** (CMPSC) | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | — | 12 |
| Astronomy and Astrophysics, B.S. — Computer Science | **unmapped** (CMPSC) | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | — | 12 |
| Astronomy and Astrophysics, B.S. — Graduate Study | MATH 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | — | 11 |
| Biobehavioral Health, B.S. (Health and Human Development) | BBH 494H | — | — | — | 7 |
| Biochemistry and Molecular Biology, B.S. (Science) | BMB 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 20 |
| Biochemistry and Molecular Biology, B.S. (Science) — Biochemistry | BMB 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 20 |
| Biochemistry and Molecular Biology, B.S. (Science) — Molecular and Cell Biology | BMB 494H | PSU 16 | ENGL 15/ESL 15/ENGL 30H; CAS 100A/CAS 100B/CAS 100C | — | 18 |
| Biological Engineering, B.S. | BE 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 11 |
| Biological Engineering, B.S. — Agricultural Engineering | BE 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 11 |
| Biological Engineering, B.S. — Food and Biological Processing Engineering | BE 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 14 |
| Biological Engineering, B.S. — Natural Resources Engineering | BE 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 11 |
| Biology, B.S. (Science) | **unmapped** (?) | PSU 16 | CAS 100A/CAS 100B/CAS 100C | — | 12 |
| Biology, B.S. (Science) — Ecology | STAT 494H | PSU 16 | CAS 100A/CAS 100B/CAS 100C | — | 12 |
| Biology, B.S. (Science) — Genetics and Developmental Biology | BMB 494H | PSU 16 | CAS 100A/CAS 100B/CAS 100C | — | 14 |
| Biology, B.S. (Science) — Neuroscience | BIOL 494H | PSU 16 | CAS 100A/CAS 100B/CAS 100C | — | 14 |
| Biology, B.S. (Science) — Plant Biology | BMB 494H | PSU 16 | CAS 100A/CAS 100B/CAS 100C | — | 14 |
| Biology, B.S. (Science) — Vertebrate Physiology | BIOL 494H | PSU 16 | CAS 100A/CAS 100B/CAS 100C | — | 13 |
| Biomedical Engineering, B.S. | BME 494H | BME 100 | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 21 |
| Biomedical Engineering, B.S. — Biomechanics | BME 494H | BME 100 | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 21 |
| Biomedical Engineering, B.S. — Biopharmaceutical | BME 494H | BME 100 | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 17 |
| Biomedical Engineering, B.S. — Medical Device Design | BME 494H | BME 100 | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 16 |
| Biomedical Engineering, B.S. — Medical Imaging | BME 494H | BME 100 | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 20 |
| Biotechnology, B.S. | **unmapped** (BIOTC) | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 15 |
| Biotechnology, B.S. — Clinical Laboratory Science | **unmapped** (MICRB) | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 14 |
| Business Analytics and Information Systems, B.S. | MIS 494H | PSU 6 | — | Requirements for the Major | 13 |
| Business, B.S. (Intercollege) | ACCTG 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | ENGL 15 or ENGL 30H | 10 |
| Chemical Engineering, B.S. | CHE 494H | CHE 100 | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 18 |
| Chemistry, B.S. (Science) | CHEM 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A | — | 17 |
| Chinese, B.A. | CHNS 494H | LA 283 | — | — | 4 |
| Civil Engineering, B.S. (Engineering) | CE 494H | CE 100S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B | CAS 100A or CAS 100B; ENGL 15 or ENGL 30H | 19 |
| Classics and Ancient Mediterranean Studies, B.A. | CAMS 494H | LA 283 | — | — | 0 |
| Classics and Ancient Mediterranean Studies, B.A. — Ancient Mediterranean Archaeology | CAMS 494H | LA 283 | — | — | 0 |
| Communication Arts and Sciences, B.A. (Liberal Arts) | CAS 494H | LA 283 | ENGL 15; CAS 100 | — | 5 |
| Communication Arts and Sciences, B.S. | CAS 494H | LA 283 | ENGL 15; CAS 100 | — | 5 |
| Communication Sciences and Disorders, B.S. (Health and Human Development) | CSD 494H | — | — | — | 1 |
| Community, Environment, and Development, B.S. | CED 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 12 |
| Community, Environment, and Development, B.S. — Community and Economic Development | CED 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 12 |
| Community, Environment, and Development, B.S. — Environmental Economics and Policy | CED 494H | — | CAS 100A/CAS 100B/CAS 100C; ENGL 15/ENGL 30H/ESL 15 | — | 13 |
| Community, Environment, and Development, B.S. — International Development | CED 494H | — | CAS 100A/CAS 100B/CAS 100C; ENGL 15/ENGL 30H/ESL 15 | — | 12 |
| Community, Environment, and Development, B.S. — Social and Environmental Responsibility | CED 494H | — | CAS 100A/CAS 100B/CAS 100C; ENGL 15/ENGL 30H | — | 12 |
| Comparative Literature, B.A. | CMLIT 494H | LA 283 | — | — | 7 |
| Computer Engineering, B.S. (Engineering) | CMPEN 494H | — | ENGL 15 | — | 10 |
| Computer Science, B.S. (Engineering) | **unmapped** (CMPSC) | — | ENGL 15; CAS 100A/CAS 100B | — | 8 |
| Corporate Innovation and Entrepreneurship, B.S. | MGMT 494H | PSU 6 | — | — | 13 |
| Criminology, B.A. | **unmapped** (?) | LA 283 | — | — | 3 |
| Criminology, B.S. | **unmapped** (?) | LA 283 | — | — | 3 |
| Cybersecurity Analytics and Operations, B.S. (Information Sciences and Technology) | **unmapped** (CYBER) | — | — | — | 8 |
| Data Sciences, B.S. (Engineering) | **unmapped** (CMPSC) | — | ENGL 15; CAS 100A/CAS 100B | — | 8 |
| Data Sciences, B.S. (Information Sciences and Technology) | **unmapped** (DS) | PSU 17 | ENGL 15; CAS 100 | — | 7 |
| Data Sciences, B.S. (Science) | STAT 494H | PSU 16 | ENGL 15; CAS 100 | CMPSC 360 or MATH 311W | 9 |
| Digital Arts and Media Design, B.Des. | **unmapped** (DART) | — | ENGL 15/ENGL 15A/ENGL 30H | — | 5 |
| Digital Multimedia Design, B.Des. | **unmapped** (DMD) | — | ENGL 15/ENGL 15A/ENGL 30H; CAS 100A/CAS 100B/CAS 100C | — | 5 |
| Earth Science and Policy, B.S. | **unmapped** (EARTH) | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 11 |
| Earth Science and Policy, B.S. — Climate Change | **unmapped** (EARTH) | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 11 |
| Earth Science and Policy, B.S. — Energy | **unmapped** (EARTH) | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 11 |
| Earth Science and Policy, B.S. — Water and Land Use | **unmapped** (EARTH) | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 11 |
| Earth Sciences, B.S. | **unmapped** (?) | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 9 |
| Economics, B.A. (Liberal Arts) | ECON 494H | LA 283 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 10 |
| Economics, B.S. | ECON 494H | LA 283 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 11 |
| Education and Public Policy, B.S. | **unmapped** (EDTHP) | — | ENGL 15/ENGL 30H; CAS 100 | — | 6 |
| Electrical Engineering Technology, B.S. (Engineering) | **unmapped** (EET) | PSU 8 | ENGL 15 | ENGL 202C or ENGL 202D | 7 |
| Electrical Engineering, B.S. (Engineering) | EE 494H | EE 9 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B | — | 19 |
| Electro-Mechanical Engineering Technology, B.S. (Engineering) | **unmapped** (EMET) | PSU 8 | ENGL 15; CAS 100A/CAS 100B | ENGL 202C or ENGL 202D | 4 |
| Elementary and Early Childhood Education, B.S. | **unmapped** (CI) | — | ENGL 15/ENGL 30H; CAS 100A | — | 5 |
| Energy Business and Finance, B.S. | **unmapped** (EBF) | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | — | 11 |
| Energy Engineering, B.S. | **unmapped** (EGEE) | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | — | 13 |
| Energy and Sustainability Policy, B.A. | GEOG 494H | — | ENGL 15; CAS 100 | CAS 100; ENGL 15 | 5 |
| Energy and Sustainability Policy, B.S. | GEOG 494H | — | CAS 100; ENGL 15 | CAS 100; ENGL 15 | 5 |
| Engineering Science, B.S. | ESC 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B | CAS 100A or CAS 100B; ENGL 15 or ENGL 30H | 23 |
| Engineering, B.S. | **unmapped** (EGEE) | PSU 8 | ENGL 15/ENGL 30H; CAS 100A/CAS 100B | CAS 100A or CAS 100B; ENGL 15 or ENGL 30H | 13 |
| English, B.A. (Liberal Arts) | ENGL 494H | LA 283 | — | — | 8 |
| Enterprise Technology Integration, B.S. (Information Sciences and Technology) | **unmapped** (ETI) | — | ENGL 15/ENGL 30H; CAS 100A/CAS 100B/CAS 100C | — | 6 |
| Environmental Resource Management, B.S. | ERM 494H | — | — | BIOL 220W or BIOL 224 | 13 |
| Environmental Resource Management, B.S. — Environmental Science | ERM 494H | — | — | BIOL 220W or BIOL 224 | 13 |
| Environmental Resource Management, B.S. — Soil Science | SOILS 494H | — | — | — | 12 |
| Environmental Resource Management, B.S. — Water Science | ERM 494H | — | — | BIOL 220W or BIOL 224 | 13 |
| Environmental Systems Engineering, B.S. | **unmapped** (ENVSE) | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 12 |
| Film Production, B.A. | COMM 494H | PSU 9 | ENGL 15; CAS 100A/CAS 100B/CAS 100C | — | 4 |
| Finance, B.S. (Business) | FIN 494H | PSU 6 | — | — | 16 |
| Food Science, B.S. | FDSC 494H | FDSC 150S | ENGL 15 | ENGL 15; ENGL 202C or ENGL 202D | 7 |
| Forensic Science, B.S. | **unmapped** (FRNSC) | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | — | 14 |
| Forensic Science, B.S. — Forensic Chemistry | CHEM 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | BIOL 230W | 16 |
| Forensic Science, B.S. — Forensic Molecular Biology | **unmapped** (FRNSC) | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | — | 14 |
| Forest Ecosystems, B.S. | FOR 494H | — | ENGL 15/ENGL 30H; CAS 100 | BIOL 220W; Common Requirements for the Major (All Options) | 9 |
| Forest Ecosystems, B.S. — Biodiversity and Conservation | FOR 494H | — | ENGL 15/ENGL 30H; CAS 100 | BIOL 220W; Common Requirements for the Major (All Options) | 9 |
| Forest Ecosystems, B.S. — Forest Management | FOR 494H | — | ENGL 15/ENGL 30H; CAS 100 | Common Requirements for the Major (All Options); ENGL 202C or ENGL 202D | 8 |
| Forest Ecosystems, B.S. — Forests, Trees, and People | FOR 494H | — | ENGL 15/ENGL 30H; CAS 100 | Common Requirements for the Major (All Options); ENGL 202C or ENGL 202D | 8 |
| Forest Ecosystems, B.S. — Watershed Ecohydrology | FOR 494H | — | ENGL 15/ENGL 30H; CAS 100 | Common Requirements for the Major (All Options); ENGL 202C or ENGL 202D | 8 |
| French and Francophone Studies, B.A. | FR 494H | LA 283 | — | — | 3 |
| French and Francophone Studies, B.A. — Language and Culture | FR 494H | LA 283 | — | — | 3 |
| French and Francophone Studies, B.A. — Language and Linguistics | FR 494H | LA 283 | — | — | 3 |
| French and Francophone Studies, B.A. — Language and Literature | FR 494H | LA 283 | — | — | 3 |
| French and Francophone Studies, B.S. | FR 494H | LA 283 | — | — | 3 |
| French and Francophone Studies, B.S. — Applied French | FR 494H | LA 283 | — | — | 3 |
| French and Francophone Studies, B.S. — French-Business | FR 494H | LA 283 | — | — | 6 |
| French and Francophone Studies, B.S. — French-Engineering | FR 494H | LA 283 | — | — | 3 |
| Geobiology, B.S. | GEOSC 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 11 |
| Geography, B.A. | GEOG 494H | EMSC 100S | — | — | 0 |
| Geography, B.S. | GEOG 494H | EMSC 100S | — | — | 2 |
| Geosciences, B.A. | GEOSC 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 8 |
| Geosciences, B.S. | GEOSC 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 11 |
| Geosciences, B.S. — Hydrogeology | GEOSC 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 11 |
| German, B.A. | GER 494H | LA 283 | — | — | 4 |
| German, B.S. | GER 494H | LA 283 | CAS 100A/CAS 100B/CAS 100C | — | 4 |
| German, B.S. — Applied German | GER 494H | LA 283 | CAS 100A/CAS 100B/CAS 100C | — | 4 |
| German, B.S. — German Business | GER 494H | LA 283 | — | — | 7 |
| German, B.S. — German Engineering | GER 494H | LA 283 | — | — | 4 |
| Global and International Studies, B.A. | **unmapped** (GLIS) | LA 283 | — | — | 5 |
| Global and International Studies, B.S. | **unmapped** (GLIS) | LA 283 | — | — | 7 |
| Graphic Design, B.Des. | GD 494H | GD 1S | — | — | 6 |
| Health Policy and Administration, B.S. (Health and Human Development) | HPA 494H | — | — | — | 5 |
| History, B.A. (Liberal Arts) | HIST 494H | LA 283 | — | — | 1 |
| Hospitality Management, B.S. (Health and Human Development) | HM 494H | — | — | — | 0 |
| Human Development and Family Studies, B.S. (Health and Human Development) | HDFS 494H | HDFS 129S | — | — | 1 |
| Human Development and Family Studies, B.S. (Health and Human Development) — Developmental Science for Health Professions | HDFS 494H | HDFS 129S | — | — | 1 |
| Human Development and Family Studies, B.S. (Health and Human Development) — Human Development and Family Science | HDFS 494H | HDFS 129S | — | — | 1 |
| Human-Centered Design and Development, B.S. (Information Sciences and Technology) | IST 494H | — | ENGL 15/ENGL 30H; CAS 100 | ENGL 15 or ENGL 30H | 5 |
| Immunology and Infectious Disease, B.S. | **unmapped** (VBSC) | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | BIOL 220W or BIOL 240W; BIOL 230W | 15 |
| Industrial Engineering, B.S. (Engineering) | **unmapped** (IE) | — | ENGL 15/ENGL 30H; CAS 100A/CAS 100B | CAS 100A or CAS 100B; ENGL 15 or ENGL 30H | 12 |
| Industrial Engineering, B.S. (Engineering) — Service Systems Engineering | **unmapped** (IE) | — | ENGL 15/ENGL 30H; CAS 100A/CAS 100B | CAS 100A or CAS 100B; ENGL 15 or ENGL 30H | 12 |
| Information Technology Ethics and Compliance, B.S. | IST 494H | — | ENGL 15; CAS 100A/CAS 100B/CAS 100C | — | 2 |
| Integrative Arts, B.A. (Arts and Architecture) | **unmapped** (?) | — | ENGL 15/ENGL 15A/ENGL 30H; CAS 100A/CAS 100B/CAS 100C | — | 2 |
| Integrative Science, B.S. (Science) | **unmapped** (?) | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 15 |
| Integrative Science, B.S. (Science) — Biological Sciences and Health Professions | BIOL 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | — | 19 |
| Integrative Science, B.S. (Science) — Legal Studies, Government Service, Public Policy | **unmapped** (?) | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 15 |
| International Politics, B.A. | PLSC 494H | LA 283 | — | — | 12 |
| International Politics, B.A. — International Political Economy | PLSC 494H | LA 283 | — | — | 12 |
| International Politics, B.A. — International Relations | PLSC 494H | LA 283 | — | — | 10 |
| International Politics, B.A. — National Security | PLSC 494H | LA 283 | — | — | 12 |
| Italian, B.A. | IT 494H | LA 283 | — | — | 4 |
| Italian, B.S. | IT 494H | LA 283 | — | — | 4 |
| Japanese, B.A. | JAPNS 494H | LA 283 | — | — | 4 |
| Jewish Studies, B.A. | **unmapped** (?) | LA 283 | — | — | 0 |
| Journalism, B.A. | COMM 494H | PSU 9 | ENGL 15/ENGL 30H | — | 10 |
| Journalism, B.A. — Broadcast Journalism | COMM 494H | PSU 9 | ENGL 15/ENGL 30H | — | 10 |
| Journalism, B.A. — Digital and Print Journalism | COMM 494H | PSU 9 | ENGL 15/ENGL 30H | — | 10 |
| Journalism, B.A. — Photojournalism | COMM 494H | PSU 9 | ENGL 15/ENGL 30H | — | 10 |
| Kinesiology, B.S. (Health and Human Development) | KINES 494H | — | — | — | 4 |
| Korean, B.A. | KOR 494H | LA 283 | — | — | 4 |
| Labor and Human Resources, B.A. | LHR 494H | LA 283 | — | — | 6 |
| Labor and Human Resources, B.S. | LHR 494H | LA 283 | — | — | 6 |
| Labor and Human Resources, B.S. — Human Resources | LHR 494H | LA 283 | — | — | 6 |
| Labor and Human Resources, B.S. — Labor and Employment Relations | LHR 494H | LA 283 | — | — | 6 |
| Landscape Architecture, B.L.A. | **unmapped** (LARCH) | — | ENGL 15/ENGL 30H | — | 5 |
| Landscape Contracting, B.S. | **unmapped** (HORT) | PLANT 150S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 6 |
| Landscape Contracting, B.S. — Design/Build | **unmapped** (HORT) | PLANT 150S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 6 |
| Landscape Contracting, B.S. — Management | **unmapped** (HORT) | PLANT 150S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 6 |
| Latin American Studies, B.A. | PLSC 494H | LA 283 | — | — | 0 |
| Linguistics, B.A. | LING 494H | LA 283 | — | — | 4 |
| Management, B.S. (Business) | MGMT 494H | PSU 6 | — | — | 13 |
| Marketing, B.S. (Business) | MKTG 494H | PSU 6 | — | — | 13 |
| Materials Science and Engineering, B.S. | MATSE 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | ENGL 15 or ENGL 30H | 13 |
| Mathematics, B.A. | MATH 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | MATH 311W | 14 |
| Mathematics, B.S. (Science) | MATH 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | MATH 311W | 18 |
| Mathematics, B.S. (Science) — Actuarial Mathematics | MATH 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | MATH 311W | 18 |
| Mathematics, B.S. (Science) — Applied and Industrial Mathematics | MATH 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | MATH 311W | 19 |
| Mathematics, B.S. (Science) — Computational Mathematics | MATH 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | MATH 311W | 18 |
| Mathematics, B.S. (Science) — Graduate Study | MATH 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | MATH 311W | 18 |
| Mathematics, B.S. (Science) — Systems Analysis | MATH 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | MATH 311W | 17 |
| Mechanical Engineering, B.S. (Engineering) | ME 494H | — | ENGL 15; CAS 100A/CAS 100B | CAS 100A or CAS 100B; ENGL 15 or ENGL 30H | 12 |
| Media Studies, B.A. | COMM 494H | PSU 9 | ENGL 15 | — | 4 |
| Media Studies, B.A. — Film and Television Studies | COMM 494H | PSU 9 | ENGL 15 | — | 4 |
| Media Studies, B.A. — Media Effects | COMM 494H | PSU 9 | ENGL 15 | — | 6 |
| Media Studies, B.A. — Society and Culture | COMM 494H | PSU 9 | ENGL 15 | — | 5 |
| Medieval Studies, B.A. | **unmapped** (?) | LA 283 | — | — | 1 |
| Meteorology and Atmospheric Science, B.S. | METEO 494H, METEO 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | — | 10 |
| Meteorology and Atmospheric Science, B.S. — Atmospheric Science | METEO 494H, METEO 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | — | 10 |
| Meteorology and Atmospheric Science, B.S. — Climate Science | METEO 494H, METEO 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | — | 10 |
| Meteorology and Atmospheric Science, B.S. — Environmental Meteorology | METEO 494H, METEO 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | — | 10 |
| Meteorology and Atmospheric Science, B.S. — Weather Forecasting and Communications | METEO 494H, METEO 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | — | 10 |
| Meteorology and Atmospheric Science, B.S. — Weather Risk Management | METEO 494H, METEO 494M | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | — | 11 |
| Microbiology, B.S. | BMB 494H | — | ENGL 15/ENGL 30H; CAS 100A/CAS 100B/CAS 100C | — | 19 |
| Middle Level Education, B.S. | **unmapped** (LLED) | — | ENGL 15/ENGL 30H; CAS 100A | — | 5 |
| Middle Level Education, B.S. — English 4-8 | **unmapped** (LLED) | — | ENGL 15/ENGL 30H; CAS 100A | — | 5 |
| Middle Level Education, B.S. — Mathematics 4-8 | **unmapped** (MTHED) | — | ENGL 15/ENGL 30H; CAS 100A | — | 8 |
| Middle Level Education, B.S. — Social Studies 4-8 | **unmapped** (CI) | — | ENGL 15/ENGL 30H | — | 7 |
| Mining Engineering, B.S. | MNG 494H | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | — | 15 |
| Multidisciplinary Studies, B.A. (Liberal Arts) | **unmapped** (?) | LA 283 | — | — | 7 |
| Music Education, B.M.E. | MUSIC 494H | — | ENGL 15/ENGL 15A/ENGL 30H | — | 9 |
| Music Technology, B.M. | MUSIC 494H | — | ENGL 15/ENGL 15A/ENGL 30H | — | 6 |
| Music, B.A. | MUSIC 494H | — | ENGL 15/ENGL 15A/ENGL 30H | — | 6 |
| Music, B.A. — Music Technology | MUSIC 494H | — | — | — | 6 |
| Music, B.M. | MUSIC 494H | — | ENGL 15/ENGL 15A/ENGL 30H | — | 6 |
| Music, B.M. — Composition | MUSIC 494H | — | ENGL 15/ENGL 15A/ENGL 30H | — | 6 |
| Music, B.M. — Keyboard Instruments | MUSIC 494H | — | ENGL 15/ENGL 15A/ENGL 30H | — | 3 |
| Music, B.M. — Strings, Winds, Brass and Percussion Instruments | MUSIC 494H | — | ENGL 15/ENGL 15A/ENGL 30H | — | 6 |
| Music, B.M. — Voice | MUSIC 494H | — | ENGL 15/ENGL 15A/ENGL 30H | — | 6 |
| Musical Arts, B.M.A. | MUSIC 494H | — | ENGL 15/ENGL 15A/ENGL 30H | — | 6 |
| Musical Theatre, B.F.A. | **unmapped** (THEA) | THEA 1S | ENGL 15/ENGL 15A/ENGL 30H; CAS 100A/CAS 100B/CAS 100C | — | 6 |
| Neurobiology, B.S. | BIOL 494H | — | — | — | 16 |
| Nuclear Engineering, B.S. | **unmapped** (NUCE) | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B | CAS 100A or CAS 100B; ENGL 15 or ENGL 30H | 15 |
| Nursing, B.S.N. | **unmapped** (NURS) | — | ENGL 15/ENGL 30H; CAS 100A/CAS 100B/CAS 100C | CAS 100; ENGL 15 | 10 |
| Nutritional Sciences, B.S. | NUTR 494H | — | — | — | 4 |
| Nutritional Sciences, B.S. — Health Sciences | NUTR 494H | — | — | — | 4 |
| Nutritional Sciences, B.S. — Nutrition and Dietetics | NUTR 494H | — | — | — | 2 |
| Organizational Leadership, B.A. | LHR 494H | LA 283 | — | — | 8 |
| Organizational Leadership, B.S. | LHR 494H | LA 283 | — | — | 9 |
| Petroleum and Natural Gas Engineering, B.S. | PNG 494H | EMSC 100S | ENGL 15/ENGL 30H/ESL 15 | Requirements for the Major | 15 |
| Pharmacology and Toxicology, B.S. | **unmapped** (VBSC) | — | ENGL 15/ENGL 30H/ESL 15; CAS 100 | BIOL 141 or BIOL 240W; BIOL 220W; BIOL 230W | 15 |
| Philosophy, B.A. | **unmapped** (?) | LA 283 | — | — | 7 |
| Philosophy, B.A. — Humanities and Arts | PHIL 494H | LA 283 | — | — | 7 |
| Philosophy, B.A. — Justice, Law, and Values | PLSC 494H | LA 283 | — | — | 8 |
| Philosophy, B.A. — Philosophy of Science and Mathematics | PHIL 494H | LA 283 | — | — | 7 |
| Philosophy, B.A. — Professional Studies | PHIL 494H | LA 283 | — | — | 7 |
| Philosophy, B.A. — Social Sciences | PHIL 494H | LA 283 | — | — | 7 |
| Philosophy, B.S. | **unmapped** (?) | LA 283 | — | — | 0 |
| Physics, B.S. (Science) | PHYS 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 12 |
| Physics, B.S. (Science) — Computation | PHYS 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | — | 13 |
| Physics, B.S. (Science) — Electronics | PHYS 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | — | 12 |
| Physics, B.S. (Science) — Medical Physics | PHYS 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 16 |
| Planetary Science and Astronomy, B.S. | ASTRO 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | — | 9 |
| Plant Sciences, B.S. | **unmapped** (HORT) | PLANT 150S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | ENGL 202C or ENGL 202D | 9 |
| Plant Sciences, B.S. — Agroecology | **unmapped** (HORT) | PLANT 150S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | ENGL 202C or ENGL 202D | 9 |
| Plant Sciences, B.S. — Crop Production | **unmapped** (AGECO) | PLANT 150S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | ENGL 202C or ENGL 202D | 9 |
| Plant Sciences, B.S. — Horticulture | **unmapped** (HORT) | PLANT 150S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | ENGL 202C or ENGL 202D | 8 |
| Plant Sciences, B.S. — Plant Genetics and Biotechnology | **unmapped** (HORT) | PLANT 150S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | — | 14 |
| Plant Sciences, B.S. — Plant Science | BIOL 494H | PLANT 150S | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C | ENGL 202C or ENGL 202D | 13 |
| Political Science, B.A. (Liberal Arts) | **unmapped** (?) | LA 283 | — | — | 10 |
| Political Science, B.S. | PLSC 494H | LA 283 | — | — | 12 |
| Premedicine, B.S. | BMB 494H | PSU 16 | ENGL 15/ENGL 30H/ESL 15 | BIOL 230W | 24 |
| Professional Photography, B.Des. | **unmapped** (PHOTO) | — | ENGL 15/ENGL 15A/ENGL 30H; CAS 100A/CAS 100B/CAS 100C | — | 5 |
| Psychology, B.A. (Liberal Arts) | PSYCH 494H | LA 283 | — | — | 9 |
| Psychology, B.S. (Liberal Arts) | PSYCH 494H | LA 283 | — | — | 6 |
| Real Estate, B.S. | RM 494H | PSU 6 | — | Requirements for the Major | 13 |
| Recreation, Park, and Tourism Management, B.S. (Health and Human Development) | RPTM 494H | RPTM 120S | — | — | 0 |
| Recreation, Park, and Tourism Management, B.S. (Health and Human Development) — Commercial Recreation and Tourism Management | RPTM 494H | RPTM 120S | — | — | 0 |
| Recreation, Park, and Tourism Management, B.S. (Health and Human Development) — Community Recreation Management | RPTM 494H | RPTM 120S | — | — | 0 |
| Recreation, Park, and Tourism Management, B.S. (Health and Human Development) — Outdoor Recreation Management | RPTM 494H | RPTM 120S | — | — | 0 |
| Recreation, Park, and Tourism Management, B.S. (Health and Human Development) — Professional Golf Management | RPTM 494H | PSU 14, RPTM 100S | — | — | 3 |
| Rehabilitation and Human Services, B.S. (Education) | **unmapped** (RHS) | — | ENGL 15/ENGL 30H | — | 6 |
| Risk Management, B.S. | BA 494H | PSU 6 | — | Common Requirements for the Major (All Options) | 13 |
| Russian, B.A. | RUS 494H | LA 283 | CAS 100A/CAS 100B/CAS 100C | — | 4 |
| Secondary Education, B.S. (Education) | BMB 494H | — | ENGL 15; CAS 100A | BIOL 220W or BIOL 224; BIOL 230W or BIOL 234; BIOL 240W or BIOL 244 | 24 |
| Secondary Education, B.S. (Education) — Biological Science Teaching | BMB 494H | — | ENGL 15; CAS 100A | BIOL 220W or BIOL 224; BIOL 230W or BIOL 234; BIOL 240W or BIOL 244 | 24 |
| Secondary Education, B.S. (Education) — Chemistry Teaching | **unmapped** (SPLED) | — | ENGL 15 | — | 14 |
| Secondary Education, B.S. (Education) — Earth and Space Science Teaching | BIOL 494H | — | ENGL 15; CAS 100A | BIOL 220W or BIOL 224 | 16 |
| Secondary Education, B.S. (Education) — English Teaching | **unmapped** (LLED) | — | ENGL 15/ENGL 30H; CAS 100A | — | 6 |
| Secondary Education, B.S. (Education) — Physics Teaching | PHYS 494H | — | ENGL 15 | — | 16 |
| Security and Risk Analysis, B.S. (Information Sciences and Technology) | **unmapped** (SRA) | — | ENGL 15/ENGL 30H/ESL 15; CAS 100 | — | 9 |
| Security and Risk Analysis, B.S. (Information Sciences and Technology) — Information and Cyber Security | IST 494H | — | ENGL 15/ENGL 30H; CAS 100 | — | 8 |
| Security and Risk Analysis, B.S. (Information Sciences and Technology) — Intelligence Analysis and Modeling | **unmapped** (SRA) | — | ENGL 15/ENGL 30H/ESL 15; CAS 100 | — | 9 |
| Social Data Analytics, B.S. | **unmapped** (DS) | LA 283 | — | — | 14 |
| Sociology, B.A. | SOC 494H | LA 283 | — | — | 1 |
| Sociology, B.S. (Liberal Arts) | SOC 494H | LA 283 | — | — | 2 |
| Spanish, B.A. | **unmapped** (?) | LA 283 | — | — | 4 |
| Spanish, B.S. | **unmapped** (?) | LA 283 | — | — | 4 |
| Spanish, B.S. — Applied Spanish | **unmapped** (?) | LA 283 | — | — | 4 |
| Spanish, B.S. — Business | BA 494H | LA 283 | — | — | 10 |
| Special Education, B.S. | **unmapped** (SPLED) | — | ENGL 15/ENGL 30H; CAS 100A | — | 5 |
| Statistics, B.S. | STAT 494H | PSU 16 | ENGL 15 | — | 11 |
| Statistics, B.S. — Actuarial Statistics | STAT 494H | PSU 16 | ENGL 15 | — | 11 |
| Statistics, B.S. — Applied Statistics | STAT 494H | PSU 16 | ENGL 15; CAS 100 | — | 7 |
| Statistics, B.S. — Biostatistics | STAT 494H | PSU 16 | ENGL 15/ESL 15; CAS 100 | — | 12 |
| Statistics, B.S. — Graduate Study | STAT 494H | PSU 16 | ENGL 15; CAS 100 | — | 11 |
| Statistics, B.S. — Statistics and Computing | STAT 494H | PSU 16 | ENGL 15; CAS 100 | — | 8 |
| Supply Chain and Information Systems, B.S. | SCM 494H | PSU 6 | — | Requirements for the Major | 13 |
| Surveying Engineering, B.S. | **unmapped** (SUR) | PSU 8 | ENGL 15 | ENGL 15 or ENGL 30H; ENGL 202C or ENGL 202D | 12 |
| Sustainability, Society, and Environmental Geography, B.A. | GEOG 494H | EMSC 100S | — | — | 2 |
| Systems Neuroscience, B.S. | BBH 494H | — | — | — | 2 |
| Telecommunications and Media Industries, B.A. | COMM 494H | PSU 9 | ENGL 15 | — | 4 |
| Theatre, B.A. | **unmapped** (THEA) | THEA 1S | ENGL 15 | — | 5 |
| Theatre, B.F.A. | **unmapped** (THEA) | THEA 1S | ENGL 15/ENGL 15A/ENGL 30H; CAS 100 | — | 3 |
| Turfgrass Science, B.S. | **unmapped** (TURF) | PLANT 150S | ENGL 15/ENGL 30H/ESL 15 | — | 5 |
| Veterinary and Biomedical Sciences, B.S. | ANSC 494H | — | ENGL 15/ENGL 30H; CAS 100A/CAS 100B/CAS 100C | — | 14 |
| Wildlife and Fisheries Science, B.S. | WFS 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | BIOL 220W; BIOL 240W | 11 |
| Wildlife and Fisheries Science, B.S. — Fisheries | WFS 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | BIOL 220W; BIOL 240W | 11 |
| Wildlife and Fisheries Science, B.S. — Wildlife | WFS 494H | — | ENGL 15/ENGL 30H/ESL 15; CAS 100A/CAS 100B/CAS 100C/CAS 100 | BIOL 220W; BIOL 240W | 11 |
| Women's, Gender, and Sexuality Studies, B.A. | WMNST 494H | LA 283, WMNST 83S | ENGL 15; CAS 100 | — | 5 |
| Women's, Gender, and Sexuality Studies, B.S. | WMNST 494H | LA 283, WMNST 83S | ENGL 15; CAS 100 | — | 5 |
| Workforce Education and Development, B.S. | **unmapped** (WFED) | — | ENGL 15; CAS 100A | — | 5 |
| World Languages (K-12) Education, B.S. | FR 494H | — | ENGL 15 | — | 4 |
| World Languages (K-12) Education, B.S. — French Teaching | FR 494H | — | ENGL 15 | — | 4 |
| World Languages (K-12) Education, B.S. — German Teaching | GER 494H | — | ENGL 15 | — | 4 |
| World Languages (K-12) Education, B.S. — Latin Teaching | **unmapped** (LATIN) | — | ENGL 15; CAS 100A | — | 5 |
| World Languages (K-12) Education, B.S. — Russian Teaching | RUS 494H | — | ENGL 15; CAS 100A | — | 5 |
| World Languages (K-12) Education, B.S. — Spanish Teaching | **unmapped** (SPAN) | — | ENGL 15 | — | 4 |