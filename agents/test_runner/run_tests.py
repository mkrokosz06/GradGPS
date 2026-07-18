"""
Run GradGPS backend pytest suites and emit a TestReport.

Usage:
  python -m agents.test_runner.run_tests --suite timeline
  python -m agents.test_runner.run_tests --suite all --slack
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow `python agents/test_runner/run_tests.py` and `python -m agents...`
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.paths import BACKEND_ROOT, REPORTS_ROOT, ensure_work_dirs
from agents.shared.routing import SUITE_PATHS
from agents.shared.schemas import TestReport, load_dotenv_file, write_json


def _load_env() -> None:
    load_dotenv_file(_REPO / "agents" / "runtime" / ".env")
    load_dotenv_file(_REPO / "backend" / ".env")


def _parse_pytest_summary(stdout: str, stderr: str) -> dict[str, int]:
    text = stdout + "\n" + stderr
    # "5 passed, 2 failed, 1 skipped in 3.21s"
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    m = re.search(
        r"(?:(\d+)\s+passed)?(?:,\s*)?(?:(\d+)\s+failed)?(?:,\s*)?(?:(\d+)\s+skipped)?(?:,\s*)?(?:(\d+)\s+error)?",
        text,
    )
    # More reliable: scan for each token
    for key in counts:
        km = re.search(rf"(\d+)\s+{key.rstrip('s')}s?\b", text)
        # pytest says "1 error" or "2 errors"
        if key == "errors":
            km = re.search(r"(\d+)\s+errors?\b", text)
        elif key == "passed":
            km = re.search(r"(\d+)\s+passed\b", text)
        elif key == "failed":
            km = re.search(r"(\d+)\s+failed\b", text)
        elif key == "skipped":
            km = re.search(r"(\d+)\s+skipped\b", text)
        if km:
            counts[key] = int(km.group(1))
    return counts


def _parse_failing_nodeids(stdout: str, stderr: str) -> list[str]:
    text = stdout + "\n" + stderr
    nodeids: list[str] = []
    for line in text.splitlines():
        # FAILED tests/foo.py::test_bar - AssertionError
        if line.startswith("FAILED "):
            node = line[len("FAILED ") :].split(" ", 1)[0].strip()
            if node:
                nodeids.append(node)
        # ERROR tests/foo.py or ERROR tests/foo.py::test
        if line.startswith("ERROR "):
            node = line[len("ERROR ") :].split(" ", 1)[0].strip()
            if node and not node.startswith("collecting"):
                nodeids.append(node)
    # Collection errors also appear as "ERROR collecting path"
    for m in re.finditer(r"ERROR collecting (\S+)", text):
        nodeids.append(m.group(1))
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for n in nodeids:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def run_suite(suite: str, extra_pytest_args: list[str] | None = None) -> TestReport:
    ensure_work_dirs()
    paths = SUITE_PATHS.get(suite)
    if paths is None:
        raise SystemExit(f"Unknown suite '{suite}'. Choose from: {', '.join(SUITE_PATHS)}")

    if suite == "mobile":
        raise SystemExit("Mobile suite is handled by agents.mobile_qa.analyze — use orchestrator area=mobile")

    if suite == "auth":
        raise SystemExit("No automated auth pytest suite yet — route auth product work to a human")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = REPORTS_ROOT / f"pytest-{suite}-{stamp}.log"

    cmd = [sys.executable, "-m", "pytest", *paths, "-v", "--tb=short"]
    if extra_pytest_args:
        cmd.extend(extra_pytest_args)

    # Fail fast with a clear report if pytest is not installed
    try:
        import pytest  # noqa: F401
    except ImportError:
        tip = (
            "pytest is not installed in this Python. "
            "Run: python -m pip install -r backend/requirements-dev.txt"
        )
        log_path.write_text(tip + "\n", encoding="utf-8")
        report = TestReport(
            suite=suite,
            command=cmd,
            passed=0,
            failed=0,
            skipped=0,
            errors=1,
            duration_seconds=0.0,
            failing_nodeids=["<pytest not installed>"],
            log_path=str(log_path),
            exit_code=2,
        )
        write_json(REPORTS_ROOT / f"pytest-{suite}-no-pytest.json", report.to_dict())
        print(tip, file=sys.stderr)
        return report

    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    duration = time.perf_counter() - started

    log_path.write_text(
        f"$ {' '.join(cmd)}\ncwd={BACKEND_ROOT}\nexit={proc.returncode}\n\n"
        f"===== STDOUT =====\n{proc.stdout}\n\n===== STDERR =====\n{proc.stderr}\n",
        encoding="utf-8",
    )

    if "No module named pytest" in (proc.stderr or ""):
        print(
            "pytest missing in subprocess Python. "
            "Run: python -m pip install -r backend/requirements-dev.txt",
            file=sys.stderr,
        )

    counts = _parse_pytest_summary(proc.stdout, proc.stderr)
    failing = _parse_failing_nodeids(proc.stdout, proc.stderr)

    report = TestReport(
        suite=suite,
        command=cmd,
        passed=counts["passed"],
        failed=counts["failed"],
        skipped=counts["skipped"],
        errors=counts["errors"],
        duration_seconds=round(duration, 3),
        failing_nodeids=failing,
        log_path=str(log_path),
        exit_code=proc.returncode,
    )

    json_path = REPORTS_ROOT / f"pytest-{suite}-{stamp}.json"
    write_json(json_path, report.to_dict())
    return report


def main(argv: list[str] | None = None) -> int:
    _load_env()
    from agents.shared.slack_config import add_slack_cli_flags, cli_slack_from_args, slack_wanted

    parser = argparse.ArgumentParser(description="Run GradGPS backend pytest suites")
    parser.add_argument(
        "--suite",
        default="all",
        choices=sorted(SUITE_PATHS.keys()),
        help="Which test group to run",
    )
    add_slack_cli_flags(parser)
    parser.add_argument("pytest_args", nargs="*", help="Extra args passed to pytest")
    args = parser.parse_args(argv)

    if args.suite == "audit":
        report = run_suite("audit", args.pytest_args)
    else:
        report = run_suite(args.suite, args.pytest_args)

    print(json.dumps(report.to_dict(), indent=2))

    if slack_wanted(cli_slack=cli_slack_from_args(args)):
        from agents.reporter.slack import post_test_report

        post_test_report(report, required=False)

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
