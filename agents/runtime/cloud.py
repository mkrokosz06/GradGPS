"""
Cloud runtime — not wired yet. Local development uses agents.runtime.local.
"""

from __future__ import annotations

from agents.shared.schemas import DispatchPlan


def dispatch(plan: DispatchPlan, *, approve_id: str | None = None) -> dict:
    raise NotImplementedError(
        "Cloud dispatch is not implemented yet. Use agents.runtime.local "
        "(python -m agents.orchestrator.run). Scheduled GitHub Actions come in a later phase."
    )
