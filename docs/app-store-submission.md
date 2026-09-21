# App Store Connect submission — GradGPS

Working document for the operator (Matthew Krokosz, solo developer). Everything below is
grounded in the repo as of 2026-09-21. Placeholders are marked `[LIKE THIS]` — fill them in
before submitting; do not guess.

## 0. Facts pulled from the repo

| Thing | Value | Source |
|---|---|---|
| Display name | `GradGPS` | `mobile/app.json` → `expo.name` |
| Bundle ID | `com.gradgps.app` | `mobile/app.json` → `expo.ios.bundleIdentifier` |
| Marketing version | `1.1.0` | `mobile/app.json` → `expo.version` (and `mobile/package.json`) |
| Build number | auto-incremented by EAS | `mobile/eas.json` → `build.production.autoIncrement: true`, `cli.appVersionSource: "remote"` |
| App Store Connect app ID | `6803643612` | `mobile/eas.json` → `submit.production.ios.ascAppId` |
| EAS project ID | `5edc93c4-d727-45f2-ad80-38dee65c0f33` | `mobile/app.json` → `expo.extra.eas.projectId` |
| Sign in with Apple | enabled | `expo.ios.usesAppleSignIn: true`, plugin `expo-apple-authentication` |
| Export compliance | already declared exempt | `expo.ios.infoPlist.ITSAppUsesNonExemptEncryption: false` |
| iPad support | **OFF** | `expo.ios.supportsTablet: false` (set 2026-09-21) — no iPad screenshots required |
| Production API | `https://kjn2ysmnjr.us-east-1.awsapprunner.com` | `mobile/.env.production` |
| Support email | `support@gradgps.com` | `mobile/app/privacy.tsx`, `mobile/app/tos.tsx` |

Public policy pages (GitHub Pages serves these without the `.html`):
`https://gradgps.com/privacy`, `https://gradgps.com/terms`, `https://gradgps.com/support`.
The same text ships in-app at `mobile/app/privacy.tsx` and `mobile/app/tos.tsx`, reachable from
the hamburger menu footer (`mobile/components/NavHeader.tsx`) and from onboarding.

---

## 1. App Review notes (free-text "Notes" field)

Paste this into **App Review Information → Notes**. Fill the placeholders first.

