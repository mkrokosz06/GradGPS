"""
App-config router — small public endpoint the mobile client polls at launch.

Currently serves the version gate: the minimum app version allowed to run and
the latest available version, both read from the environment so they can be
bumped without a code deploy (App Runner env var change → restart).

Defaults are fail-open ("0.0.0"): if nothing is set, no client is ever blocked
or nagged. Set MIN_SUPPORTED_APP_VERSION / LATEST_APP_VERSION in prod to arm it.
"""

import os

from fastapi import APIRouter

router = APIRouter()


@router.get("/app")
def app_config():
    return {
        # Below this, the app hard-blocks with an update screen.
        "min_supported_version": os.getenv("MIN_SUPPORTED_APP_VERSION", "0.0.0"),
        # Below this (but >= min), the app shows a dismissible "update available" nudge.
        "latest_version": os.getenv("LATEST_APP_VERSION", "0.0.0"),
        # Where the "Update" button sends the user (TestFlight public link now,
        # App Store URL later). Empty → the client falls back to opening TestFlight.
        "ios_update_url": os.getenv("IOS_UPDATE_URL", ""),
    }
