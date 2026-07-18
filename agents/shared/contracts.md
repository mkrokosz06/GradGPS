# Report contracts

## TestReport

```json
{
  "suite": "timeline",
  "command": ["python", "-m", "pytest", "..."],
  "passed": 10,
  "failed": 0,
  "skipped": 0,
  "errors": 0,
  "duration_seconds": 1.23,
  "failing_nodeids": [],
  "log_path": "agents/.work/reports/pytest-timeline-....log",
  "exit_code": 0,
  "created_at": "ISO-8601"
}
```

## AnalyticsReport

```json
{
  "area": "audit|timeline|transcript|catalog|mobile|auth|cross",
  "title": "string",
  "metrics": {},
  "notes": [],
  "recommendations": [],
  "created_at": "ISO-8601"
}
```

## Recommendation

```json
{
  "id": "audit-missing-pytest",
  "area": "audit",
  "severity": "critical|high|medium|low|info",
  "title": "string",
  "rationale": "string",
  "suggested_owner": "human|implement_fix|...",
  "verify_steps": [],
  "claude_md_refs": [],
  "created_at": "ISO-8601"
}
```

Reports are written under `agents/.work/reports/` (gitignored).