```
WHAT GRADGPS IS

GradGPS turns a college student's academic transcript into a degree audit and a
semester-by-semester plan to graduation. The student uploads their unofficial
transcript PDF, picks their major, and the app shows what requirements are done,
what is in progress, and which classes are left to take and when.

IMPORTANT: THE APP NEEDS A TRANSCRIPT TO SHOW ANYTHING

Every meaningful screen (timeline, audit, registration dashboard) is generated from
an uploaded transcript plus a selected major. A brand-new account with no transcript
shows an empty state. So that you do not need a Penn State student login, we have
seeded a demo account that already has a major and a full transcript loaded.

DEMO ACCOUNT (no university login required)

  Sign-in method: "Continue with Email" on the sign-in screen
  Email:  [DEMO EMAIL — default is appreview@gradgps.com; confirm the value of
           REVIEW_EMAIL on the production server]
  Code:   [DEMO SIGN-IN CODE — the REVIEW_CODE env var on the production
           server; it is deliberately not stored in the repo]

  (This account uses the app's passwordless email sign-in with a fixed code, so
  no email has to be delivered and no Google or Apple account is required. Enter
  the email, tap continue, then type the code above.)

STEP BY STEP — WHAT TO TAP

  1. Launch the app. Tap "Get Started".
  2. Age gate: tap the confirm button ("I'm 13 or older"). The app requires users to
     be at least 13; this matches our Terms and Privacy Policy.
  3. On the sign-in screen choose "Continue with Email", enter the demo email above,
     then enter the code. You land on the Home screen.
  4. HOME: the greeting names the student's major, and below it is the
     current/next-semester registration dashboard — the classes to register for,
     each tagged (Required / Gen Ed / Elective). This is the app's main screen.
  5. TIMELINE: tap the hamburger menu (top left) -> "Timeline". This is the full
     academic plan: past semesters from the transcript, then every remaining
     semester through graduation, credit-balanced and in prerequisite order.
  6. COURSE DETAIL: on the Home or Timeline screen, tap any course card. A detail
     screen opens with the course title, credit value, and the official course
     description.
  7. CLASS PICKER: on a Timeline card marked "Gen Ed" or showing an "N options"
     button, tap it — a picker opens listing the real courses that satisfy that
     slot. Picking one updates the plan.
  8. DEGREE AUDIT / ACCOUNT: hamburger menu -> "Account". Shows credits Done /
     In Progress / Remaining, the declared major, and the "Minors & Certificates"
     card (tap it to declare one and watch the Timeline absorb the extra courses).
  9. UPLOAD FLOW: hamburger menu -> "Upload Transcript" to see the upload screen and
     the parsed transcript, grouped by semester.

TESTING THE UPLOAD FLOW YOURSELF

A sample Penn State unofficial transcript PDF is attached to this submission as a
review attachment: [SAMPLE TRANSCRIPT FILE NAME — attach the PDF in App Review
Information -> Attachment]. Tap "Upload Transcript", choose to select a PDF, and pick
that file from the Files app. Note: re-uploading replaces the demo account's existing
transcript; we can restore the demo data by re-running our seed script, so please use
a second throwaway account if you want the demo data left intact.

INDEPENDENCE FROM PENN STATE / RIGHTS TO THE DATA (guideline 5.2.2)

GradGPS is an independent project built by one student developer. It is NOT
affiliated with, endorsed by, sponsored by, or approved by The Pennsylvania State
University, and the app says so in three places: the Terms of Use (Section 2, "Not
affiliated with Penn State"), the Privacy Policy (Section 1), and the App Store
description.

The course and program information in the app is factual academic catalog data —
course codes, course titles, credit values, and degree requirement lists — published
publicly by the university on its own public bulletin website (bulletins.psu.edu),
which requires no login and is intended for public consultation by prospective and
current students. Factual catalog listings of this kind are not creative expression.
We do not reproduce the university's logos, seal, brand assets, or copyrighted
marketing text, we do not use any university trademark in the app name, icon, or
subtitle, and we make no claim of affiliation. The app does not access any Penn State
account, portal, or private system: the student supplies their own transcript file
from their own records.

The app is not built on any third party's private or licensed API. (A professor
ratings feature that called a third-party endpoint was removed from the app in
September 2026 and is not present in this build.)

ACCOUNT CREATION AND SIGN IN WITH APPLE (guideline 4.8)

Sign in with Apple is implemented and offered on the sign-in screen alongside
Google Sign-In and passwordless email sign-in. On device (TestFlight / App Store
builds) the native Apple button is shown. Apple ID tokens are verified server-side
against Apple's JWKS. No password is ever collected or stored.

ACCOUNT DELETION (guideline 5.1.1(v))

In-app account deletion: hamburger menu -> "Account" -> scroll to the bottom ->
"Delete Account" -> confirm in the alert. It is a single confirmation, with no email
or support ticket required.

It permanently deletes: the stored transcript PDF in object storage; every parsed
transcript course row; every saved planning choice, pinned class, and adviser
course-substitution; the user profile record (name, email, major, subplan, declared
minors/certificates); and every active session token, which signs the user out
everywhere. See backend/routers/users.py, DELETE /users/me.

SUPPORT

support@gradgps.com, or the in-app Contact Support screen (hamburger menu ->
"Contact Support").
```

> **Accuracy check on the deletion paragraph.** `DELETE /users/me` in
> `backend/routers/users.py` deletes, in order: (1) the S3 object
> `transcripts/<user_id>/transcript.pdf`; (2) all `transcript_courses` rows for the user;
> (3) all `user_course_choices` rows — which is where pinned class choices, adviser
> substitutions (`sub:` namespace) and credential attestations live; (4) the `users` row;
> (5) all `sessions` rows for the user, best-effort (any straggler resolves to a profile-less
> identity and expires via the 30-day TTL). If S3 is unreachable the endpoint returns 502 and
> deletes nothing else, so a "deleted" response always means the PDF is gone. Do **not** claim
> deletion is instant across backups — the wording above only claims what the code does.

> **One thing the notes do not claim:** there is **no transcript PDF checked into this
> repository**. The sample must be exported from LionPATH (or redacted from a real one) by the
> operator and attached in ASC. Do not point the reviewer at a file that does not exist.

---

## 2. Privacy nutrition labels (App Privacy section)

**Two global answers first.**

