"""Shared report schemas for GradGPS dev agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
import json
from pathlib import Path


Severity = Literal["critical", "high", "medium", "low", "info"]
Area = Literal["audit", "timeline", "transcript", "catalog", "mobile", "auth", "cross"]
Intent = Literal["test", "analyze", "recommend", "implement_fix"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TestReport:
    suite: str
    command: list[str]
    passed: int
    failed: int
    skipped: int
    errors: int
    duration_seconds: float
    failing_nodeids: list[str] = field(default_factory=list)
    log_path: str | None = None
    exit_code: int = 0
    created_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and self.errors == 0


@dataclass
class Recommendation:
    id: str
    area: Area
    severity: Severity
    title: str
    rationale: str
    suggested_owner: str
    verify_steps: list[str] = field(default_factory=list)
    claude_md_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalyticsReport:
    area: Area
    title: str
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    created_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class DispatchPlan:
    intent: Intent
    area: Area | Literal["all"]
    agent: str
    reason: str
    raw_request: str
    slack: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_dotenv_file(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ if not already set."""
    import os

    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
