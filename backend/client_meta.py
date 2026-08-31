"""
Record the mobile client's app version + last-seen on the user record.

The app tags every request with an `X-App-Version` header (services/api.ts). We
stamp that onto the user's row so the admin dashboard can show who's on which
build — but only from endpoints the app already calls on launch (the degree
audit, the profile load), never from the hot auth path.

The write is throttled: we only touch the row when the reported version changes
or the last_seen day rolls over, so a chatty client doesn't rewrite the row on
every poll. That keeps this to roughly one write per user per active day.
"""

import logging
from datetime import datetime, timezone

from db import users_table

logger = logging.getLogger(__name__)

_MAX_VERSION_LEN = 32  # bound an attacker-controlled header


def touch_client_meta(user_id: str, existing: dict | None, app_version: str | None) -> None:
    """Stamp app_version + last_seen on the user row, throttled to once/day/version.

    `existing` is the caller's already-fetched user record (avoids an extra read);
    pass None if unknown. Never raises — telemetry must not break a real request.
    """
    version = (app_version or "").strip()[:_MAX_VERSION_LEN]

    now_iso = datetime.now(timezone.utc).isoformat()
    today   = now_iso[:10]

    existing   = existing or {}
    prev_ver   = existing.get("app_version", "")
    prev_seen  = existing.get("last_seen", "")

    # Throttle: nothing new to record for today on this version.
    if version == prev_ver and prev_seen[:10] == today:
        return

    fields = {"last_seen": now_iso}
    if version:
        fields["app_version"] = version

    try:
        expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression=expr,
            ExpressionAttributeNames={f"#{k}": k for k in fields},
            ExpressionAttributeValues={f":{k}": v for k, v in fields.items()},
        )
    except Exception:
        logger.warning("Failed to record client meta for %s", user_id, exc_info=True)
