# Reviewer

When reviewing an agent or human PR for GradGPS, check:

- [ ] No `(tabs)` → Stack conversion
- [ ] No fabricated gen-ed pools / no `seed_gen_ed` domain use
- [ ] `choose_credits` not exploded into timeline items
- [ ] Official detector: no spaced `/Type /Sig`; watermark by font size
- [ ] Auth/secrets not committed; `AUTH_DEV_BYPASS` not enabled for prod
- [ ] SAP changes use scrape_sap + validate_template, audit remains SoT
- [ ] Tests added/updated for the area

Comment only unless asked to implement.
