# App Review demo assets

`demo_transcript.pdf` is a **fabricated** LionPATH-style unofficial transcript for the
synthetic student "Alex Demo". It contains no real person's record — the name, student ID
and grades are invented; only the course codes are real PSU catalog codes, so that the
parser, audit and timeline actually resolve.

It exists so an App Store reviewer can exercise the transcript-upload flow without a Penn
State account. It is deliberately marked `UNOFFICIAL`, which is also `official_detector`'s
hard veto, so it can never trip the official-transcript 409 consent gate.

Its course list is the *same* one `scripts/seed_demo_account.py` seeds, so uploading it is
idempotent: it reproduces the account the reviewer is already looking at rather than wiping
it.

Regenerate and re-verify:

```bash
cd backend
python scripts/make_demo_transcript_pdf.py --verify
```

`--verify` re-parses the written PDF through `transcript_parser.parse_and_detect()` and
fails if any course or term does not round-trip.

Getting it onto the review device: attach it to the **App Review Information → Attachment**
field in App Store Connect, or host it at a URL you give in the review notes. It is checked
in (via a `.gitignore` exception to the blanket `*.pdf` PII rule) precisely because it is
synthetic.
