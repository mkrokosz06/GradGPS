"""Shared Slack / agent env helpers."""

from __future__ import annotations

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def load_agent_env() -> None:
    from agents.shared.schemas import load_dotenv_file

    load_dotenv_file(_REPO / "agents" / "runtime" / ".env")
    load_dotenv_file(_REPO / "backend" / ".env")


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def slack_wanted(*, cli_slack: bool | None = None) -> bool:
    """
    Resolve whether to post to Slack.

    - cli_slack=True  → always
    - cli_slack=False → never
    - cli_slack=None  → SLACK_ENABLED env (default false)
    """
    if cli_slack is True:
        return True
    if cli_slack is False:
        return False
    return env_flag("SLACK_ENABLED", default=False)


def cli_slack_from_args(args: object) -> bool | None:
    """Map --slack / --no-slack argparse flags to cli_slack for slack_wanted()."""
    if getattr(args, "no_slack", False):
        return False
    if getattr(args, "slack", None) is True:
        return True
    return None


def add_slack_cli_flags(parser) -> None:  # noqa: ANN001
    parser.add_argument(
        "--slack",
        action="store_true",
        default=None,
        help="Force Slack posting (default: SLACK_ENABLED in agents/runtime/.env)",
    )
    parser.add_argument("--no-slack", action="store_true", help="Disable Slack for this run")


def slack_configured() -> bool:
    return bool(os.environ.get("SLACK_WEBHOOK_URL") or os.environ.get("SLACK_BOT_TOKEN"))
