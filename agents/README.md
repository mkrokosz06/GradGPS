# GradGPS agents — development teammates

**Never import this package from FastAPI or the Expo app.** These agents help the engineering team run tests, produce analytics, and recommend work. Student-facing degree audits, timelines, and transcript parsing stay in `backend/` algorithms.

## Quick start

From the repo root (Python 3.11+ recommended):

```bash
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# Route a request
python -m agents.orchestrator.run "run timeline tests"
python -m agents.orchestrator.run "analyze catalog"
python -m agents.orchestrator.run "recommendations" --intent recommend

# Direct specialists
python -m agents.test_runner.run_tests --suite timeline
python -m agents.audit_qa.analyze
python -m agents.timeline_qa.analyze
python -m agents.transcript_qa.analyze
python -m agents.catalog_analyst.analyze
python -m agents.mobile_qa.analyze
python -m agents.recommend.digest --run-all

# Approved fix packet (writes agents/.work/implement/<id>.md)
python -m agents.recommend.digest --run-all --skip-tests
python -m agents.implement_fix.apply --approve audit-missing-pytest
```

## Slack

Full setup: [docs/slack-setup.md](docs/slack-setup.md)

```bash
copy agents\runtime\.env.example agents\runtime\.env
# set SLACK_WEBHOOK_URL (and optionally bot tokens)
python -m pip install -r agents/requirements.txt
python -m agents.reporter.slack --ping

# Inbound bot (keep running)
python -m agents.reporter.bot
# then in Slack: /gradgps run timeline tests
```

With `SLACK_ENABLED=1`, CLI agents post automatically (`--no-slack` to disable).

## Layout

See [AGENTS.md](AGENTS.md) for the roster. Shared contracts live in `shared/`.

## Local vs cloud

- **Now:** `agents.runtime.local` (this machine).
- **Later:** `agents.runtime.cloud` (GitHub Actions / hosted) — not implemented yet; same prompts and report shapes.