- **Do you or your third-party partners use data for tracking?** → **No.**
  Verified: `mobile/package.json` contains no analytics, attribution, advertising, or
  crash-reporting SDK of any kind (no Firebase, Sentry, Amplitude, Mixpanel, Segment,
  AppsFlyer, Facebook SDK). The only network client is `axios` talking to our own backend.
  Because nothing is used for tracking, **App Tracking Transparency does not apply** and no
  `NSUserTrackingUsageDescription` is needed.
- **Is data sold or shared with data brokers?** → **No.** Stated in the Privacy Policy
  ("We do not sell or share your personal information").

### 2.1 The labels to declare

For every row below: **Used for Tracking = No**, and **Linked to the User = Yes** (all of it is
stored on a row keyed by the account identifier).

| Apple data category | Apple data type | Collected? | Purposes to check | Why this classification |
|---|---|---|---|---|
| Contact Info | **Name** | Yes | App Functionality | Google/Apple/email sign-in supplies a display name, written to the `users` row (`backend/routers/users.py`, `upsert_me`). Apple sends the name only on first authorization; the app captures it there. |
| Contact Info | **Email Address** | Yes | App Functionality, **Customer Support** | Stored on the `users` row from the verified token; also collected by the support form (`backend/routers/support.py`) and used as the passwordless sign-in identity (`backend/routers/email_auth.py`). |
| Identifiers | **User ID** | Yes | App Functionality | The canonical account id is provider-scoped: `google:<sub>`, `apple:<sub>`, `email:<address>` (`backend/auth.py`, `backend/routers/email_auth.py`). It is our own identifier, not a device identifier. |
| User Content | **Customer Support** | Yes | Customer Support | The free-text message and email address a user sends from the Contact Support screen. It is emailed to the operator via SES and, when the user is signed in, carries their user id. |
| User Content | **Other User Content** | Yes | App Functionality | The uploaded transcript **PDF file itself**, stored in S3. See §2.2 — this is the row that covers the file's full contents. |
| Usage Data | **Product Interaction** | Yes | App Functionality, **Analytics** | `backend/client_meta.py` stamps `last_seen` (the date of last app use) and `app_version` on the user row, throttled to about one write per user per active day. Used for the in-app update gate (App Functionality) and for an aggregate build-distribution chart on the operator's admin dashboard (Analytics). Declare **both** purposes — the admin chart is analytics even though no SDK is involved. |
| **Other Data** | **Other Data Types** | Yes | App Functionality | The academic data itself: parsed course codes, grades, credits earned, enrollment terms, the selected major and subplan, declared minors/certificates, pinned future classes, and adviser course substitutions. Describe it in the free-text box as: *"Academic transcript and degree-progress information (courses, grades, credits, terms, declared major and minors) that the user uploads or enters, used only to generate their degree audit and course plan."* |

### 2.2 Reasoning you may have to defend

**Why transcript data is "Other Data", not something else.** Apple's taxonomy has no
"Education" type. Walk the list: it is not Contact Info, not Financial Info, not Health &
Fitness, not Location, not Browsing/Search History, and it is not *Usage Data* (Apple defines
that as interaction with the app or its advertising, which is what `last_seen` / `app_version`
are — not the content of a transcript). Apple's **Sensitive Info** type is a closed list —
racial or ethnic data, sexual orientation, pregnancy, disability, religious or philosophical
beliefs, trade union membership, political opinion, genetic information, biometric data — and
academic records are on none of it. "Other Data Types" is the residual bucket Apple provides
exactly for this, and Apple lets you name it in free text. **Declare it.** It is the most
sensitive thing the app holds, and under-declaring is the failure mode that gets a build
rejected or pulled later.

**Why the PDF gets its own "User Content → Other User Content" row.** The parsed academic
fields and the raw file are different collections with different exposure. The stored PDF is a
document the user chose to upload; if it is an **official** transcript it may also contain the
student's printed name and Penn State student ID number, which the app never parses or uses but
does store inside the file. Declaring the file as User Content is the honest way to cover
whatever else is printed on it, and it matches what the Privacy Policy already says (§2 and §8,
"Sensitive personal information"). If ASC's UI pushes you to pick only one of these two rows,
keep **Other Data** and describe the PDF inside its free text.

