"""
Runtime app-config (the version gate the mobile UpdateGate reads).

Historically the min/latest version lived only in env vars, so nudging users
about an update meant an App Runner env change + restart. To let an admin
publish the "update available" banner live from the dashboard, the values are
stored as a singleton row in the users table (user_id="__APP_CONFIG__", the same
reserved-sentinel pattern as __GEN_ED__ / __CROSSLISTINGS__). Reusing an
existing table avoids a new prod DynamoDB table + IAM grant.

Read precedence: stored value → env var → fail-open default ("0.0.0" / "").
So an unset field still falls back to the env behaviour, and a fresh deploy with
no stored row behaves exactly as before.

The sentinel row is filtered out of the admin user views (see admin.py).
"""

import os
import logging

from db import users_table

logger = logging.getLogger(__name__)

APP_CONFIG_KEY = "__APP_CONFIG__"

# Fields an admin may publish, paired with the env var that seeds each default.
_FIELD_ENV = {
    "min_supported_version": ("MIN_SUPPORTED_APP_VERSION", "0.0.0"),
    "latest_version":        ("LATEST_APP_VERSION",        "0.0.0"),
    "ios_update_url":        ("IOS_UPDATE_URL",            ""),
}


def get_app_config() -> dict:
    """Resolve the version gate: stored override → env var → default."""
    try:
        item = users_table.get_item(Key={"user_id": APP_CONFIG_KEY}).get("Item") or {}
    except Exception:
        # Never let a config-read hiccup take down /config/app — fall back to env.
        logger.warning("app-config read failed; falling back to env", exc_info=True)
        item = {}

    out = {}
    for field, (env_name, default) in _FIELD_ENV.items():
        stored = item.get(field)
        out[field] = stored if stored not in (None, "") else os.getenv(env_name, default)
    return out


def set_app_config(**fields) -> dict:
    """Persist any of the known fields (ignores unknown/None) and return the
    resolved config afterward."""
    updates = {
        k: str(v).strip()
        for k, v in fields.items()
        if k in _FIELD_ENV and v is not None
    }
    if updates:
        expr = "SET " + ", ".join(f"#{k} = :{k}" for k in updates)
        users_table.update_item(
            Key={"user_id": APP_CONFIG_KEY},
            UpdateExpression=expr,
            ExpressionAttributeNames={f"#{k}": k for k in updates},
            ExpressionAttributeValues={f":{k}": v for k, v in updates.items()},
        )
    return get_app_config()
