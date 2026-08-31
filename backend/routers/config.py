"""
App-config router — small public endpoint the mobile client polls at launch.

Serves the version gate: the minimum app version allowed to run, the latest
available version, and where "Update" sends the user. Values resolve from a
stored admin override (set live from the dashboard) → env var → fail-open
default; see app_config.py. Fail-open defaults ("0.0.0") mean an unset gate
never blocks or nags anyone.

  - min_supported_version: below this, the app hard-blocks with an update screen.
  - latest_version:        below this (but >= min), a dismissible "update" nudge.
  - ios_update_url:        where "Update" sends the user (empty → TestFlight).
"""

from fastapi import APIRouter

from app_config import get_app_config

router = APIRouter()


@router.get("/app")
def app_config():
    return get_app_config()
