# App Store Connect submission — GradGPS

Working document for the operator (Matthew Krokosz, solo developer). Written 2026-09-21,
updated 2026-09-23 to record what was actually submitted.

## Status — submitted for review (2026-09-23)

| | |
|---|---|
| Version / build | **1.1.0 (build 10)** — EAS build `441b46de-050c-45b5-a931-3c84e6b23101`. Build 9 is identical except for the app icon (see §6). |
| Demo account in prod | `REVIEW_EMAIL=appreview@gradgps.com` and `REVIEW_CODE` set on App Runner 2026-09-22 (value **not** in the repo). Seeded with `seed_demo_account.py`: 27 courses, 6 terms, 67.5 credits, Computer Engineering B.S. Verified against prod: right code → session, wrong code → 401, the code against any other address → 401. |
| Screenshots | 6.5" slot, 1242 × 2688, flattened to RGB (ASC rejects PNGs with an alpha channel). |
| Release | Manual release after approval. |

**While review is pending:** pushes to `main` deploy straight to the backend the reviewer is
using. Do not touch `_review_account()` in `routers/email_auth.py`, do not unset either env var,
and do not re-seed or delete the demo account.

**After approval:** rotate `REVIEW_CODE` (`aws apprunner update-service`, fresh six digits) —
the current value has been in App Store Connect and in local submission files.

A rejection arrives as a Resolution Center message; fix and resubmit, nothing is lost.

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

**ASC caps this field at 4,000 characters.** The first draft was 5,871 and would not paste; the
version below is what was submitted (3,594). It keeps every guideline
argument — 2.1 (why a demo account exists), 5.2.2 (rights to catalog data), 4.8 (Sign in with
Apple), 5.1.1(v) (deletion) — and drops the longer factual-vs-creative elaboration and the
RateMyProfessors removal note. `<REVIEW_CODE>` stands in for the real code, which is deliberately
not in the repo.

```
WHAT GRADGPS IS

GradGPS turns a college student's transcript into a degree audit and a
semester-by-semester plan to graduation.

THE APP NEEDS A TRANSCRIPT TO SHOW ANYTHING

Every meaningful screen is generated from an uploaded transcript plus a selected
major; a brand-new account shows an empty state. So you do not need a university
login, we seeded a demo account that already has a major and a full transcript.

DEMO ACCOUNT (no university login required)

  On the sign-in screen choose "Continue with Email"
  Email: appreview@gradgps.com
  Code:  <REVIEW_CODE>

This is passwordless email sign-in with a fixed code for this one account, so no
email has to be delivered and no Google or Apple account is needed.

WHAT TO TAP

1. Launch, tap "Get Started".
2. Age gate: tap "I Confirm". The app requires users to be 13+, matching our
   Terms and Privacy Policy.
3. "Continue with Email", enter the email above, then the code. You land on Home.
4. HOME: the greeting names the major; below it is the current/next-semester
   registration dashboard, each class tagged Required / Gen Ed / Elective.
5. TIMELINE: hamburger menu (top left) -> "Timeline". Past semesters from the
   transcript, then every remaining semester through graduation, credit-balanced
   and in prerequisite order.
6. COURSE DETAIL: tap any course card for title, credits and description.
7. CLASS PICKER: on a Timeline card marked "Gen Ed" or showing "N options", tap
   it to see the real courses that satisfy that slot. Picking one updates the plan.
8. ACCOUNT: hamburger menu -> "Account". Credits Done / In Progress / Remaining,
   the declared major, and "Minors & Certificates" (declare one and the Timeline
   absorbs the extra courses).
9. UPLOAD: hamburger menu -> "Upload Transcript".

TESTING UPLOAD YOURSELF

A sample unofficial transcript PDF is attached to this submission
(demo_transcript.pdf). Tap "Upload Transcript" and pick it from the Files app.
Note that re-uploading replaces the demo account's transcript; please use a
throwaway account if you want the demo data left intact.

RIGHTS TO THE DATA (5.2.2)

GradGPS is an independent project by one student developer. It is NOT affiliated
with, endorsed by or sponsored by The Pennsylvania State University, and says so
in the Terms of Use, the Privacy Policy and the App Store description.

The course and program information is factual academic catalog data - course
codes, titles, credit values and requirement lists - published publicly on the
university's own bulletin site (bulletins.psu.edu), which needs no login and
exists for public consultation. We reproduce no logos, seal, brand assets or
marketing text, use no university trademark in the app name, icon or subtitle,
and claim no affiliation. The app accesses no university account, portal or
private system: the student supplies their own transcript file. The app is not
built on any third party's private or licensed API.

SIGN IN WITH APPLE (4.8)

Implemented and offered alongside Google and email sign-in. The native Apple
button shows on device (TestFlight / App Store builds). Apple ID tokens are
verified server-side against Apple's JWKS. No password is ever collected.

ACCOUNT DELETION (5.1.1(v))

Hamburger menu -> "Account" -> "Delete Account" -> confirm. One confirmation, no
email or support ticket. It permanently deletes the stored transcript PDF, every
parsed course row, every saved planning choice, pinned class and adviser
substitution, the user profile, and every session token.

SUPPORT

In-app Contact Support (hamburger menu), or https://gradgps.com/support
```

