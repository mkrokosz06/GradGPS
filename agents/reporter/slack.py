"""
GradGPS Slack reporter — Incoming Webhook and/or Bot API.

Env (agents/runtime/.env):
  SLACK_WEBHOOK_URL     Incoming Webhook (simplest outbound)
  SLACK_BOT_TOKEN       xoxb-... (optional; chat.postMessage)
  SLACK_DEFAULT_CHANNEL Channel id or name for bot posts (e.g. #gradgps-agents or C0123)
  SLACK_ENABLED         1 to post by default without --slack
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.shared.schemas import (
    AnalyticsReport,
    Recommendation,
    TestReport,
)
from agents.shared.slack_config import load_agent_env, slack_configured


def _prefix() -> str:
    return os.environ.get("SLACK_MESSAGE_PREFIX", "GradGPS").strip() or "GradGPS"


def _webhook_url() -> str | None:
    return os.environ.get("SLACK_WEBHOOK_URL") or None


def _bot_token() -> str | None:
    return os.environ.get("SLACK_BOT_TOKEN") or None


def _default_channel() -> str | None:
    return os.environ.get("SLACK_DEFAULT_CHANNEL") or None


def post_message(
    text: str,
    *,
    blocks: list[dict[str, Any]] | None = None,
    channel: str | None = None,
    thread_ts: str | None = None,
    required: bool = True,
) -> bool:
    """
    Post to Slack. Prefers webhook when set (ignores channel/thread unless bot fallback).
    Returns True if posted. If required=False and not configured, returns False.
    """
    load_agent_env()
    webhook = _webhook_url()
    bot = _bot_token()

    if not webhook and not bot:
        msg = (
            "Slack not configured. Set SLACK_WEBHOOK_URL and/or SLACK_BOT_TOKEN in "
            "agents/runtime/.env (see agents/docs/slack-setup.md)."
        )
        if required:
            raise SystemExit(msg)
        print(msg, file=sys.stderr)
        return False

    # Prefer webhook for fire-and-forget reports (no channel needed)
    if webhook and not thread_ts:
        return _post_webhook(webhook, text, blocks=blocks, required=required)

    # Bot API for threaded replies or when webhook absent
    if bot:
        ch = channel or _default_channel()
        if not ch:
            msg = "SLACK_DEFAULT_CHANNEL is required when using SLACK_BOT_TOKEN without a webhook."
            if required:
                raise SystemExit(msg)
            print(msg, file=sys.stderr)
            return False
        return _post_bot(bot, ch, text, blocks=blocks, thread_ts=thread_ts, required=required)

    # Webhook can't do threads — fall back to webhook plain post
    if webhook:
        return _post_webhook(webhook, text, blocks=blocks, required=required)

    return False


def _post_webhook(
    url: str,
    text: str,
    *,
    blocks: list[dict[str, Any]] | None,
    required: bool,
) -> bool:
    payload: dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status != 200 or body.strip() != "ok":
                msg = f"Slack webhook unexpected response: HTTP {resp.status} {body!r}"
                if required:
                    raise SystemExit(msg)
                print(msg, file=sys.stderr)
                return False
            return True
    except urllib.error.URLError as exc:
        msg = f"Slack webhook request failed: {exc}"
        if required:
            raise SystemExit(msg) from exc
        print(msg, file=sys.stderr)
        return False


def _post_bot(
    token: str,
    channel: str,
    text: str,
    *,
    blocks: list[dict[str, Any]] | None,
    thread_ts: str | None,
    required: bool,
) -> bool:
    payload: dict[str, Any] = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if thread_ts:
        payload["thread_ts"] = thread_ts
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            if not body.get("ok"):
                msg = f"Slack chat.postMessage failed: {body.get('error', body)}"
                if required:
                    raise SystemExit(msg)
                print(msg, file=sys.stderr)
                return False
            return True
    except urllib.error.URLError as exc:
        msg = f"Slack Bot API request failed: {exc}"
        if required:
            raise SystemExit(msg) from exc
        print(msg, file=sys.stderr)
        return False


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}


def _header(text: str) -> dict[str, Any]:
    return {"type": "header", "text": {"type": "plain_text", "text": text[:150], "emoji": True}}


def _context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text[:2000]}]}


def post_claimed(
    agent: str,
    request: str,
    reason: str,
    *,
    channel: str | None = None,
    thread_ts: str | None = None,
    required: bool = True,
) -> bool:
    p = _prefix()
    text = f"{p} agent claimed — `{agent}`: {request}"
    blocks = [
        _header(f"{p} · claimed"),
        _section(f"*Agent:* `{agent}`\n*Request:* {request}\n*Reason:* {reason}"),
    ]
    return post_message(text, blocks=blocks, channel=channel, thread_ts=thread_ts, required=required)


def post_test_report(
    report: TestReport,
    *,
    channel: str | None = None,
    thread_ts: str | None = None,
    required: bool = True,
) -> bool:
    p = _prefix()
    status = "PASS" if report.ok else "FAIL"
    summary = (
        f"*Suite:* `{report.suite}`\n"
        f"*Result:* {status}\n"
        f"Passed {report.passed} · Failed {report.failed} · "
        f"Skipped {report.skipped} · Errors {report.errors}\n"
        f"Duration: {report.duration_seconds}s"
    )
    blocks: list[dict[str, Any]] = [
        _header(f"{p} · tests {status}"),
        _section(summary),
    ]
    if report.failing_nodeids:
        fails = "\n".join(f"• `{n}`" for n in report.failing_nodeids[:15])
        if len(report.failing_nodeids) > 15:
            fails += f"\n• …and {len(report.failing_nodeids) - 15} more"
        blocks.append(_section(f"*Failures*\n{fails}"))
    if report.log_path:
        blocks.append(_context(f"Log: `{report.log_path}`"))
    return post_message(
        f"{p} tests {status}: {report.suite}",
        blocks=blocks,
        channel=channel,
        thread_ts=thread_ts,
        required=required,
    )


def post_analytics_report(
    report: AnalyticsReport,
    *,
    channel: str | None = None,
    thread_ts: str | None = None,
    required: bool = True,
) -> bool:
    p = _prefix()
    metric_lines = []
    for k, v in list(report.metrics.items())[:20]:
        metric_lines.append(f"• `{k}`: `{v}`")
    body = f"*{report.title}*\nArea: `{report.area}`"
    if metric_lines:
        body += "\n\n*Metrics*\n" + "\n".join(metric_lines)
    blocks: list[dict[str, Any]] = [
        _header(f"{p} · analytics · {report.area}"),
        _section(body),
    ]
    if report.notes:
        notes = "\n".join(f"• {n}" for n in report.notes[:12])
        blocks.append(_section(f"*Notes*\n{notes}"))
    if report.recommendations:
        rec_lines = "\n".join(
            f"• [{r.severity}] `{r.id}` — {r.title}" for r in report.recommendations[:10]
        )
        blocks.append(_section(f"*Recommendations*\n{rec_lines}"))
    return post_message(
        f"{p} analytics ({report.area}): {report.title}",
        blocks=blocks,
        channel=channel,
        thread_ts=thread_ts,
        required=required,
    )


def post_recommendations(
    recs: list[Recommendation],
    *,
    title: str = "Recommendations",
    channel: str | None = None,
    thread_ts: str | None = None,
    required: bool = True,
) -> bool:
    p = _prefix()
    if not recs:
        text = f"{p} — {title}: none"
        blocks = [_header(f"{p} · {title}"), _section("_No recommendations._")]
        return post_message(text, blocks=blocks, channel=channel, thread_ts=thread_ts, required=required)

    lines = []
    for rec in recs[:25]:
        lines.append(f"• *[{rec.severity}/{rec.area}]* `{rec.id}` — {rec.title}")
        lines.append(f"  _{rec.rationale[:200]}_")
    blocks = [
        _header(f"{p} · {title}"),
        _section(f"{len(recs)} item(s)\n\n" + "\n".join(lines)[:2800]),
        _context("Approve with: `python -m agents.implement_fix.apply --approve <id>`"),
    ]
    return post_message(
        f"{p} {title}: {len(recs)}",
        blocks=blocks,
        channel=channel,
        thread_ts=thread_ts,
        required=required,
    )


def post_blocked(
    title: str,
    detail: str,
    *,
    channel: str | None = None,
    thread_ts: str | None = None,
    required: bool = True,
) -> bool:
    p = _prefix()
    blocks = [
        _header(f"{p} · blocked"),
        _section(f"*{title}*\n{detail}"),
    ]
    return post_message(
        f"{p} blocked: {title}",
        blocks=blocks,
        channel=channel,
        thread_ts=thread_ts,
        required=required,
    )


def post_implement_packet(
    rec_id: str,
    rec_title: str,
    task_path: str,
    *,
    github_issue_url: str | None = None,
    channel: str | None = None,
    thread_ts: str | None = None,
    required: bool = True,
) -> bool:
    p = _prefix()
    issue = github_issue_url or "_none_"
    blocks = [
        _header(f"{p} · implement packet"),
        _section(
            f"*Id:* `{rec_id}`\n*Title:* {rec_title}\n"
            f"*Task:* `{task_path}`\n*GitHub issue:* {issue}"
        ),
    ]
    return post_message(
        f"{p} implement packet: {rec_id}",
        blocks=blocks,
        channel=channel,
        thread_ts=thread_ts,
        required=required,
    )


def post_dispatch_result(
    result: dict[str, Any],
    *,
    channel: str | None = None,
    thread_ts: str | None = None,
    required: bool = True,
) -> bool:
    """Route a local.dispatch() result dict to the right Slack formatter."""
    kind = result.get("type")
    if kind == "TestReport":
        data = result["report"]
        report = TestReport(**{k: data[k] for k in TestReport.__dataclass_fields__ if k in data})
        return post_test_report(report, channel=channel, thread_ts=thread_ts, required=required)
    if kind == "AnalyticsReport":
        data = result["report"]
        recs = [Recommendation(**r) for r in data.get("recommendations", [])]
        report = AnalyticsReport(
            area=data["area"],
            title=data["title"],
            metrics=data.get("metrics", {}),
            notes=data.get("notes", []),
            recommendations=recs,
            created_at=data.get("created_at", ""),
        )
        return post_analytics_report(report, channel=channel, thread_ts=thread_ts, required=required)
    if kind == "Recommendations":
        recs = [Recommendation(**r) for r in result.get("recommendations", [])]
        return post_recommendations(recs, channel=channel, thread_ts=thread_ts, required=required)
    if kind == "ImplementPacket":
        rec = result.get("recommendation", {})
        return post_implement_packet(
            rec.get("id", "?"),
            rec.get("title", "?"),
            result.get("task_path", "?"),
            github_issue_url=result.get("github_issue_url"),
            channel=channel,
            thread_ts=thread_ts,
            required=required,
        )
    return post_message(
        f"{_prefix()} result: `{kind}`\n```{json.dumps(result)[:2500]}```",
        channel=channel,
        thread_ts=thread_ts,
        required=required,
    )


def ping() -> bool:
    """Verify Slack credentials with a short message."""
    load_agent_env()
    if not slack_configured():
        raise SystemExit(
            "Neither SLACK_WEBHOOK_URL nor SLACK_BOT_TOKEN is set.\n"
            "See agents/docs/slack-setup.md"
        )
    ok = post_message(
        f"{_prefix()} Slack ping — outbound integration OK",
        blocks=[
            _header(f"{_prefix()} · ping"),
            _section("Outbound Slack integration is working."),
            _context(
                f"webhook={'yes' if _webhook_url() else 'no'} · "
                f"bot={'yes' if _bot_token() else 'no'} · "
                f"channel=`{_default_channel() or 'n/a'}`"
            ),
        ],
        required=True,
    )
    return ok


def main(argv: list[str] | None = None) -> int:
    load_agent_env()
    parser = argparse.ArgumentParser(description="GradGPS Slack reporter")
    parser.add_argument("--ping", action="store_true", help="Send a test message")
    parser.add_argument("--text", help="Plain text message")
    parser.add_argument("--test-report", type=Path, help="Path to TestReport JSON")
    parser.add_argument("--analytics-report", type=Path, help="Path to AnalyticsReport JSON")
    parser.add_argument("--recommendations", type=Path, help="Path to recommendations-latest.json")
    parser.add_argument("--channel", help="Override channel (bot token path)")
    args = parser.parse_args(argv)

    if args.ping:
        ping()
        print("Ping sent.")
        return 0
    if args.text:
        post_message(args.text, channel=args.channel)
        return 0
    if args.test_report:
        data = json.loads(args.test_report.read_text(encoding="utf-8"))
        report = TestReport(**{k: data[k] for k in TestReport.__dataclass_fields__ if k in data})
        post_test_report(report, channel=args.channel)
        return 0
    if args.analytics_report:
        data = json.loads(args.analytics_report.read_text(encoding="utf-8"))
        recs = [Recommendation(**r) for r in data.get("recommendations", [])]
        report = AnalyticsReport(
            area=data["area"],
            title=data["title"],
            metrics=data.get("metrics", {}),
            notes=data.get("notes", []),
            recommendations=recs,
            created_at=data.get("created_at", ""),
        )
        post_analytics_report(report, channel=args.channel)
        return 0
    if args.recommendations:
        data = json.loads(args.recommendations.read_text(encoding="utf-8"))
        recs = [Recommendation(**r) for r in data.get("recommendations", [])]
        post_recommendations(recs, channel=args.channel)
        return 0

    parser.error("Provide --ping, --text, --test-report, --analytics-report, or --recommendations")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