**Why the student ID number is not declared as an Identifier.** The app does not extract,
index, transmit, or key anything on it — `backend/transcript_parser.py` reads course rows only.
It is incidental content of a file the user uploaded, covered by the User Content row above. If
a reviewer asks: we recommend the *unofficial* transcript precisely to avoid it, the app detects
an official transcript and asks the user to confirm before accepting it
(`backend/routers/transcript.py`, the 409 consent gate), and the file is deletable in one tap.

**Why IP address is not declared.** IP is read from `X-Forwarded-For` only to apply a sliding
in-memory rate-limit window on sign-in codes and support messages
(`backend/routers/email_auth.py`, `backend/routers/support.py`). It is never written to
DynamoDB and never linked to an account. Apple's App Privacy rules let you omit data collected
solely for fraud prevention or security that is not used for tracking, analytics, advertising,
or personalization, and is not stored beyond the request. That is exactly this case, and the
Privacy Policy says so in plain words. **If you would rather not argue it:** declare
`Identifiers → Device ID`, Linked = **No**, purpose **App Functionality**. Over-declaring is
always safe; under-declaring is not.

**Why "Purchases", "Location", "Contacts", "Photos", "Health" are all No.** There is no IAP,
no location API, no contacts access, and the file picker (`expo-document-picker`) returns only
the single document the user chooses — it grants no library access and needs no usage-description
string. Confirm before submitting that `mobile/app.json` still declares no
`NSPhotoLibraryUsageDescription` / `NSLocationWhenInUseUsageDescription`; it currently does not,
and shipping a usage string for a capability you don't use is itself a rejection cause.

**One thing to verify, not assume.** `[VERIFY: whether the sign-in SDKs you bundle
(expo-auth-session, expo-apple-authentication) count as third-party partners needing their own
labels. They should not — they perform authentication only, the provider's own privacy policy
governs their side, and the Privacy Policy already discloses them under "Third-Party Services".]`

---

## 3. Age rating

Answer the content questionnaire honestly — every content question is **None** for this app:

| Questionnaire topic | Answer |
|---|---|
| Cartoon or Fantasy Violence | None |
| Realistic Violence / Prolonged Graphic Violence | None |
| Profanity or Crude Humor | None |
| Mature / Suggestive Themes | None |
| Horror / Fear Themes | None |
| Sexual Content or Nudity | None |
| Alcohol, Tobacco, or Drug Use or References | None |
| Simulated Gambling / Contests | None |
| Medical / Treatment Information | None |
| **Unrestricted Web Access** | **No** — a web view opens only for the Google OAuth consent page (`expo-web-browser` / `expo-auth-session`). There is no general-purpose browser and no user-enterable URL. |
| **User-Generated Content** | **No** — nothing a user writes is shown to any other user. The support form is a private message to the operator. |
| In-app purchases / loot boxes | None |

**Resulting content rating: 4+.**