ASC labels the sign-in fields "Username" / "Password"; the code goes in "Password". The app has
no passwords — the Notes explain that, which is why the step list stays near the top.

> **Accuracy check on the deletion paragraph.** `DELETE /users/me` in
> `backend/routers/users.py` deletes, in order: (1) the S3 object
> `transcripts/<user_id>/transcript.pdf`; (2) all `transcript_courses` rows for the user;
> (3) all `user_course_choices` rows — which is where pinned class choices, adviser
> substitutions (`sub:` namespace) and credential attestations live; (4) the `users` row;
> (5) all `sessions` rows for the user, best-effort (any straggler resolves to a profile-less
> identity and expires via the 30-day TTL). If S3 is unreachable the endpoint returns 502 and
> deletes nothing else, so a "deleted" response always means the PDF is gone. Do **not** claim
> deletion is instant across backups — the wording above only claims what the code does.

> **The review attachment** is `backend/scripts/demo_assets/demo_transcript.pdf` — wholly
> synthetic, parses 27/27 with no Unknown terms, and scores −5 on the official detector so it
> cannot trip the 409 consent dialog mid-review.

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

**1,757 characters.** The first draft (all-caps section headers, a bolded feature list)
read as machine-written and was replaced. What was entered in ASC:

```
GradGPS turns a college transcript into a plan for graduating.

Upload your unofficial transcript and choose your major. GradGPS reads what you've already taken, checks it against every requirement in your program, and shows what's done, what's in progress, and what's left. Then it lays the remaining classes out semester by semester - in prerequisite order, with a realistic credit load each term, and following your program's published suggested plan where one exists.

The home screen shows the classes to register for next, so you know what to sign up for without opening the full plan.

You can declare up to three minors or certificates and see the extra coursework folded into the same timeline. For a general education slot or an elective, a picker lists the courses that actually count so you can choose one instead of leaving a placeholder. If your department approved a course substitution, you can record it and the plan updates. And if you add or drop a class for the term you're registered in, you can change it without re-uploading your transcript.

Tap any course to see its title, credit value, and official description.

GradGPS currently supports degree programs, minors, and certificates at Penn State's University Park campus. More schools are being added.

GradGPS is an independent project and is not affiliated with, endorsed by, or sponsored by any university. Requirement data comes from publicly published course bulletins. It's a planning tool, not academic advising - confirm with your adviser before you register.

There are no ads and no analytics. You can delete your transcript, or your entire account, from the Account screen at any time.

Terms: gradgps.com/terms
Privacy: gradgps.com/privacy
Support: gradgps.com/support
```

