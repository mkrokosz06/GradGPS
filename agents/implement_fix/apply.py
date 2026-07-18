"""
Prepare an approved recommendation for implementation (human / Cursor / Claude Code).

Does not auto-edit product code without an external coding agent. Writes a concrete
task packet under agents/.work/implement/ and optionally opens a GitHub issue via gh.

Usage:
  python -m agents.implement_fix.apply --approve audit-missing-pytest
  python -m agents.implement_fix.apply --approve audit-missing-pytest --gh-issue
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.paths import REPORTS_ROOT, WORK_ROOT, ensure_work_dirs
from agents.shared.schemas import Recommendation, load_dotenv_file


def _load_env() -> None:
    load_dotenv_file(_REPO / "agents" / "runtime" / ".env")


def _load_recommendation(rec_id: str) -> Recommendation:
    path = REPORTS_ROOT / "recommendations-latest.json"
    if not path.is_file():
        raise SystemExit(
            f"No {path}. Run: python -m agents.recommend.digest --run-all --skip-tests"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    for r in data.get("recommendations", []):
        if r.get("id") == rec_id:
            return Recommendation(
                id=r["id"],
                area=r["area"],
                severity=r["severity"],
                title=r["title"],
                rationale=r["rationale"],
                suggested_owner=r.get("suggested_owner", "human"),
                verify_steps=r.get("verify_steps", []),
                claude_md_refs=r.get("claude_md_refs", []),
                created_at=r.get("created_at", ""),
            )
    raise SystemExit(f"Recommendation id not found: {rec_id}")


def _task_markdown(rec: Recommendation) -> str:
    verify = "\n".join(f"- {s}" for s in rec.verify_steps) or "- (none listed)"
    refs = "\n".join(f"- {s}" for s in rec.claude_md_refs) or "- CLAUDE.md"
    return f"""# Implement: {rec.title}

- **id:** `{rec.id}`
- **area:** `{rec.area}`
- **severity:** `{rec.severity}`
- **owner hint:** {rec.suggested_owner}

## Rationale

{rec.rationale}

## Constraints (GradGPS)

- Dev-agent task only — do not wire this into FastAPI/Expo runtime.
- Follow root CLAUDE.md and area docs. Do not invent gen-ed/catalog data.
- Auth-area product changes stay human-gated.
- Mobile: do not convert `(tabs)` layout to Stack.

## CLAUDE.md / doc refs

{refs}

## Verify

{verify}

## Done when

- Code or tests land on a PR branch `agent/{rec.id}`
- Verify steps pass
- PR description links this recommendation id
"""


def apply_recommendation(approve_id: str | None, *, slack: bool = False, gh_issue: bool = False) -> dict[str, Any]:
    if not approve_id:
        raise SystemExit(
            "implement_fix requires --approve <recommendation_id>. "
            "List ids via: python -m agents.recommend.digest"
        )

    rec = _load_recommendation(approve_id)
    if rec.area == "auth":
        raise SystemExit(
            "Auth recommendations are human-only. Do not auto-implement; assign a developer."
        )

    ensure_work_dirs()
    out_dir = WORK_ROOT / "implement"
    out_dir.mkdir(parents=True, exist_ok=True)
    task_path = out_dir / f"{rec.id}.md"
    task_path.write_text(_task_markdown(rec), encoding="utf-8")

    result: dict[str, Any] = {
        "type": "ImplementPacket",
        "recommendation": rec.to_dict(),
        "task_path": str(task_path),
        "next_steps": [
            f"Open {task_path} in Cursor or Claude Code and implement on branch agent/{rec.id}",
            "Or pass --gh-issue to open a GitHub issue from this packet",
        ],
    }

    if gh_issue:
        body = task_path.read_text(encoding="utf-8")
        title = f"[agent/{rec.area}] {rec.title}"
        try:
            proc = subprocess.run(
                [
                    "gh",
                    "issue",
                    "create",
                    "--title",
                    title,
                    "--body",
                    body,
                    "--label",
                    f"area:{rec.area}",
                ],
                cwd=str(_REPO),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise SystemExit("gh CLI not found on PATH") from exc
        if proc.returncode != 0:
            raise SystemExit(f"gh issue create failed: {proc.stderr or proc.stdout}")
        result["github_issue_url"] = proc.stdout.strip()

    if slack:
        from agents.reporter.slack import post_implement_packet

        post_implement_packet(
            rec.id,
            rec.title,
            str(task_path),
            github_issue_url=result.get("github_issue_url"),
            required=False,
        )

    return result


def main(argv: list[str] | None = None) -> int:
    from agents.shared.slack_config import load_agent_env, slack_wanted

    load_agent_env()
    parser = argparse.ArgumentParser(description="Prepare an approved GradGPS recommendation for implementation")
    parser.add_argument("--approve", required=True, help="Recommendation id")
    parser.add_argument("--gh-issue", action="store_true", help="Also create a GitHub issue via gh")
    parser.add_argument("--slack", action="store_true", default=None)
    parser.add_argument("--no-slack", action="store_true")
    args = parser.parse_args(argv)

    cli_slack = False if args.no_slack else (True if args.slack else None)
    result = apply_recommendation(
        args.approve,
        slack=slack_wanted(cli_slack=cli_slack),
        gh_issue=args.gh_issue,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
