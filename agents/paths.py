"""Resolve GradGPS repo paths for agent scripts."""

from __future__ import annotations

from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = AGENTS_ROOT.parent
BACKEND_ROOT = REPO_ROOT / "backend"
MOBILE_ROOT = REPO_ROOT / "mobile"
TESTS_ROOT = BACKEND_ROOT / "tests"
WORK_ROOT = AGENTS_ROOT / ".work"
REPORTS_ROOT = WORK_ROOT / "reports"


def ensure_work_dirs() -> None:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
