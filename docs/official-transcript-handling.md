# Official-Transcript Detection, Consent & Handling — Implementation Doc

## Context

GradGPS currently only handles PSU **unofficial** transcripts (LionPATH browser-print PDFs). When a student uploads an **official** transcript instead, the current parser does **not** cleanly reject it — validated against a real 4-page digitally-signed official transcript, it returned **13 mangled, partly-wrong courses** with every term marked `Unknown`. This feature adds: (1) a scored heuristic to detect official transcripts server-side (validated, robust), (2) a consent gate that warns the user and lets them confirm or cancel, and (3) a **dedicated official-layout parser** so an acknowledged official transcript is parsed correctly rather than stored garbled.

> **Approach change vs. the original plan:** the original assumed official transcripts yield 0 courses → clean rejection. Real-sample validation disproved this (see Parsing findings below). The former "Phase 2" dedicated parser is therefore **folded into Phase 1**: detected-official uploads are routed to a purpose-built parser, with a safety net that falls back to the reject message if the parse looks untrustworthy.

## Prerequisites

- Backend, Docker (DynamoDB local + MinIO), and the seed scripts are already runnable per `CLAUDE.md` (§ "Running the project"). Assume you can `docker-compose up -d`, seed, and run uvicorn on `:8080`.
- Test user `matthew-test-001`, dev bypass (`AUTH_DEV_BYPASS=1`) accepts the `x-user-id` header — use it for all curl verification.
- A real unofficial transcript PDF is available (the seed uses one).
- **A real signed official transcript sample exists and was used to validate this doc.** Several implementation steps (column boundary, watermark band) must be tuned by inspecting that sample — do not hardcode blindly. **Do not commit the sample or any PII** (name, SSN, student ID, birthdate); use sanitized/synthetic fixtures in tests.

---

## Validated findings (from a real 4-page signed official transcript, Aerospace Engineering BS)

### Detection — robust, net score ≈ 9 vs. threshold 4

| Finding | Result |
|---|---|
| `/ByteRange` byte marker | **HIT** — reliable anchor |
| `adbe.pkcs7` byte marker | **HIT** — reliable anchor |
| `/AcroForm` byte marker | HIT (corroborating) |
| `/Type/Sig` (**no space**) | present in the PDF, but the original doc's `/Type /Sig` **with a space MISSED** — see Step 1 correction |
| Header "Undergraduate Official Transcript" (per page) + "End of Undergraduate Official Transcript" | **HIT** — `(?<!UN)OFFICIAL\s+TRANSCRIPT` matches. Header wording is now **verified** (the old "unverified" caveat is removed). |
| Registrar language ("Office of the University Registrar", "University seal", "…, University Registrar" signature line) | HIT — capped +2 |
| "Statement of Authenticity" / "Parchment" / "digitally signed" | **ABSENT** — these are Parchment *eTranscript* markers; the printed "Copy of Transcript" style lacks them. Demote to optional bonus signals, not primary. |
| `UNOFFICIAL` veto | correctly did **not** fire (word absent) |

### Parsing — the current parser produces garbage on official layout

1. **Two-column layout.** The official prints two terms side-by-side. pdfplumber reads left-to-right across both columns, so two different courses collide on one physical text line.
2. **Watermark corruption.** A vertical "Copy of Transcript" watermark is overlaid *through* the course table; pdfplumber splices its individual letters into course text. Real examples: `PHYS 211` → `PHYSip 211`; `EDSGN 100 Cornerstone` → `EDSGN 100 C D o sg rn n erstone Eng`; `Course Description` → `Courrse ip Description`. Many courses dropped entirely.
3. **Term detection fully fails.** Official uses **full season names** — "Fall 2025", "Spring 2026", "Summer 2024" — but the parser's term regex only matches the abbreviated "FA 2025" form. Every course came back `term="Unknown"`.

---

### Known risks (called out inline at the relevant steps)

- **(a) Detection is robust and verified** — the certified-PDF byte signals (`/ByteRange` + `adbe.pkcs7`) are the reliable anchor and trigger on their own; the header wording is confirmed. No remaining wording uncertainty.
- **(b) The two-column de-interleaver + watermark stripper is built from ONE sample and is fragile.** Different students have different term counts, and the column boundary / watermark band may shift. Validate against 2–3 more official samples before prod. **Safety net (mandatory):** if the official parser yields suspiciously few courses OR many `Unknown` terms, **fall back to the reject message** rather than storing a bad result. See Step 3 (official parser) and Step 4 (router).
- **(c) The existing mobile error handler will render `[object Object]`.** The 409 `detail` is now an object, not a string. A `typeof detail === "string"` guard is mandatory in both `upload.tsx` screens. See Step 6.

