"""
Detects whether an uploaded transcript PDF is an *official* PSU transcript
(as opposed to the unofficial LionPATH browser-print PDF the app normally parses).

Why this exists
---------------
Official transcripts have a fundamentally different layout — two term columns
side by side, a diagonal "Copy of Transcript" watermark overlaid through the
course tables, and full-name terms ("Fall 2025" vs. the unofficial "FA 2025").
The unofficial parser mangles them (validated against a real signed sample:
13 partly-wrong courses, every term "Unknown"). So we detect official transcripts
up front to (a) route them to the dedicated official parser and (b) drive a
consent gate in the API.

Detection is a scored heuristic over multiple signals, validated against a real
4-page digitally-signed official transcript:

    pdf_digital_signature  +4   certified-PDF bytes (/ByteRange + adbe.pkcs7)
    official_header        +3   "OFFICIAL TRANSCRIPT" (not "UNOFFICIAL")
    registrar_language     +1 each, capped +2
    authenticity_statement +1   (bonus; absent from the printed style)
    unofficial_marker      -5   hard veto — the word never appears on official

Threshold is 4, so the signature bytes alone trigger detection (layout-agnostic),
and header + registrar language triggers even for a non-signed printout.

PSU-specific text signals are isolated in the module-level lists so per-school
variants can slot in later (see MEMORY.md multi-school note); the byte-signature
signal is school-agnostic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

THRESHOLD = 4  # score >= THRESHOLD  =>  is_official

# ── Signal weights ──────────────────────────────────────────────────────────
W_SIGNATURE      = 4
W_HEADER         = 3
W_REGISTRAR_EACH = 1
W_REGISTRAR_CAP  = 2
W_AUTHENTICITY   = 1   # bonus only — absent from the printed "Copy of Transcript" style
W_UNOFFICIAL     = -5  # hard veto

# ── Byte signals (layout-independent; scanned on raw PDF bytes) ──────────────
# A PSU official eTranscript is a certified PDF. `/ByteRange` + an Adobe PKCS#7
# signature dictionary are the reliable anchors. NOTE: the real sample contains
# `/Type/Sig` with NO space — never test the spaced form, it misses.
_SIG_BYTES_REQUIRED = (b"/ByteRange", b"adbe.pkcs7")

# ── Text signals (PSU-specific) ─────────────────────────────────────────────
# Negative lookbehind so "UNOFFICIAL TRANSCRIPT" never matches the official one.
_HEADER_RE = re.compile(r"(?<!UN)OFFICIAL\s+TRANSCRIPT", re.I)

_REGISTRAR_PHRASES = (
    "Office of the University Registrar",
    "University seal",
    "University Registrar",
    "Family Educational Rights and Privacy Act",
    "FERPA",
)

# Parchment eTranscript markers — present only on the certified electronic style,
# absent from the printed/scanned "Copy of Transcript" style. Bonus signal only.
_AUTHENTICITY_PHRASES = (
    "Statement of Authenticity",
    "Parchment",
    "digitally signed",
)

_UNOFFICIAL_RE = re.compile(r"UNOFFICIAL|not an official transcript", re.I)


@dataclass
class OfficialDetection:
    is_official: bool
    score: int
    confidence: float          # min(max(score,0)/8, 1.0), rounded
    signals: list[str]         # names of signals that fired (for logging + API response)


def detect_official(pdf_bytes: bytes, full_text: str) -> OfficialDetection:
    """
    Parameters
    ----------
    pdf_bytes : bytes
        Raw bytes of the uploaded PDF (used for the layout-agnostic signature scan).
    full_text : str
        Text already extracted from the PDF (e.g. by transcript_parser.extract_pages_text).

    Returns
    -------
    OfficialDetection
    """
    score = 0
    signals: list[str] = []

    # Signature bytes — the strongest, layout-agnostic anchor.
    if all(marker in pdf_bytes for marker in _SIG_BYTES_REQUIRED):
        score += W_SIGNATURE
        signals.append("pdf_digital_signature")

    # "OFFICIAL TRANSCRIPT" header (verified wording on the real sample).
    if _HEADER_RE.search(full_text):
        score += W_HEADER
        signals.append("official_header")

    # Registrar boilerplate — several phrases, capped so it can't dominate alone.
    reg_hits = sum(1 for p in _REGISTRAR_PHRASES if re.search(re.escape(p), full_text, re.I))
    if reg_hits:
        score += min(reg_hits * W_REGISTRAR_EACH, W_REGISTRAR_CAP)
        signals.append("registrar_language")

    # Authenticity/Parchment markers — bonus only.
    if any(re.search(re.escape(p), full_text, re.I) for p in _AUTHENTICITY_PHRASES):
        score += W_AUTHENTICITY
        signals.append("authenticity_statement")

    # Unofficial veto — the word never appears on an official transcript.
    if _UNOFFICIAL_RE.search(full_text):
        score += W_UNOFFICIAL
        signals.append("unofficial_marker")

    confidence = round(min(max(score, 0) / 8, 1.0), 2)
    return OfficialDetection(
        is_official=score >= THRESHOLD,
        score=score,
        confidence=confidence,
        signals=signals,
    )


# ── quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python official_detector.py path/to/transcript.pdf")
        sys.exit(1)

    from transcript_parser import extract_pages_text  # local import avoids a cycle

    raw = open(sys.argv[1], "rb").read()
    text = "\n".join(extract_pages_text(raw))
    d = detect_official(raw, text)
    print(f"is_official : {d.is_official}")
    print(f"score       : {d.score}")
    print(f"confidence  : {d.confidence}")
    print(f"signals     : {d.signals}")
