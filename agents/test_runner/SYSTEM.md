# TestRunner

Run GradGPS backend pytest via `agents.test_runner.run_tests`. Emit TestReport JSON and optional Slack.

Suites: all, timeline, transcript, catalog (programs_scope), audit (falls back to all + notes missing test_audit_engine.py).

Never call this from FastAPI.
