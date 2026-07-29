# Integration tests (API-level)

Tests here exercise real FastAPI routes via `fastapi.testclient.TestClient` (or httpx)
against the local stack: `docker-compose up -d` + seeded tables. They are slower than
unit tests and may be skipped in environments without Docker
(`pytest.mark.skipif` on a reachability check).

## Existing

| File | Covers |
|------|--------|
| `test_timeline_random_majors.py` | Picks N random bachelor's majors (default 3) from the live catalog, generates a fresh-student timeline for each, and asserts structural invariants (chronological terms, credit bands, no over-scheduled courses, path-aware total-credit floor). Zero input; prints its `TEST_SEED` for reproduction. `TEST_N_MAJORS=500` sweeps every major (~208, a few minutes). |

## Ideas

- **Happy path** — upload transcript PDF → select major → `/audit` shows expected
  done/missing counts → `/timeline` produces semesters in the 14–17 credit band.
- **Official consent flow** — upload official sample with `OFFICIAL_DETECT=1`:
  first request 409 `needs_official_ack`, re-submit with `acknowledge_official=true`
  succeeds, user record gets `transcript_kind` + `official_transcript_ack_at`;
  a later unofficial upload clears both.
- **Transcript delete** — DELETE removes courses, S3 object, and user transcript
  metadata; `/audit` afterwards reflects an empty transcript.
- **Auth matrix** — with bypass off: no token → 401, garbage token → 401,
  `x-user-id` header ignored; with bypass on: header accepted.
- **Major switch** — select major A, audit, switch to major B → no stale results,
  subplan cleared.
- **SAP vs fallback** — a major with a template returns template-shaped timeline;
  a major without one falls back to the Layer 1 packer (no 500s).
- **Upload hardening** — non-PDF file, oversized file, empty file, non-transcript
  PDF → clean 4xx errors, nothing stored.