---

## Implementation Steps

Steps are ordered so each is independently testable and the build never breaks. Backend Steps 1–4 are shippable and verifiable via curl before any mobile change.

### Step 1 — New file: `backend/official_detector.py`

**Create** a standalone detector module. No dependencies on the parser or router (import-safe, unit-testable).

**Shape:**

```python
from dataclasses import dataclass

THRESHOLD = 4  # score >= THRESHOLD  => is_official

@dataclass
class OfficialDetection:
    is_official: bool
    score: int
    confidence: float          # round(min(max(score, 0) / 8, 1.0), 2)
    signals: list[str]         # names of signals that fired (for logging + response)

# PSU-specific text signals kept in one list so per-school variants slot in later
# (see MEMORY.md multi-school note). The byte-signature signal is school-agnostic.
def detect_official(pdf_bytes: bytes, full_text: str) -> OfficialDetection: ...
```

**Signal table (implement exactly — corrected from real-sample validation):**

| Signal name | Weight | Test |
|---|---|---|
| `pdf_digital_signature` | **+4** | Raw-byte scan of `pdf_bytes` (no text needed): **`b"/ByteRange" in pdf_bytes and b"adbe.pkcs7" in pdf_bytes`**. Both CONFIRMED present in the real sample. **CORRECTION:** do **not** test `b"/Type /Sig"` — the real PDF contains `/Type/Sig` with **no space**, so the spaced form misses. `/ByteRange`+`adbe.pkcs7` are the reliable anchor; optionally OR-in `b"/AcroForm"` as corroboration only. This alone hits threshold. |
| `official_header` | **+3** | `re.search(r"(?<!UN)OFFICIAL\s+TRANSCRIPT", full_text, re.I)`. **Verified** against literal header "Undergraduate Official Transcript". Negative lookbehind ensures "UNOFFICIAL TRANSCRIPT" never matches. |
| `registrar_language` | **+1 per phrase, capped at +2** | phrases (case-insensitive): `Office of the University Registrar`, `University seal`, `University Registrar`, `Family Educational Rights and Privacy Act`, `FERPA`. All confirmed present. |
| `authenticity_statement` | **+1 (bonus, optional)** | any of (case-insensitive): `Statement of Authenticity`, `Parchment`, `digitally signed`. **CORRECTION:** these were **ABSENT** from the printed sample (they are Parchment eTranscript markers). Demoted from +2 primary to +1 bonus — never rely on them. |
| `unofficial_marker` | **−5** (hard veto) | `UNOFFICIAL` present, or `not an official transcript` present. Did not false-fire on the sample. |

`score = sum of fired weights`. `is_official = score >= THRESHOLD`. On the real sample: 4 + 3 + 2 = **9**. `signals` lists fired signals (including `unofficial_marker` when it vetoes, for logs).

