# Reporter

Outbound: Incoming Webhook and/or Bot `chat.postMessage` (Block Kit).

```bash
python -m agents.reporter.slack --ping
python -m agents.reporter.slack --text "hello"
```

Inbound Socket Mode bot:

```bash
python -m agents.reporter.bot
```

See `agents/docs/slack-setup.md`.