**But do not list it as 4+.** Your own policies assert a **13+ minimum**
(`website/terms.html` §4 "Who can use the Service"; `website/privacy.html` §10 "Age Requirement
& Children's Privacy"), and onboarding enforces it with a real gate
(`mobile/app/onboarding/age.tsx` — an "I'm under 13" answer dead-ends and refuses to create an
account; the attestation is stored via `services/ageAttestation`). An App Store listing that
says 4+ while the app refuses under-13 users is an inconsistency a reviewer can act on, and a
4+ rating invites Kids-adjacent scrutiny that a transcript-collecting app should not attract.

**Recommendation: list the app at 13+.** Apple's 2025 questionnaire added 13+/16+/18+ bands and
asks whether the app is intended for, or restricted to, a minimum age — answer that question
with **13**. Do **not** enrol in the Kids Category under any circumstances: it forbids collecting
personal information from children, and this app collects a name, an email, and an academic
record.

`[VERIFY IN THE LIVE ASC QUESTIONNAIRE: Apple revised the age-rating flow in 2025. Confirm the
exact wording of the minimum-age / age-assurance question and that answering it yields a listed
rating of 13+. If the questionnaire offers no route from all-None content answers to 13+, accept
the computed rating and add one line to the Review Notes stating that the app enforces a 13+
minimum in onboarding per its Terms.]`

---

## 4. Listing metadata

Character counts are exact, computed on the strings as written below.

### App name — limit 30

```
GradGPS: Degree Planner
```

**23 characters.** GradGPS leads. No university name anywhere in it.

Alternates (same rule): `GradGPS` (7 characters), `GradGPS — Degree Roadmap` (24 characters).

### Subtitle — limit 30

```
Your transcript to graduation
```

**29 characters.**

Alternates: `Map your classes to graduation` (30 — exactly at the limit, zero slack),
`Plan every semester to grad` (27).

> **Hard constraint honoured:** neither the name nor the subtitle contains "Penn State", "PSU",
> "Nittany", "Lion", or any university mark. Per the prior trademark review, university
> references appear only later in the description, trailing and purely descriptive
> ("currently supports University Park degree programs … at Penn State"), never as branding and
> never implying endorsement. Keep it that way through every future metadata edit.

### Promotional text — limit 170

```
Upload your transcript, pick your major, and see exactly what is left: a full degree audit plus a semester-by-semester plan built from your school's published catalog.
```

**167 characters.** Promotional text can be changed at any time without a new build — useful for
term-start messaging later.

### Keywords — limit 100, comma-separated, no spaces after commas

```
degree,audit,transcript,graduation,college,major,minor,schedule,credits,planner,courses,advisor,GPA
```

**99 characters.** Deliberately omits "Penn State" and "PSU": a trademarked term in the keyword
field is a common 5.2.2 rejection and would contradict the name/subtitle rule above. Words
already in the app name and subtitle are indexed automatically, so they are not repeated here.

### Description — limit 4000

**2,088 characters.**

```
GradGPS turns your college transcript into a clear plan for graduating.

Upload your unofficial transcript, pick your major, and GradGPS builds a degree audit and a semester-by-semester timeline: what you have finished, what you are taking now, and exactly what is left. No spreadsheets, no guessing which requirement a class actually filled.

WHAT YOU GET

- Degree audit. Every major requirement and General Education category, checked against the classes on your transcript.
- Semester timeline. Your remaining requirements laid out term by term, credit-balanced and in prerequisite order, following your program's published suggested plan where one exists.
- Registration view. Next semester's classes on the home screen, so you know what to sign up for.
- Minors and certificates. Declare up to three and see the extra coursework folded into your plan.
- Class picker. For a General Education slot or an elective, browse the courses that actually count and pin the one you want.
- Course detail. Title, credits, and the official course description.
- Adviser substitutions. If your department approved a swap, tell GradGPS and the plan updates.
- Manual edits. Added or dropped a class for the term you are registered in? Change it without re-uploading anything.

WHO IT COVERS

GradGPS currently supports University Park degree programs, minors, and certificates at Penn State. More schools are on the way.

HONEST ABOUT WHAT IT IS

GradGPS is an independent project built by a student developer. It is not affiliated with, endorsed by, or sponsored by The Pennsylvania State University. Requirement data comes from the university's publicly published bulletin. GradGPS is a planning aid, not academic advising: always confirm with your adviser before you register.

YOUR DATA

Your transcript is yours. No ads, no analytics SDKs, nothing sold or shared. Delete your transcript, or your entire account and everything in it, from the Account screen at any time.

Terms of Use: https://gradgps.com/terms
Privacy Policy: https://gradgps.com/privacy
Support: https://gradgps.com/support
```

Every feature claim above is implemented: degree audit (`backend/audit_engine.py`), timeline
(`backend/routers/timeline.py` + `backend/sap_templates/`), registration dashboard
(`mobile/app/(tabs)/index.tsx`), minors capped at three (`MAX_CREDENTIALS = 3` in
`backend/routers/users.py`), class picker (`mobile/components/CoursePickerModal.tsx`), course
detail (`mobile/app/course/[code].tsx`), substitutions (`backend/routers/substitutions.py`),
manual class edits (`POST`/`PATCH`/`DELETE /transcript/course`). Do not add a claim here that
isn't implemented — guideline 2.3.1 is about exactly that.

---

## 5. Submission checklist

### In App Store Connect — app information

- [ ] **Category:** Primary `Education`. Secondary `Productivity` (optional).
- [ ] **Content rights:** answer "Does your app contain, show, or access third-party content?"
      → **Yes**, described as *publicly published university course catalog information; no
      licence required.* (Consistent with the Review Notes in §1.)
- [ ] **Copyright field:** `2026 Matthew Krokosz` (year + name only — no "©", ASC adds it).
- [ ] **Support URL:** `https://gradgps.com/support` — **required**. Confirm the page loads and
      its contact form actually posts to production before submitting.
- [ ] **Marketing URL** (optional): `https://gradgps.com`
- [ ] **Privacy Policy URL:** `https://gradgps.com/privacy` — **required**.
- [ ] **App Review Information:** first name, last name, phone number, email, the demo-account
      credentials from §1, and the sample transcript PDF as an attachment.
- [ ] **Sign-in required:** tick "Sign-in required" and supply the demo email + code.
- [ ] **Age rating questionnaire** — §3.
- [ ] **App Privacy** labels — §2. These are published separately from the build and must be
      complete before the app can be submitted at all.

### Export compliance

- [x] `ITSAppUsesNonExemptEncryption: false` is already set in `mobile/app.json` →
      `ios.infoPlist`. This pre-answers the per-build export question; the app uses only
      HTTPS / standard OS cryptography. Nothing further to do unless you add custom crypto.

### Screenshots — the item most likely to block you

- [ ] **6.9" iPhone** (iPhone 16 Pro Max / 15 Pro Max class) — **required**. 1320 × 2868 px or
      1290 × 2796 px, portrait. Up to 10; supply at least 3.
- **13" iPad — NOT required.** `ios.supportsTablet` was set to `false` on 2026-09-21, which
      removes the iPad screenshot requirement and avoids shipping an untested tablet layout. This
      is native config, so it takes effect only in a new production build — not over OTA. Reversible:
      flip it back to `true` and the iPad screenshots become mandatory again.
- 6.5" iPhone screenshots are no longer separately required; ASC scales the 6.9" set down.
- Suggested set, matching the description's ordering: Home / registration dashboard → Timeline
  → Course detail → Account with credit progress → Class picker.
- [ ] **Do not reuse `website/shots/*.png`** as App Store screenshots — see §6.

### Build and submit

From the `mobile/` directory:

```bash
# 1. Production build (signs with your Apple distribution cert, builds on EAS)
eas build --platform ios --profile production

# 2. Submit the finished build to App Store Connect
#    (ascAppId 6803643612 is already in eas.json, so no extra flags are needed)
eas submit --platform ios --profile production --latest
```

Notes on those commands:

- `eas.json` sets `cli.appVersionSource: "remote"` and `build.production.autoIncrement: true`,
  so the **build number** increments on EAS automatically. The **marketing version** (`1.1.0`)
  comes from `mobile/app.json` and must be bumped by hand if this submission should be a new
  version. `[DECIDE: submit as 1.1.0, or bump the version first?]`
- The production build reads `mobile/.env.production`, pointing the app at the live App Runner
  backend. Verify `EXPO_PUBLIC_API_BASE` is present before building — without it the app falls
  back to a LAN address and the reviewer sees nothing but network errors.
- After the build appears in ASC, attach it to the version, then **Add for Review** →
  **Submit for Review**.
- JS-only fixes after approval can ship via `eas update --branch production` without a new
  review. Native config changes (including `supportsTablet`) cannot.

### Pre-submit smoke test against production

- [ ] Install the exact build from TestFlight and run the reviewer's script in §1 end to end.
- [ ] Sign in with Apple on a real device (the native button does not render in Expo Go or on
      web — `AppleAuthentication.isAvailableAsync()` gates it).
- [ ] Sign in with the demo email account exactly as a reviewer would.
- [ ] Delete Account on a throwaway account; confirm it signs out and the data is gone.
- [ ] **Sign in as the reviewer will**, with `REVIEW_EMAIL` + `REVIEW_CODE`, against the live
      production backend — not a local one. The review sign-in path in
      `backend/routers/email_auth.py` is env-gated, so it only works once both variables are set
      on the App Runner service. `[VERIFY: REVIEW_EMAIL and REVIEW_CODE are set in production,
      and seed_demo_account.py has been run against production so the account has a major and a
      transcript.]`
- [ ] Confirm the *ordinary* email sign-in code still arrives for real users. **SES production
      access is granted** (verified 2026-09-21 via `aws sesv2 get-account`: `ProductionAccessEnabled:
      true`, 50,000/day, status HEALTHY), so codes deliver to any inbox — the sandbox warning that
      used to sit in `email_auth.py` was stale and has been corrected. If a user ever reports never
      receiving a code, check the SES suppression list first (it suppresses on bounce/complaint).

### Operator placeholders to resolve

| Placeholder | Where |
|---|---|
| `[DEMO EMAIL]` (`REVIEW_EMAIL`, default `appreview@gradgps.com`) and `[DEMO SIGN-IN CODE]` (`REVIEW_CODE`, never in the repo) | §1 review notes — set on the production server; account seeded by `backend/scripts/seed_demo_account.py` |
| ~~Sample transcript PDF~~ — **done**: `backend/scripts/demo_assets/demo_transcript.pdf` (synthetic, parses 27/27) | §1, ASC attachment |
| Reviewer contact name / phone / email | ASC App Review Information |
| Sign-in-SDK third-party-label question | §2.2 |
| 13+ age-rating question wording in the 2025 questionnaire | §3 |
| ~~iPad screenshots~~ — **done**: `supportsTablet: false` | §5 |
| ~~SES sandbox status~~ — **done**: production access granted | §5 smoke test |
| Version number to submit (1.1.0 or bumped) | §5 |

---

## 6. Rejection risks found in the repo

### ~~HIGH~~ RESOLVED — the dead "Tap for ratings" label

The live app told users to tap a course for ratings, a feature withdrawn in September 2026
(`docs/professor-ratings.md`) — a broken promise under **2.3.1** and **2.1**, and a visible
reminder in the shipping binary of the exact feature removed for a third-party terms violation.

Fixed 2026-09-21: both strings now read "Tap for course details". A full grep of `mobile/` found
no other remnant — no ratings service, type, or endpoint reference survives. The tap handler was
left alone; the rows still route to `mobile/app/course/[code].tsx`. **Needs a new build to reach
users.**

### HIGH — `website/shots/app-timeline.png` shows the withdrawn feature

The marketing screenshot on gradgps.com still displays the "Tap for ratings" label. If any App
Store screenshot is generated from this asset — or if a reviewer visits the support / marketing
URL you supply and sees a feature the app doesn't have — that is 2.3.3 (screenshots must show the
app in use) and 2.3.1. **Re-capture all three `website/shots/*.png` from the fixed build**, and
never use website assets as App Store screenshots.