**CLI stanza** (mirror `transcript_parser.py`'s `__main__`): read a PDF path from `sys.argv[1]`, extract text with pdfplumber, call `detect_official`, print `is_official`, `score`, `confidence`, `signals`.

**How to verify:**
```bash
cd backend
python official_detector.py path/to/unofficial.pdf   # is_official=False, unofficial_marker fired
python official_detector.py path/to/official.pdf      # is_official=True, score ~9
```

---

### Step 2 — Refactor `backend/transcript_parser.py`: extract text once + full-name term support

**Goal:** extract page text exactly once so detection and parsing share it, and prepare for a two-parser split.

1. **Extract** a top-level function from the current head of `parse_transcript`:
   ```python
   def extract_pages_text(pdf_bytes: bytes) -> list[str]:
       with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
           return [page.extract_text() or "" for page in pdf.pages[:MAX_PAGES]]
   ```
2. **Change** `parse_transcript` to accept pre-extracted text (backward compatible) — this remains the **unofficial** parser:
   ```python
   def parse_transcript(pdf_bytes: bytes, *, pages_text: list[str] | None = None) -> list[dict]:
       if pages_text is None:
           pages_text = extract_pages_text(pdf_bytes)
       full_text = "\n".join(pages_text)
       ...  # unchanged parse logic
   ```
3. **Add full-name term support** so the official parser (Step 3) reuses it. Add a mapping + a second regex + a normalizer:
   ```python
   _FULL_SEASON = {"Fall": "FA", "Spring": "SP", "Summer": "SU"}
   FULL_TERM_PATTERN = re.compile(r"\b(Fall|Spring|Summer)\s+(20\d{2})\b")
   # normalize either "FA 2025" or "Fall 2025" -> internal "FA 2025"
   ```

**How to verify:**
```bash
cd backend
python -c "from transcript_parser import parse_transcript; \
print(len(parse_transcript(open('path/to/unofficial.pdf','rb').read())),'courses')"
# expect same course count as before the refactor (no regression on unofficial)
```

---

### Step 3 — New: dedicated official-layout parser + `parse_and_detect()`

**File:** `backend/transcript_parser.py` (or a new `backend/official_parser.py` imported by it — engineer's choice; keep `parse_and_detect` as the single entry point).

#### 3a. `parse_official_transcript(pdf_bytes) -> list[dict]`

Returns the same dict shape as `parse_transcript` (`course_code`, `raw_code`, `grade`, `credits_earned`, `term`, `status`, `is_writing`). Approach — implement concretely:

1. **Word-level extraction.** Use `page.extract_words()` (not `extract_text()`) to get tokens with `x0`, `x1`, `top` coordinates. Pre-joined lines are exactly what corrupts across columns.
2. **Determine the column split — inspect the sample first.** Run `extract_words()` on the real sample and inspect the distribution of word `x0` values (there should be two clusters). Find the real boundary by clustering `x0` into two groups (e.g. simple 1-D k-means, or the largest gap in a sorted `x0` histogram). **Do NOT hardcode a pixel value blindly** — derive it, then assign each word to left/right column by comparing `x0` to the boundary. (Risk (b): the boundary may shift between students.)
3. **Watermark strip (heuristic — tune on sample).** The "Copy of Transcript" watermark tokens are isolated **single-character** words stacked vertically in a **narrow x band**. Filter out word tokens where `len(text.strip()) == 1` AND the token falls in the watermark x-band AND participates in a vertical stack (multiple single-char tokens at similar `x0`, increasing `top`). Detect the band from that stack, not a magic constant. Remove these tokens before line reconstruction. Comment that this is heuristic and sample-tuned.
4. **Reconstruct lines per column.** Within each column, group surviving words by rounded `top` (e.g. `round(top / 2)` to absorb jitter), sort each group by `x0`, join with spaces. This yields clean single-course lines.
5. **Match courses.** Run the existing `COURSE_PATTERN` against each reconstructed per-column line; reuse `_normalise_code`, status logic, and `is_writing` detection unchanged.
6. **Term parsing.** Track the current term using **`FULL_TERM_PATTERN`** (Step 2) mapped via `_FULL_SEASON` to internal "FA 2025". Terms appear per column, so track term **per column** as you walk that column's lines.
7. **Transfer / test credits.** Detect section headers like `Transfer Credit from <institution>` and `Test Credits`; courses under them get `status="transfer"` / grade `"TR"` (mirror the unofficial parser). Use a generic placeholder institution in comments/examples — no PII.

#### 3b. `parse_and_detect(pdf_bytes) -> tuple[list[dict], OfficialDetection]`

Single entry point used by the router. Extracts text once, detects, then picks the parser:

```python
from official_detector import detect_official, OfficialDetection

def parse_and_detect(pdf_bytes: bytes) -> tuple[list[dict], OfficialDetection]:
    pages_text = extract_pages_text(pdf_bytes)
    full_text  = "\n".join(pages_text)
    detection  = detect_official(pdf_bytes, full_text)
    if detection.is_official:
        courses = parse_official_transcript(pdf_bytes)
    else:
        courses = parse_transcript(pdf_bytes, pages_text=pages_text)
    return courses, detection
```

#### 3c. Trustworthiness safety net (Risk (b) — mandatory)

Expose a helper the router uses to decide reject-vs-store:

```python
def official_parse_looks_bad(courses: list[dict]) -> bool:
    if len(courses) < 3:                      # implausibly few for a full official record
        return True
    unknown = sum(1 for c in courses if c.get("term") in (None, "", "Unknown"))
    return unknown / max(len(courses), 1) > 0.3   # too many unresolved terms => de-interleave failed
```
Tune the thresholds against the real sample once course/term recovery works.

**How to verify:**
```bash
cd backend
python -c "from transcript_parser import parse_and_detect; \
c,d=parse_and_detect(open('path/to/official.pdf','rb').read()); \
print(d.is_official, len(c),'courses'); \
print([(x['course_code'], x['term']) for x in c])"
# expect is_official=True, clean codes (no 'PHYSip'), real terms (FA/SP/SU 20xx), NOT 'Unknown'
```

---

### Step 4 — Wire `backend/routers/transcript.py`: ack flag, 409, official parse + safety net, consent write, response fields, shadow flag

**File:** `backend/routers/transcript.py`, `POST /upload` handler.

1. **Import** `Form`; add the parameter:
   ```python
   from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request, Form
   async def upload_transcript(
       request: Request,
       file: UploadFile = File(...),
       acknowledge_official: bool = Form(False),   # NEW
       user_id: str = Depends(get_user_id),
   ):
   ```
2. **Shadow-mode flag** near the top of the module:
   ```python
   OFFICIAL_DETECT = os.getenv("OFFICIAL_DETECT", "0") == "1"
   ```
3. **Replace** the current parse call with `parse_and_detect` (keep the existing `TimeoutError` / broad-`except` → 422 wrappers):
   ```python
   from transcript_parser import parse_and_detect, official_parse_looks_bad
   courses, detection = await asyncio.wait_for(
       asyncio.to_thread(parse_and_detect, pdf_bytes),
       timeout=PARSE_TIMEOUT_SECONDS,
   )
   ```
4. **Always log** (shadow mode observes without acting):
   ```python
   logger.info("official_detection user=%s score=%d official=%s signals=%s ack=%s",
               user_id, detection.score, detection.is_official, detection.signals, acknowledge_official)
   ```
5. **409 consent gate** — only when the flag is on:
   ```python
   if OFFICIAL_DETECT and detection.is_official and not acknowledge_official:
       raise HTTPException(status_code=409, detail={
           "code": "official_transcript_detected",
           "needs_official_ack": True,
           "confidence": detection.confidence,
           "signals": detection.signals,
           "message": "This looks like an official transcript. Confirm to proceed.",
       })
   ```
   **Shadow-mode behavior:** when `OFFICIAL_DETECT` is unset/`0`, detection + official parsing still run and log but **never 409** — validates the false-positive rate against real traffic before the dialog goes live. Mobile needs no flag; it never sees a 409.
6. **Safety net + official-specific 422** — replace the current `if not courses:` block:
   ```python
   if detection.is_official and (not courses or official_parse_looks_bad(courses)):
       raise HTTPException(422, detail="We couldn't reliably read this official transcript's course list. Please upload your unofficial transcript from LionPATH instead (Student Center -> My Academics).")
   if not courses:
       raise HTTPException(422, detail="No courses found in transcript. Make sure this is an unofficial PSU transcript PDF.")
   ```
   This prevents storing a garbled official result (Risk (b)).
7. **Consent timestamp + kind on the user record.** Extend the existing `users_table.update_item` (the `transcript_parsed_at` write) to also persist `transcript_kind` and, when official + acknowledged, `official_transcript_ack_at`:
   ```python
   kind = "official" if detection.is_official else "unofficial"
   # UpdateExpression adds: transcript_kind = :kind
   #   and official_transcript_ack_at = :ack when kind == "official"
   ```
   Add S3 object metadata `Metadata={"transcript-kind": kind}` to the existing `put_object` (same key/bucket — sensitivity class identical to unofficial).
8. **DELETE handler:** add `transcript_kind` and `official_transcript_ack_at` to the existing `REMOVE` `UpdateExpression` so a later unofficial upload clears official consent state.
9. **Success response:** add `"transcript_kind": kind`. Optionally add `"parse_warning": "Official transcripts are parsed best-effort — please cross-check your course list."` when `detection.is_official`.

**How to verify:**
```bash
# Shadow mode off: official upload parses via official parser, stores if it passes the safety net; log shows official=True.
# Flag on -> 409 without ack (set OFFICIAL_DETECT=1 in backend/.env, restart uvicorn):
curl -i -X POST localhost:8080/transcript/upload \
  -H "x-user-id: matthew-test-001" -F "file=@path/to/official.pdf"
# expect 409, detail.needs_official_ack=true
curl -i -X POST localhost:8080/transcript/upload \
  -H "x-user-id: matthew-test-001" -F "file=@path/to/official.pdf" -F "acknowledge_official=true"
# expect 200 with transcript_kind=official (or safety-net 422 if parse looks bad)
# Unofficial upload still returns 200, transcript_kind=unofficial.
```

---

### Step 5 — `mobile/services/transcriptService.ts`: param, error helper, types

**File:** `mobile/services/transcriptService.ts`.

1. **Extend** `UploadResult`:
   ```ts
   export type UploadResult = {
     status: string; courses_parsed: number; done: number; in_progress: number; transfer: number;
     transcript_kind?: string;   // NEW
     parse_warning?: string;     // NEW
   };
   ```
2. **Add** the 4th parameter to `uploadTranscript`:
   ```ts
   export async function uploadTranscript(
     userId: string, fileUri: string, fileName: string,
     acknowledgeOfficial = false,               // NEW
   ): Promise<UploadResult> {
     const form = new FormData();
     form.append("file", { uri: fileUri, name: fileName, type: "application/pdf" } as any);
     if (acknowledgeOfficial) form.append("acknowledge_official", "true");
     const res = await api.post<UploadResult>("/transcript/upload", form, {
       headers: { "x-user-id": userId, "Content-Type": "multipart/form-data" },
     });
     return res.data;
   }
   ```
3. **Add** a discriminator helper (shared by both screens):
   ```ts
   export function isOfficialAckError(e: any): boolean {
     return e?.response?.status === 409 && e?.response?.data?.detail?.needs_official_ack === true;
   }
   ```

**How to verify:** Expo/`tsc` type-check passes; existing 3-arg callers still compile (4th param defaults).

---

### Step 6 — Both upload screens: `doUpload(file, ack)` refactor + Alert + string-guard + parse_warning

**Files:** `mobile/app/(tabs)/upload.tsx` **and** `mobile/app/onboarding/upload.tsx` (both call `uploadTranscript`).

Refactor each screen's `pickAndUpload` so picking and uploading are separate — the confirm branch re-uses the already-picked file:

```ts
import { uploadTranscript, isOfficialAckError, /* ...existing... */ } from "../../services/transcriptService";

async function pickAndUpload() {
  const picked = await DocumentPicker.getDocumentAsync({ type: "application/pdf", copyToCacheDirectory: true });
  if (picked.canceled || !picked.assets?.length) return;
  await doUpload(picked.assets[0], false);
}

async function doUpload(file: DocumentPicker.DocumentPickerAsset, ack = false) {
  setUploading(true);
  // (tabs screen only) setResult(null);
  try {
    const data = await uploadTranscript(userId!, file.uri, file.name ?? "transcript.pdf", ack);
    // ...existing success handling for this screen...
  } catch (e: any) {
    if (isOfficialAckError(e)) {
      Alert.alert(
        "Official transcript detected",
        "This looks like an OFFICIAL Penn State transcript. Official transcripts are meant for institutions - your unofficial transcript from LionPATH works just as well and is the recommended option.\n\nDo you want to use this file anyway?",
        [
          { text: "Cancel", style: "cancel" },
          { text: "Use it anyway", onPress: () => doUpload(file, true) },
        ],
      );
      return;
    }
    // RISK (c): the 409 detail is an OBJECT. Without this guard, Alert renders "[object Object]".
    const detail = e?.response?.data?.detail;
    Alert.alert("Upload failed", typeof detail === "string" ? detail : "Something went wrong.");
  } finally {
    setUploading(false);
  }
}
```

**Notes:**
- `(tabs)/upload.tsx`: success = `setResult(data)` then `setTimeout(() => router.navigate("/(tabs)/"), 1500)`. Render `data.parse_warning` (if present) as an amber caption under the stat boxes.
- `onboarding/upload.tsx`: success = `setParsed(data.courses_parsed); setDone(true);`. No `setResult` there.
- **Risk (c) reminder:** the string-guard on `detail` is required in *both* files — the current code passes `detail` straight to `Alert.alert`, which can now be an object.
- Consent copy is unchanged from the prior design (we now actually parse the file if they confirm).

**How to verify (needs `OFFICIAL_DETECT=1` backend + the signed sample):** pick official PDF → dialog → "Cancel" aborts silently → re-pick → "Use it anyway" proceeds and (if parse passes) lands on timeline. Pick unofficial → uploads, no dialog. Trigger a plain 422 → readable message, not `[object Object]`.

---

### Step 7 — New file: `backend/tests/test_official_detector.py` (+ official parser tests)

**Create** unit tests using **sanitized** fixtures (no PII — generic names/IDs).

**Detector cases:**

| Case | Fixture | Expect |
|---|---|---|
| Unofficial | text containing `UNOFFICIAL TRANSCRIPT` | `is_official False`, `unofficial_marker` fired |
| Official (text) | text with `Undergraduate Official Transcript` + `Office of the University Registrar` + `University seal` | `is_official True` (3+2=5) |
| Signature bytes alone | `pdf_bytes` with `/ByteRange` + `adbe.pkcs7`, empty text | `is_official True` (4) — proves byte anchor / Risk (a) |
| Spaced `/Type /Sig` NOT relied on | bytes with `/Type/Sig` (no space) but WITH `adbe.pkcs7` | still detected — regression guard for the correction |
| Registrar boilerplate only | just `FERPA` + `Office of the University Registrar` | `is_official False` (2 < 4) |
| Negative lookbehind | text `UNOFFICIAL TRANSCRIPT` | `official_header` does not fire |

**Official-parser cases (sanitized fixtures):**

| Case | Fixture | Expect |
|---|---|---|
| Two-column reconstruction | synthetic `extract_words`-style token list with two x-clusters, one course per column | two distinct courses, not collided |
| Full-name terms | tokens/lines with "Fall 2025" / "Spring 2026" | terms normalized to `FA 2025` / `SP 2026`, never `Unknown` |
| Watermark stripping | course tokens interleaved with single-char stacked watermark tokens in a narrow x-band | clean code (e.g. `PHYS 211`, not `PHYSip 211`) |
| Safety net | course list with >30% `Unknown` terms | `official_parse_looks_bad` returns True |

For byte-signature tests, construct minimal `bytes` blobs — no valid PDF needed since `detect_official` only byte-scans. Build word-token fixtures as plain dict lists mimicking `extract_words()` output so line-reconstruction logic is unit-testable without a PDF.

**How to verify:**
```bash
cd backend
python -m pytest tests/test_official_detector.py -v
```

---

### Step 8 — `CLAUDE.md` note

Add a short subsection under **"Key decisions & known quirks"** documenting: the scored detector (`official_detector.py`, byte anchor `/ByteRange`+`adbe.pkcs7`, threshold 4); the **dedicated official-layout parser** (`extract_words` + column de-interleave + watermark strip + full-name term mapping) and *why* it exists (current parser mangles official layout — two columns, "Copy of Transcript" watermark, full-season terms); the trustworthiness safety net; the single-endpoint 409 `acknowledge_official` contract; the `OFFICIAL_DETECT` shadow flag; and the consent fields (`transcript_kind`, `official_transcript_ack_at`).

---

## Deferred (Phase 2)

- **OCR for scanned paper official transcripts** (image-only PDFs → empty text → generic 422).
- **Per-school detectors/parsers** for multi-school expansion — keep PSU strings isolated in `PSU_SIGNALS`; the byte-signature signal is already school-agnostic. The two-column/watermark logic is PSU-official-specific and must be revisited per school.
- **S3 encryption-at-rest / retention review** — fold into the existing AWS-migration task list (`project_aws_tasks.md`).
- **Harden the de-interleaver** once 2–3 more official samples are collected — replace sample-tuned constants with distribution-derived values across samples.

## Manual test checklist

- [ ] `python official_detector.py <unofficial>.pdf` → `is_official=False`; `<official>.pdf` → `is_official=True`, score ~9.
- [ ] `pytest tests/test_official_detector.py` → all pass.
- [ ] **Against the real signed sample:** (a) detection fires (`is_official=True`); (b) the official parser recovers the correct course list — clean codes (no `PHYSip`, no spliced watermark letters) with **real terms** (`FA/SP/SU 20xx`, not `Unknown`); (c) course count roughly matches the transcript's career totals.
- [ ] Shadow mode (`OFFICIAL_DETECT` unset): official upload parses + stores if trustworthy; log shows `official=True`; no 409.
- [ ] `OFFICIAL_DETECT=1`: official PDF without ack → **409** with `detail.needs_official_ack=true`.
- [ ] Same PDF with `acknowledge_official=true` → 200 `transcript_kind=official` (or safety-net 422 if parse looks bad).
- [ ] Deliberately-degraded official (force >30% Unknown) → safety-net 422, nothing stored.
- [ ] Unofficial upload → 200, `transcript_kind=unofficial`, no regression in parsed course count, no dialog on mobile.
- [ ] Mobile: official PDF → Alert; Cancel aborts; "Use it anyway" proceeds.
- [ ] Mobile: a plain 422/error → readable message, **not** `[object Object]` (Risk c).
- [ ] `official_transcript_ack_at` set after acknowledged official upload; cleared after DELETE and after a later unofficial upload.
- [ ] Both screens (`(tabs)/upload.tsx` and `onboarding/upload.tsx`) behave identically.
