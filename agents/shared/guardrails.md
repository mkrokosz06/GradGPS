# Guardrails

Full product rules: root [CLAUDE.md](../../CLAUDE.md).

Hard rules for agents:

1. **No product runtime** — do not register agents in `backend/main.py` or mobile.
2. **No fabricated catalog/gen-ed** — recommend scrape/`rebuild_gen_ed` or `seed_matthew` patches only; never run `seed_gen_ed.py` for domain pools.
3. **Audit vs catalog** — AuditQA must label findings as engine bug vs catalog/pair gap.
4. **choose_credits** — one timeline slot; never expand pool items individually into the timeline.
5. **Official transcripts** — no spaced `/Type /Sig`; watermark by font size; respect OFFICIAL_DETECT shadow vs 409.
6. **SAP** — deterministic `scrape_sap.py` only; audit remains source of truth.
7. **Mobile** — never convert `(tabs)` to Stack.
8. **Auth** — product changes are human-only; never commit secrets or enable `AUTH_DEV_BYPASS` for prod.
