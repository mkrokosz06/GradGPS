# Multi-school copy layer — design

Status: **design only, not implemented** (2026-08-11). Scope decision below.

GradGPS is Penn State–only today, with plans to add schools. This doc designs the
**copy/config layer** — how user-facing text stops hardcoding "Penn State" /
"LionPATH" and instead reads from a per-school config object, so adding a school's
*wording* becomes a config entry rather than a string hunt.

This is deliberately the *copy* slice of the larger multi-school effort. It does
**not** cover the functional PSU couplings (transcript parser layout, RMP school ID,
catalog loader, UP-scoping denylist, gen-ed pools) — those are tracked separately and
gate what a new school can actually *do*. Copy can run slightly ahead of function, but
must never promise what the backend can't yet deliver (see "Guardrail" below).

---

## Scope decision (agreed)

- **App copy → config layer**, defaulted to `psu`. Durable refactor; sets up the real
  backend `school_id` work. **Deferred** — this doc is the plan, not the change.
- **User-record `school` field / onboarding school picker** — deferred. Until it
  exists, config resolves to a hardcoded `psu` default, so the refactor is invisible
  but ready.
- **Marketing website** → **stays Penn State–specific** for now. Revisit when a real
  second school exists (a school picker / variant landing for an audience of one
  school isn't worth it). The website has no user context and can't be per-user
  anyway.

---

## The config object

One entry per school. Every piece of app copy reads a field off the active school.

```ts
// mobile/constants/schools.ts  (proposed)
export type School = {
  id: string;              // "psu" — stable key, matches backend school_id
  name: string;            // "Penn State"          → "Your {name} degree, mapped."
  shortName: string;       // "PSU"                 → "Unofficial {shortName} transcript"
  university: string;      // "Penn State University" (account subtitle)
  sisName: string;         // "LionPATH"            → upload steps, hero note
  sisSteps: string[];      // exact numbered upload instructions (SIS-specific)
  emailDomain: string;     // "psu.edu"             → "abc1234@{emailDomain}"
  hasProfessorRatings: boolean; // gates the RMP course→professor search copy
};

export const SCHOOLS: Record<string, School> = {
  psu: {
    id: "psu",
    name: "Penn State",
    shortName: "PSU",
    university: "Penn State University",
    sisName: "LionPATH",
    sisSteps: [
      "Log in to LionPATH",
      "Academic Records → View Advising Transcript",
      "Save as PDF",
    ],
    emailDomain: "psu.edu",
    hasProfessorRatings: true,
  },
};

export const DEFAULT_SCHOOL_ID = "psu";
```

Resolution helper (single choke point; swap the body when school-on-user lands):

```ts
// today: always psu. later: read user.school ?? DEFAULT_SCHOOL_ID
export const activeSchool = (): School => SCHOOLS[DEFAULT_SCHOOL_ID];
```

Keeping `sisSteps` as an array (not one interpolated string) matters — a different
school's SIS has a different click path, not just a different name. `name` vs
`university` are split because the copy uses both forms ("Penn State major" vs "Penn
State University").

---

## App string inventory → mapping

Every hardcoded PSU reference in the app and the field that replaces it:

| File | Current string | Reads |
|------|----------------|-------|
| `app/(tabs)/index.tsx` | "Your Penn State degree, mapped." | `{name}` |
| `app/(tabs)/account.tsx` | "Penn State University" | `{university}` |
| `app/(tabs)/major.tsx` | "Search for your Penn State program." | `{name}` |
| `app/(tabs)/major.tsx` | "Search Penn State majors…" | `{name}` |
| `app/onboarding/major.tsx` | "Search for your Penn State program." | `{name}` |
| `app/onboarding/signup.tsx` | "Penn State email" label | `{name}` |
| `app/onboarding/signup.tsx` | `abc1234@psu.edu` placeholder | `{emailDomain}` |
| `app/(tabs)/support.tsx` | `you@psu.edu` placeholder | `{emailDomain}` |
| `app/(tabs)/upload.tsx` | LionPATH steps + "Unofficial PSU transcript" | `{sisSteps}`, `{shortName}` |
| `app/onboarding/upload.tsx` | LionPATH steps + "Unofficial PSU transcript" | `{sisSteps}`, `{shortName}` |
| `app/(tabs)/upload.tsx` | official-transcript alert ("…OFFICIAL Penn State…") | `{name}`, `{sisName}` |
| `app/onboarding/upload.tsx` | same official alert | `{name}`, `{sisName}` |
| `app/course/[code].tsx` | "No Penn State professors found for …" | `{name}` (guard on `hasProfessorRatings`) |

Note `constants/api.ts` already models "config that varies by build" (`API_BASE`,
client IDs) — `schools.ts` sits naturally beside it.

---

## Guardrail: copy must not outrun function

`hasProfessorRatings` is the pattern for this. `rmp_client.py` is keyed to PSU's
RateMyProfessors school ID; a new school with `hasProfessorRatings: false` should hide
the professor-search UI entirely, not show "No {name} professors found" for a feature
that can't work. Same principle applies later to any SIS whose transcript layout the
parser doesn't yet understand — the config can name the SIS, but the upload flow
should gate on a real "parser supports this school" capability, not just a label.

(Per house style, none of this copy names RateMyProfessors — "professor ratings".)

---

## What this unlocks / what still blocks a second school

**Unlocked by this refactor:** adding a school's *wording* = one `SCHOOLS` entry.

**Still required before a second school is real** (out of scope here, tracked in the
multi-school expansion notes):
1. `school` field on the user record + onboarding step to set it (this doc's deferred
   half). `activeSchool()` becomes `SCHOOLS[user.school ?? DEFAULT_SCHOOL_ID]`.
2. `school_id` partition on `requirements` / catalog data so audits scope to a school.
3. Transcript parser that understands the new SIS's PDF layout.
4. RMP school ID (or disable ratings) + gen-ed model + UP-scoping equivalent.
5. Website treatment (neutral copy / picker / variant) — decided when school #2 is
   named.

---

## Implementation sketch (when picked up)

1. Add `mobile/constants/schools.ts` (config + `activeSchool()`), default `psu`.
2. Replace the 13 mapped strings above with `activeSchool()` reads. Pure refactor —
   output is byte-identical while only `psu` exists, so it's safely shippable alone.
3. Gate `course/[code].tsx` professor search on `hasProfessorRatings`.
4. (Later) add `school` to the user record + onboarding picker; point `activeSchool()`
   at it.
