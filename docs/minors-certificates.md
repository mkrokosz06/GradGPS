# Minors & Certificates

**Status:** planned. Today minors and certificates are *hidden*, not supported —
`is_degree_program()` in `backend/routers/programs.py` filters them out of the picker and
`POST /programs/select` refuses one. This doc is the plan to make them real.

**Shape of the feature:** a student declares a minor or certificate **from the Account page**
(never in the signup flow — onboarding stays "one major, one transcript, done"), and the timeline
reflows to include the credential's remaining courses. The major screen carries a one-line pointer
to Account so the student knows where to go.

Throughout this doc, **credential** = a minor or a certificate (anything the catalog labels with a
non-degree `degree` value).

---

## 1. Why this is a data problem before it is a code problem

The catalog already contains **265 credential programs** (262 of them University Park: 195 minors +
67 certificates), 4,847 rows. The scraper (`scripts/scrape_psu.py`) treats a minor page like a major
page, and minor pages are laid out differently — mostly prose plus one flat course table with no
per-section headings. The result does not survive contact with `run_audit()`:

| Defect | Count | Consequence |
|---|---|---|
| `choose_one` rows with **no `pair_group_id`** | 1,627 of 1,883 | `_eval_choose_one()` treats unpaired rows as **individually required** (`audit_engine.py:1655`). "Business, Minor" is 43 unpaired rows in one group → a phantom **43-course** minor. |
| Programs that are a single unpaired `choose_one` blob (>3 rows) | 41 of 265 | Same failure, systematically. |
| Programs with **fewer than 3 rows** total | 21 | "Psychology, Minor" is 2 rows (PSYCH 100, PSYCH 301W). The real minor is 18 credits — the 12 elective credits were never scraped, so it would read as **nearly complete on day one**. |
| Rows with a blank `credits` value | 3,987 of 4,847 (82%) | Credit totals in a credential audit are guesses; the timeline falls back to 3 cr per slot (`_display_credits`). |
| Junk `course_title` (a credit count scraped as a title) | 212 | Cosmetic, already repairable by `scripts/fix_junk_titles.py`. |
| Missing `group_threshold` on `choose_credits` | 0 | The one thing that is clean. |

The failure is **bidirectional** — some credentials over-require, some under-require — which rules
out a single blanket heuristic. **Phase 0 below is not optional.** Shipping the UI on this data
would tell a student their minor is done when it isn't.

---

## 2. Data model

One new attribute on the existing `users` row — no new table, so no prod IAM change
(prod DynamoDB is per-table scoped; see the class-selector note in `CLAUDE.md`):

```
credentials: [ {"program": "Information Sciences and Technology, Minor", "kind": "minor"}, … ]
```

- A list, not a scalar: students genuinely stack two minors, or a minor and a certificate.
- `kind` is denormalized from the catalog `degree` at declare time so the UI can group and label
  without a catalog read.
- **Cap at 3** (`MAX_CREDENTIALS`). Same reasoning as `MAX_PER_USER` on substitutions: it is a
  student's declaration about themselves, and an uncapped list is a way to make the timeline
  meaningless.
- Absent/empty = today's behavior exactly. Every code path below must be a byte-identical no-op
  when the list is empty — that is the safety property that lets this ship to live beta users.

---

## 3. Backend

### 3.1 `routers/programs.py` — classify instead of filter

Refactor the predicate shipped in the hide-only change:

```python
def program_kind(name: str, degrees: set[str]) -> str:   # "degree" | "minor" | "certificate"
is_degree_program(name, degrees) -> program_kind(...) == "degree"   # keep as a thin wrapper
```

`_load_all_programs()` already scans `program_name` + `degree`; have it populate **two** caches
(`_programs_cache`, `_credentials_cache`) in the same pass — no extra scan.

New endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /programs/credentials?q=` | Search minors/certificates. Returns `[{name, kind}]`, sorted, UP-scoped via the existing `is_up_program()`. |
| `PUT /users/me/credentials` | Replace the whole list (idempotent — no add/remove race). Validates each: exists in the catalog, `program_kind != "degree"`, ≤ 3, no duplicates, and **not equal to the student's major**. |

Put the mutation on `users.py`, not `programs.py`: it writes the user row, and `programs.py` should
stay the catalog-scoping module. `GET /users/me` returns the list so Account can render before the
audit lands.

### 3.2 `audit_engine.py` — no changes

This is the point of the design. `run_audit()` is already pure: rows in, result out. A credential
audit is the *same function* over a different `program_name`'s rows and the *same* transcript.
Nothing in the engine needs to know credentials exist.

### 3.3 `routers/audit.py` — one extra audit per credential

After the existing `run_audit()` call (`audit.py:195`), loop the declared credentials:

```python
result["credentials"] = [
    {"program": c["program"], "kind": c["kind"],
     **run_audit(_filter_rows(rows_for(c["program"]), None, taken_codes),
                 transcript_courses, declared_subs)}
    for c in user.get("credentials", [])
]
```

Notes:
- `_filter_rows(..., subplan=None, ...)` still applies — it drops campus/suggested-plan duplicate
  groups. Credentials have no subplan concept; `_pick_best_option` is a no-op on a single-group
  program (`len(option_groups) <= 1` → return unchanged).
- Cost: one extra `requirements_table.query` per credential (cap 3). The transcript, gen-ed rows,
  and substitutions are already in hand — do **not** re-read them.
- Declared substitutions apply to credentials for free, since they go through the same
  `_build_taken()` choke point.

### 3.4 Double-counting policy — decide explicitly, enforce nothing at first

PSU's actual rule varies by department (commonly "at most 6 credits may double count between a
major and a minor"), and the catalog does not encode it. Running each credential as an independent
audit means a course counts for both. **That is the right v1**: it matches what students assume, and
the alternative (a shared `consumed` set across programs) would arbitrarily pick which program loses
a course. Surface it in the UI as *"counted toward both"* rather than silently, and revisit only if
a beta report demands it. Gen-ed cross-group exclusivity is unaffected — that lives entirely inside
`run_gen_ed_audit()`.

### 3.5 `routers/timeline.py` — merge credential slots into the plan

The credential's missing courses have to land in future semesters. Both timeline paths need it, and
they need it differently.

**Layer 1 (packer) — easy.** `_collect_missing()` already takes an audit result and returns flat
slots. Call it once per credential, tag each slot `{"credential": "<program name>"}`, and extend
`named_courses` / `raw_pools` in `_build_layer1_future()` (`timeline.py:759`) before packing.
De-dupe against the major's slots by course code — the existing `seen_codes` set in
`_collect_missing()` is per-call, so the merge needs its own pass. The credit-band packer then
absorbs the extra load naturally, adding semesters when 15 cr/term can't hold it.

**SAP template path — the real work.** `_reflow_template()` emits the major's official plan; a minor
is not in it. Options, in order of preference:

1. **Fill elective slots first.** The template already carries `elective` slots that
   `match_template()` fills from leftovers. A credential course is exactly the kind of thing a
   student's free electives are *for*. Route credential slots into unfilled `elective` slots by
   position, then overflow to option 2. Highest-fidelity, most work.
2. **Append + rebalance.** Distribute the remainder across post-current semesters up to
   `_MAX_CREDITS`, extending the plan by a term when it overflows.

Ship 2 first, then 1 — 2 is correct-but-blunt, and it makes the feature real while the harder
version is built. Either way, credential slots must carry a stable `slot_key`
(`cred:<program>:<code>`) so the class selector's pin/swap machinery works on them unchanged.

**Response:** add `"credentials": [{program, kind, remaining_credits}]` to the timeline summary so
the mobile app can badge credential courses on the timeline and home cards.

---

## 4. Mobile

### 4.1 Account page — where you declare it (`app/(tabs)/account.tsx`)

A **"Minors & Certificates"** card directly below the existing MAJOR card (`account.tsx:100`), same
visual language (`#f0f4ff` fill, `#dbeafe` border):

