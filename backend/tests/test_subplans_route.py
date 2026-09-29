"""
GET /audit/subplans — the mobile major picker calls it before saving a major.

It was deleted by accident once (Sept 2 2026) and nothing noticed: onboarding
showed "Could not check tracks." and never saved the major. These tests pin
that the route is mounted and that it pulls option names out of group names.

Run either way:
  * pytest:       cd backend && python -m pytest tests/test_subplans_route.py -v
  * plain python: cd backend && python tests/test_subplans_route.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers import audit  # noqa: E402


class _FakeTable:
    def __init__(self, groups):
        self._items = [{"requirement_group": g} for g in groups]

    def query(self, **_kwargs):
        return {"Items": self._items}


def test_route_is_mounted_on_the_app():
    import main
    # FastAPI keeps included routers nested, so read the mounted paths from the
    # generated OpenAPI schema rather than app.routes.
    assert "/audit/subplans" in main.app.openapi()["paths"]


def test_extracts_option_names():
    real = audit.requirements_table
    audit.requirements_table = _FakeTable([
        "Common Requirements for the Major (All Options)",
        "Forensic Chemistry Option (20-22 credits)",
        "Forensic Molecular Biology Option: (21 credits)",
        "Requirements for the Major",
        "Forensic Chemistry Option at University Park Campus",
    ])
    try:
        out = audit.get_subplans("Forensic Science, B.S.")
    finally:
        audit.requirements_table = real
    assert out == {"major": "Forensic Science, B.S.",
                   "subplans": ["Forensic Chemistry", "Forensic Molecular Biology"]}


def test_major_without_options_returns_empty_list():
    real = audit.requirements_table
    audit.requirements_table = _FakeTable(["Requirements for the Major", "General Education"])
    try:
        assert audit.get_subplans("Accounting, B.S. (Business)")["subplans"] == []
    finally:
        audit.requirements_table = real


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} passed")
