# credentials/ — minor & certificate catalog repair (Phase 0)

Self-contained workspace for the **Phase 0** data repair in `docs/minors-certificates.md`.
Nothing here is wired into the running app yet: `backend/` is untouched, the picker filter
in `routers/programs.py` still hides minors and certificates, and no student can declare one.

The deliverable is `credential_requirements.json` — a trustworthy, git-diffable requirement
set for PSU's University Park minors and certificates — plus the `dept_credits` evaluator
the audit engine will need to read it.

## Why a new parser

`backend/scripts/scrape_psu.py` reads a bulletin page as *text* and only resets its group
state on an `<h2>`–`<h5>` heading (`scrape_psu.py:195`). Credential pages carry **one**
heading and put all their structure inside a single `table.sc_courselist`, so:

1. one stray "Select one of the following:" leaked into every later table, and unpaired
   `choose_one` rows are evaluated as *individually required* (`audit_engine.py:1655`) —
   *Arts Entrepreneurship, Minor* came out demanding **660 credits**;
2. requirement rows with no course code were dropped by the `code_match` guard
   (`scrape_psu.py:243`) — *Psychology, Minor* lost the "Select 11 credits … in PSYCH" row
   and came out as 7 of its real 18 credits.

PSU's CourseLeaf markup is fully semantic, so this parser reads the classes instead:

```
tr.areaheader      section boundary       ("Prescribed Courses")   ← the missing reset
tr.areasubheader   constraint prose       ("Require a grade of C or better")
tr > td.codecol    a course row           (td.hourscol holds the credits)
tr.orclass         alternative of the row above
tr (no codecol)    a requirement sentence ("Select 11 credits … in PSYCH")
tr.listsum         CourseLeaf's own "Total Credits" footer — skipped
```

Same approach as `scripts/scrape_sap.py`, which parses `table.sc_plangrid` deterministically
rather than guessing from text.

## Files

| File | Purpose |
|---|---|
| `pools.py` | Parses a "Select N credits …" sentence into a `PoolSpec`. The key call is **enumerable vs departmental** — see below. Pure. |
| `courseleaf.py` | Walks `table.sc_courselist` and emits requirement groups. Pure: HTML in, groups out. |
| `validate.py` | `validate()` -> (blockers, warnings) + `credit_range()`. Mirrors `plan_templates.validate_template()`. |
| `verify.py` | Independent check against PSU's own published credit total — the only signal that catches a well-formed but wrong parse. |
| `dept_credits.py` | The `dept_credits` evaluator, plus the three-line wiring note for `audit_engine.py`. |
| `scrape_credentials.py` | CLI: discover → fetch (cached) → parse → validate → write JSON. |
| output | **`../backend/credential_data/credential_requirements.json`** — written directly to the backend's bundled data dir so there is only ever one copy. One entry per credential. |
| `tests/` | 31 tests over saved bulletin HTML; runs offline. |
| `.cache/` | Downloaded pages, so re-runs need no network. Safe to delete. |

## Running it

```bash
python scrape_credentials.py --dry-run --report     # parse + health table, write nothing
python scrape_credentials.py --report               # writes credential_requirements.json
python scrape_credentials.py --only psychology      # one credential, for debugging
python scrape_credentials.py --refresh              # re-download instead of using .cache/

python tests/test_credentials.py                    # or: python -m pytest tests/
```

## Where it landed

207 University Park credentials (154 minors, 53 certificates); the ~55 non-UP ones are
dropped by **URL college slug**, not by name — credential names rarely carry a campus
parenthetical (*Business, Minor* has none but lives under `/colleges/university-college/`),
so `is_up_program()`'s name test alone would have leaked them.

**Supported: 207 / 207 (100%), zero quarantined.** Split deliberately, because
"supported" is not the same as "audited end to end":

| | count | |
|---|---|---|
| audited end to end | **154 (74%)** | every requirement is machine-evaluable |
| + a student-confirmed part | **53 (26%)** | median 6 cr the bulletin defers to an adviser |

### Accuracy: 204 / 205 agree with PSU's own number

Structural validation only proves a parse is *well-formed*, never that it is *right* —
*Environmental Inquiry, Minor* passed every structural check while reconstructing to
**510 credits**. Catching that needs a source of truth outside our own parse, and PSU
publishes one on nearly every page (`verify.py`):

| source | pages |
|---|---|
| `table.tbl_programrequirements` — a "Program Requirements" table | 154 |
| prose — "…a minimum of N credits is required" | 51 |
| no total published | 2 |

**Every credential that states a total agrees with our reconstruction, except one.**
*Worklink Strategies and Employability, Certificate* reconstructs to 3-36 cr against a
stated 42; its table lists three repeatable 1-12 credit seminars that cannot reach 42, so
the page under-specifies itself. That is a PSU data problem, not a parser one.

This check runs in `--report` on every pass. It is the only signal that catches a parse
which is well-formed and wrong, and it found every real bug after the first round.

