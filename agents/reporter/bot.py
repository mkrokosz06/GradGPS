"""
GradGPS Slack bot (Socket Mode) — inbound commands from Slack to local orchestrator.

Requires:
  SLACK_BOT_TOKEN=xoxb-...
  SLACK_APP_TOKEN=xapp-...   (Socket Mode)
  Optional: SLACK_WEBHOOK_URL for mirror posts

Usage:
  python -m pip install -r agents/requirements.txt
  python -m agents.reporter.bot

Slash command (configure in Slack app as /gradgps):
  /gradgps run timeline tests
  /gradgps analyze audit
  /gradgps recommendations
  /gradgps ping

App mention:
  @GradGPSAgents run transcript tests

See agents/docs/slack-setup.md
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.shared.slack_config import load_agent_env, slack_configured

load_agent_env()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gradgps.slack.bot")


def _strip_mention(text: str) -> str:
    # Remove <@U123> style mentions
    return re.sub(r"<@[^>]+>\s*", "", text or "").strip()


def _run_orchestrator(
    request: str,
    *,
    channel: str,
    thread_ts: str | None,
    say,
) -> None:
    """Run in a worker thread so Slack ack stays fast."""
    try:
        from agents.reporter.slack import (
            post_blocked,
            post_claimed,
            post_dispatch_result,
            post_message,
        )
        from agents.runtime.local import dispatch
        from agents.shared.routing import route

        plan = route(request, slack=True)
        post_claimed(
            plan.agent,
            plan.raw_request,
            plan.reason,
            channel=channel,
            thread_ts=thread_ts,
            required=False,
        )
        # Also say in-thread for visibility even if webhook-only
        try:
            say(
                text=f"Running `{plan.agent}` — {plan.reason}",
                thread_ts=thread_ts,
            )
        except Exception:  # noqa: BLE001
            pass

        # Avoid double-post from local.dispatch when we post via post_dispatch_result
        plan.slack = False
        result = dispatch(plan, approve_id=None)
        post_dispatch_result(result, channel=channel, thread_ts=thread_ts, required=False)
        try:
            say(text="Done. See the report above / in #gradgps-agents.", thread_ts=thread_ts)
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        log.exception("orchestrator failed")
        try:
            from agents.reporter.slack import post_blocked

            post_blocked("Agent run failed", str(exc), channel=channel, thread_ts=thread_ts, required=False)
        except Exception:  # noqa: BLE001
            pass
        try:
            say(text=f"Failed: `{exc}`", thread_ts=thread_ts)
        except Exception:  # noqa: BLE001
            pass


def _handle_request(request: str, *, channel: str, thread_ts: str | None, say) -> None:
    request = request.strip()
    if not request:
        say(text="Usage: `/gradgps <request>` e.g. `/gradgps run timeline tests`", thread_ts=thread_ts)
        return
    if request.lower() in {"ping", "help"}:
        if request.lower() == "help":
            say(
                text=(
                    "*GradGPS agents*\n"
                    "• `/gradgps run timeline tests`\n"
                    "• `/gradgps analyze audit`\n"
                    "• `/gradgps analyze catalog`\n"
                    "• `/gradgps recommendations`\n"
                    "• `/gradgps ping`\n"
                    "Dev-only — not student runtime."
                ),
                thread_ts=thread_ts,
            )
            return
        from agents.reporter.slack import ping

        try:
            ping()
            say(text="Ping sent via outbound Slack config.", thread_ts=thread_ts)
        except SystemExit as exc:
            say(text=f"Ping failed: {exc}", thread_ts=thread_ts)
        return

    say(text=f"Claimed: `{request}` — running locally…", thread_ts=thread_ts)
    threading.Thread(
        target=_run_orchestrator,
        kwargs={"request": request, "channel": channel, "thread_ts": thread_ts, "say": say},
        daemon=True,
    ).start()


def main() -> int:
    load_agent_env()
    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError:
        print(
            "slack-bolt is not installed. Run:\n"
            "  python -m pip install -r agents/requirements.txt",
            file=sys.stderr,
        )
        return 1

    import os

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not bot_token or not app_token:
        print(
            "Set SLACK_BOT_TOKEN (xoxb-) and SLACK_APP_TOKEN (xapp-) in agents/runtime/.env\n"
            "See agents/docs/slack-setup.md",
            file=sys.stderr,
        )
        return 1

    if not slack_configured() and not bot_token:
        print("Warning: no SLACK_WEBHOOK_URL — will rely on bot chat.postMessage only.", file=sys.stderr)

    app = App(token=bot_token)

    @app.command("/gradgps")
    def on_slash(ack, command, say):  # noqa: ANN001
        ack()
        text = (command.get("text") or "").strip()
        channel = command.get("channel_id")
        # Slash commands: reply in channel; use response thread if supported
        _handle_request(text, channel=channel, thread_ts=None, say=say)

    @app.event("app_mention")
    def on_mention(event, say):  # noqa: ANN001
        text = _strip_mention(event.get("text", ""))
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        _handle_request(text, channel=channel, thread_ts=thread_ts, say=say)

    @app.event("message")
    def on_message(_event, _say):  # noqa: ANN001
        # Required to avoid unhandled event warnings when message events are subscribed
        return

    log.info("Starting GradGPS Slack bot (Socket Mode)…")
    SocketModeHandler(app, app_token).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
