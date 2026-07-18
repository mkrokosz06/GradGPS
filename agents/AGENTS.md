# Agent roster

| Agent | Module | Does |
|-------|--------|------|
| Orchestrator | `agents.orchestrator.run` | Route test / analyze / recommend / implement_fix |
| TestRunner | `agents.test_runner.run_tests` | Run backend pytest suites → TestReport |
| AuditQA | `agents.audit_qa.analyze` | Audit test gaps + optional seeded `run_audit` for matthew-test-001 |
| TimelineQA | `agents.timeline_qa.analyze` | Packing/SAP pytest + SAP template coverage |
| TranscriptQA | `agents.transcript_qa.analyze` | Official-detector pytest + sample PDF gaps |
| CatalogAnalyst | `agents.catalog_analyst.analyze` | Seed/gen-ed/SAP artifact analytics (no fabricated data) |
| MobileQA | `agents.mobile_qa.analyze` | Static Tabs/NativeWind/official-ack checks |
| Recommend | `agents.recommend.digest` | Rank recommendations from latest analyst JSON |
| ImplementFix | `agents.implement_fix.apply` | Human-approved task packet (+ optional `gh issue`) |
| Reporter | `agents.reporter.slack` | Slack webhook posts |
| Reviewer | `agents/reviewer/SYSTEM.md` | Prompt for PR quirk review (use in Cursor/Claude Code) |

## Boundary

Agents **do not** replace `run_audit()`, timeline packing, or transcript parsing in production. They may call those functions **inside test/analysis harnesses only**.