The body is deliberately school-neutral ("your program", "any university"), but the coverage line
naming University Park **stays** — the app only has that catalog, and implying broader support is
a 2.3.1 problem. It is the one line to edit as schools are added.

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
- [x] **Content rights:** "Does your app contain, show, or access third-party content?"
      → **Yes**, with the rights attestation. It has to be Yes: the course screen shows PSU's
      course descriptions verbatim, which is prose, not bare fact. There is no free-text box;
      the justification lives in the Review Notes. If 5.2.2 is ever pushed on, the description
      text is the weak point and a short factual summary would be the fix.
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

- [x] **iPhone screenshots.** ASC offered the **6.5"** slot and accepted 1242 × 2688 (the size an
      XS Max / 11 Pro Max produces). 6.9" would be 1320 × 2868 or 1290 × 2796.
- **ASC rejects any PNG with an alpha channel**, even a fully opaque one. Raw device screenshots
      are RGB; alpha usually arrives via a design tool or a device-frame template. Flatten onto
      white before upload (PIL: paste onto an `RGB` canvas using the alpha as the mask).
- **13" iPad — NOT required.** `ios.supportsTablet` was set to `false` on 2026-09-21, which
      removes the iPad screenshot requirement and avoids shipping an untested tablet layout. This
      is native config, so it takes effect only in a new production build — not over OTA. Reversible:
      flip it back to `true` and the iPad screenshots become mandatory again.
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
  version. Submitted as **1.1.0**; only the build number moved (9, then 10).
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
      on the App Runner service. Done 2026-09-22: both set, account seeded, and the path
      checked against prod (see Status).
- [ ] Confirm the *ordinary* email sign-in code still arrives for real users. **SES production
      access is granted** (verified 2026-09-21 via `aws sesv2 get-account`: `ProductionAccessEnabled:
      true`, 50,000/day, status HEALTHY), so codes deliver to any inbox — the sandbox warning that
      used to sit in `email_auth.py` was stale and has been corrected. If a user ever reports never
      receiving a code, check the SES suppression list first (it suppresses on bounce/complaint).

### Operator placeholders to resolve

| Placeholder | Where |
|---|---|
| ~~Demo email / sign-in code~~ — **done**: set on App Runner 2026-09-22, account seeded | §1 review notes |
| ~~Sample transcript PDF~~ — **done**: `backend/scripts/demo_assets/demo_transcript.pdf` (synthetic, parses 27/27) | §1, ASC attachment |
| ~~Reviewer contact~~ — **done**, entered in ASC | ASC App Review Information |
| Sign-in-SDK third-party-label question | §2.2 |
| 13+ age-rating question wording in the 2025 questionnaire | §3 |
| ~~iPad screenshots~~ — **done**: `supportsTablet: false` | §5 |
| ~~SES sandbox status~~ — **done**: production access granted | §5 smoke test |
| ~~Version number~~ — **done**: 1.1.0 (build 10) | §5 |

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

### RESOLVED — app icon had transparent corners

`mobile/assets/icon.png` was a pre-rounded RGBA image: fully transparent corners, 4.6% of pixels
non-opaque. Apple requires the 1024 marketing icon to have no alpha. Flattened 2026-09-22
(`9fb43ae`) by extending the icon's own navy gradient into the corners — compositing onto white
would leave visible wedges. The Android adaptive-icon layers keep their alpha; they need it.

**It was not the cause of the blank icon in App Store Connect**, which is what prompted it. Build
10's icon showed next to the build while the large app-level icon stayed blank: that one fills
from a build *attached to a version*, and on a never-approved app it can stay generic until first
approval. Inspecting a built IPA does not answer the alpha question either — Xcode rewrites icons
into Apple's CgBI PNG variant, whose header reports `RGBA` regardless and which PIL cannot decode.
Check the source file instead.

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