### ~~MEDIUM~~ RESOLVED — `mobile/assets/favicon.png` was the default Expo chevron

1,129 bytes, untouched since project init. Referenced only by `expo.web.favicon`, so it never
shipped in the iOS binary and could not by itself cause a rejection — but it was the visible
favicon of any Expo web export. Regenerated 2026-09-21 from `mobile/assets/icon.png`
(48×48 RGBA, Lanczos).

### ~~MEDIUM~~ RESOLVED — iPad support

`ios.supportsTablet` was `true`, making iPad a supported device (mandatory 13" screenshots, and a
reviewer running an untested tablet layout — 2.1 / 4.0). Set to `false` on 2026-09-21. Nothing in
the repo depended on tablet support. **Native config: needs a new build, not OTA.**

### ~~MEDIUM~~ RESOLVED — ordinary email sign-in delivery (SES)

`email_auth.py` used to warn that SES delivers only to verified recipients until production access
is granted, which would have made email sign-in a dead path — **guideline 2.1**, the most common
first-submission rejection. The warning was stale. Verified 2026-09-21 via `aws sesv2 get-account`:
`ProductionAccessEnabled: true`, `SendingEnabled: true`, 50,000/day, `EnforcementStatus: HEALTHY`.
Codes deliver to any inbox. The docstring has been corrected.

### LOW — dormant RateMyProfessors code is still in the repo

`backend/rmp_client.py` and `backend/scripts/build_rmp_index.py` remain, imported by nothing and
scheduled by nothing. They are server-side and ship in no binary, so guideline 2.3.1's "dormant
features" language does not reach them through the app. No action needed for this submission —
but do not wire them back up. `docs/professor-ratings.md` has the full rationale.

### LOW — the "Charlie" add-my-school router

`backend/charlie.py` mounts only when `CHARLIE_ENABLED=1`, which production never sets, so
`/charlie/*` does not exist in prod and the mobile app does not call it. Nothing to disclose.

### LOW — legacy dev-bypass endpoints

`POST /users/create` and the spoofable `x-user-id` header path are gated behind
`AUTH_DEV_BYPASS`, which is off in production (`x-user-id` → 401). Confirm that is still true on
the live App Runner service before submitting — a spoofable auth header reachable in production
would be a security finding, not merely a review problem.