- Empty state: `+ Add a minor or certificate` and one line of explanation — *"Declaring one adds its
  remaining courses to your timeline."*
- Populated: one row per credential — name, `MINOR`/`CERTIFICATE` chip, an `x of y requirements
  done` line from `audit.credentials[]`, and a `✕` to remove.
- Tapping add opens a search modal reusing the `major.tsx` search pattern against
  `GET /programs/credentials`. `components/CredentialPickerModal.tsx` — a modal, not a route, since
  the tab bar is hidden and this is a sub-flow of Account.
- Save → `PUT /users/me/credentials` → refetch audit → the timeline reflows on next focus.

New `services/credentialService.ts` (`searchCredentials`, `setCredentials`), matching
`substitutionService.ts` in shape.

### 4.2 Major screen — the pointer (`app/(tabs)/major.tsx`)

A static note under the search bar (`major.tsx:203`), muted, not a control:

> **Have a minor or certificate?** Add it in **Account** — your timeline updates to include it.

Also worth putting on the "Major Saved" confirmation screen (`major.tsx:161`), which is the moment a
student is most likely to be thinking about their credentials.

### 4.3 Timeline / home

Credential-sourced course cards get a small chip with the credential's short name (`IST Minor`), so
a student can see *why* a course they didn't expect is in their plan. Reuse the `EDITED`-badge
pattern from `upload.tsx`.

---

## 5. Phasing

Each phase is shippable and independently useful. Phases 1–2 are display-only: a wrong credential
audit shows a wrong **number**, not a wrong **plan** — that's the cheap way to find out how bad the
data is with real students.

| Phase | Scope | Gate to the next phase |
|---|---|---|
| **0. Catalog repair** | `scripts/audit_credential_catalog.py` — per-credential health report (row count, unpaired `choose_one` blobs, missing credits, threshold sanity). Re-scrape credential pages with a minor-aware parser; hand-fix or **quarantine** what still fails. A quarantined credential simply stays out of the picker — the same fail-safe direction the current filter uses. | A known-good list. Do not proceed on all 262. |
| **1. Declare + store** | `credentials` on the user row, `GET /programs/credentials`, `PUT /users/me/credentials`, Account card, major-screen note. No audit, no timeline. | Students can declare; nothing downstream moves. |
| **2. Credential audit** | `result["credentials"]` in `GET /audit`; progress line on the Account card. | Numbers look right against a handful of real beta transcripts. |
| **3. Timeline merge** | Layer 1 merge + SAP append/rebalance (option 2). Credential chips on cards. | The plan is right for a templated *and* an un-templated major. |
| **4. Polish** | SAP elective-slot routing (option 1), "counts toward both" double-count labeling, credit-total accuracy. | — |

---

## 6. Risks / open questions

- **Catalog quality is the whole risk.** Phase 0 may reveal that a minor-aware scrape is
  substantially new parsing work rather than a tweak. Budget for that; the quarantine escape hatch
  means partial coverage still ships.
- **Certificates may deserve to be dropped from v1.** 67 of them, thinner data than minors, and far
  fewer students. Cheap to defer — it is one `kind` filter.
- **Timeline length.** A student declaring a minor late may push graduation out a semester. That is
  *true* and worth showing, but it should be surfaced deliberately ("adding this adds a semester"),
  not as a silent extra term appearing in the plan.
- **Re-upload.** A transcript re-upload wipes `transcript_courses` but must **not** wipe
  `credentials` — they live on the user row, so this is free, but it needs a test
  (`DELETE /users/me` should of course clear them).
- **Older mobile builds** ignore the new response fields, so `credentials` must stay strictly
  additive to `/audit` and `/timeline`.
