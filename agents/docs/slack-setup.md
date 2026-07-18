# Slack setup for GradGPS agents

Dev-team only. Agents post test/analytics/recommendations to Slack and can be
kicked off from Slack. They are **not** part of the student app.

## What you get

| Path | Direction | Needs |
|------|-----------|-------|
| Incoming Webhook | Agents → Slack | `SLACK_WEBHOOK_URL` |
| Bot + Socket Mode | Slack → Agents (and replies) | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |
| Optional Bot posts | Agents → channel/thread | `SLACK_BOT_TOKEN` + `SLACK_DEFAULT_CHANNEL` |

Recommended: **Webhook + Socket Mode bot** together.

---

## 1. Create a Slack app

1. Open [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. Name it e.g. `GradGPS Agents`, pick your workspace.

### Incoming Webhook (outbound reports)

1. **Incoming Webhooks** → On → **Add New Webhook to Workspace**.
2. Choose channel `#gradgps-agents` (create it if needed).
3. Copy the Webhook URL → `SLACK_WEBHOOK_URL` in `agents/runtime/.env`.

### Bot + Socket Mode (inbound `/gradgps` and @mentions)

1. **Socket Mode** → Enable → create an **App-Level Token** with scope `connections:write`.
   - Copy `xapp-...` → `SLACK_APP_TOKEN`.
2. **OAuth & Permissions** → Bot Token Scopes:
   - `chat:write`
   - `commands`
   - `app_mentions:read`
   - `channels:history` (optional, for context)
3. **Install to Workspace** → copy Bot User OAuth Token `xoxb-...` → `SLACK_BOT_TOKEN`.
4. **Slash Commands** → Create New Command:
   - Command: `/gradgps`
   - Short description: `Run GradGPS local agents`
   - Escape channels/users: yes
   - (Request URL can be blank when using Socket Mode.)
5. **Event Subscriptions** → Enable → Subscribe to bot events:
   - `app_mention`
6. **App Home** → ensure Messages Tab is available if you want DMs (optional).
7. Invite the bot to `#gradgps-agents`: `/invite @GradGPS Agents`

Set `SLACK_DEFAULT_CHANNEL` to the channel id (`C…`) or `#gradgps-agents` for bot posts/threads.

---

## 2. Local env file

```bash
copy agents\runtime\.env.example agents\runtime\.env
# edit agents/runtime/.env
```

```env
SLACK_ENABLED=1
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_DEFAULT_CHANNEL=#gradgps-agents
```

---

## 3. Verify outbound

```bash
python -m pip install -r agents/requirements.txt
python -m agents.reporter.slack --ping
```

You should see a ping message in the webhook channel.

---

## 4. Run the inbound bot

Keep this process running on a developer machine (local-first):

```bash
python -m agents.reporter.bot
```

Then in Slack:

- `/gradgps ping`
- `/gradgps run timeline tests`
- `/gradgps analyze audit`
- `/gradgps recommendations`
- `@GradGPS Agents analyze catalog`

---

## 5. CLI with Slack

With `SLACK_ENABLED=1`, orchestrator and specialists post automatically.
Override with `--slack` / `--no-slack`.

```bash
python -m agents.orchestrator.run "run transcript tests"
python -m agents.timeline_qa.analyze --slack
python -m agents.recommend.digest --run-all --slack
```

---

## Cursor Cloud Agents Slack (`@cursor`)

Separate product integration: [Cursor Slack docs](https://cursor.com/docs/integrations/slack).
Use that for Cursor Cloud coding agents. **This** `agents/` package is the GradGPS
dev QA/analytics team reporter + local orchestrator bridge. Both can coexist in the
same channel; keep message prefixes distinct (`GradGPS` vs Cursor).