A secondary yardstick — PSU Senate policy, which puts a minor at 18-21 credits — now
sits at **90%** (139/154), up from 75%. The seven minors outside even 15-24 (Meteorology
at 39 cr, Electrochemical Engineering at 35) **all agree with PSU's own stated totals**:
they are genuinely large minors, not parse errors. That is exactly why the policy band is
a warning and never withholds support.

### The bugs the verification exposed

Structural validation caught none of these. Each is a distinct way a page can be shaped:

| Symptom | Cause |
|---|---|
| Environmental Inquiry: 510 cr | Seven cluster *reference* tables after the requirements table were folded in as requirements |
| Environmental Engineering: 11 cr | Its first table is **"Entrance to Minor"** — admission criteria, not coursework |
| Environmental Inquiry: 292 cr | A pool option that stated its own credits closed the pool, dumping the other 79 options into the prescribed block |
| Food Systems: 177 cr | A bare category label inside a list ("Agricultural and Environmental Sciences:") ended the option run, so 53 options became required |
| Dispute Management: 27 cr | A sub-pool with a blank credits cell was counted on top of the parent that already declared 12 |
| Agribusiness: 24 cr | Same, for `choose_courses` — the type was handled before the sub-pool check |
| Geophysics: 42 cr | A section that branches by student type lists every branch; the header's own stated total is authoritative |
| **15 credentials, ~3 cr each** | **Cross-listed codes (`AFAM/WMNST 101N`, `PHIL 132/RLST 131`), co-requisite pairs (`ANSC 207 & ANSC 208`) and hyphenated subjects (`A-I 305`) did not match the code regex, so those rows were dropped silently** |
| Computer Engineering: 18 vs 19 | `choose_one` pairs were valued at a flat 3 cr; CMPEN 270 is 4 |
| International Engineering: 12 cr | A requirement with no verb and no number ("Demonstrate language skills…", 6 cr) was read as a heading |
| One Health: 7 vs 13 cr | Same, for two 3-credit rows ("Environment or Climate Elective") |
| Presidential Leadership: 5 cr | Variable-credit courses ("HONOR 401, 1-6") counted at the low end only |

The dropped-code-cell bug was the worst of them: it removed real requirements from 15
credentials with no warning of any kind, and only the credit-total comparison revealed it.

Tables are now selected by the **heading they sit under** (`requirements for the
minor/certificate`), not by position — position was wrong in both directions.

## The two pool kinds

**Enumerable** — the options are the rows that follow, marked by a trailing colon.
Becomes `choose_credits` / `choose_courses`, which the audit engine already understands.

**Departmental** — a rule over the catalog, not a list. Becomes `dept_credits`, a new group
type (`dept_credits.py`), structurally the sibling of `_eval_writing_intensive()`
(`audit_engine.py:1234`), which likewise evaluates a *designation* rather than a course list.
Handles: single subject (`in PSYCH`), multi-subject (`from ACCTG, BA, … or STAT`), level
floors and ranges (`400-level ANSC`, `the ANTH 400-489 range`, `ENGL 200 - ENGL 299`),
exclusions (`except ANTH 1`), and the "at least N credits at the L level" sub-constraint,
which gates satisfaction — 11 credits of 100-level PSYCH does not complete the Psychology minor.

## What is deliberately NOT done here

- **`backend/audit_engine.py` is not modified.** `dept_credits.evaluate()` returns exactly the
  shape `_eval_choose_credits()` returns, and the three-line dispatch patch is written out at
  the bottom of `dept_credits.py`. It belongs with Phase 2, when credentials are actually audited.
- **No loader.** Writing these rows into the `requirements` table is Phase 1/2 work; the JSON
  is the reviewable artifact and the review should happen before anything reaches DynamoDB.
- **No discovery of new credentials.** Program URLs come from the existing
  `PSU_Major_Requirements.xlsx`; the old scrape found every credential page, it just parsed
  them wrong. A fresh crawl belongs with the next full catalog refresh.

## Next

1. **Two credentials publish no total at all** (Carbon Capture Utilization and Storage;
   Climate and Environmental Change) and *Worklink* disagrees because its own page
   under-specifies. Those three are the only ones no automated check can vouch for.
2. **Decide how the 53 partly-adviser-defined credentials present in the app.** The data
   is ready: each carries `manual_credits` and `unstructured_credits` groups holding the
   bulletin's exact wording. The design question is UI — most likely a slot the student
   fills with the class-selector picker, reusing `user_course_choices` the way the
   substitution flow already does, labelled as the student's own declaration.
3. Then Phase 1 in `docs/minors-certificates.md`: `users.credentials`,
   `GET /programs/credentials`, `PUT /users/me/credentials`, the Account card, and the
   major-screen pointer.

## Re-running this later

`--report` prints the agreement figure every time, so a PSU page edit that breaks a parse
shows up as a drop in that number rather than as a wrong plan in a student's timeline.
Run `--refresh` to re-download, and check the agreement line before trusting the output.
