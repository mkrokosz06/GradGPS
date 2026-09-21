"""
Tests for the App Store review demo sign-in (routers/email_auth._review_account).

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_review_account.py -v
  * plain python:  cd backend && python tests/test_review_account.py

Hermetic — the DynamoDB-backed halves (issue_code/check_code, create_session)
are stubbed, so nothing here needs a table. What is asserted is the *gating*:
that the path does not exist unless both env vars are set, that it can only
ever authenticate the one configured address, and that the static code is
guess-rate-limited (a real one-time code is burned by check_code after
MAX_ATTEMPTS; this one never is).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import email_auth

DEMO = "appreview@example.com"
CODE = "424242"


def _client():
    """Fresh app + cleared rate-limit buckets and stubbed storage."""
    email_auth._by_email.clear()
    email_auth._by_ip.clear()
    email_auth._demo_by_ip.clear()
    email_auth._demo_global.clear()

    # Stub the DynamoDB-backed pieces.
    email_auth.issue_code = lambda email: "999999"
    email_auth.check_code = lambda email, code: False
    email_auth.create_session = lambda claims: {
        "token": "sess_stub", "expires_at": 0, "_claims": claims,
    }

    app = FastAPI()
    app.include_router(email_auth.router, prefix="/auth")
    return TestClient(app)


def _set_env(email, code):
    for k, v in (("REVIEW_EMAIL", email), ("REVIEW_CODE", code)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_unset_is_a_no_op():
    """Both vars unset: the demo path does not exist — the address is just an
    unknown email, and its code is checked by the normal (stubbed, always-false)
    one-time-code machinery."""
    _set_env(None, None)
    c = _client()
    assert email_auth._review_account() is None
    assert c.post("/auth/email/verify",
                  json={"email": DEMO, "code": CODE}).status_code == 401


def test_partial_config_is_a_no_op():
    """Half-configured must not half-enable anything."""
    _set_env(DEMO, None)
    assert email_auth._review_account() is None
    _set_env(None, CODE)
    assert email_auth._review_account() is None
    _set_env(DEMO, "abcdef")          # non-numeric
    assert email_auth._review_account() is None
    _set_env(DEMO, "12345")           # wrong length
    assert email_auth._review_account() is None
    _set_env(None, None)


def test_configured_demo_account_signs_in():
    _set_env(DEMO, CODE)
    c = _client()
    r = c.post("/auth/email/verify",
               json={"email": DEMO, "code": CODE, "name": "Alex Demo"})
    assert r.status_code == 200, r.text
    # The id is derived from the email exactly as the normal OTP path does it.
    assert r.json()["user_id"] == "email:" + DEMO
    _set_env(None, None)


def test_demo_code_authenticates_only_the_demo_address():
    """The single most important property: this is not a master password."""
    _set_env(DEMO, CODE)
    c = _client()
    for other in ("attacker@example.com", "APPREVIEW@example.com.evil.com",
                  "x" + DEMO, DEMO + ".evil"):
        r = c.post("/auth/email/verify", json={"email": other, "code": CODE})
        assert r.status_code == 401, (other, r.status_code)
    _set_env(None, None)


def test_wrong_code_for_demo_address_is_rejected():
    _set_env(DEMO, CODE)
    c = _client()
    assert c.post("/auth/email/verify",
                  json={"email": DEMO, "code": "000000"}).status_code == 401
    _set_env(None, None)


def test_static_code_is_guess_rate_limited():
    """A real one-time code is burned after MAX_ATTEMPTS; the static demo code
    is not, so the endpoint must cap the guess rate itself."""
    _set_env(DEMO, CODE)
    c = _client()
    codes = [c.post("/auth/email/verify",
                    json={"email": DEMO, "code": "000001"}).status_code
             for _ in range(email_auth._DEMO_VERIFY_PER_IP + 5)]
    assert 401 in codes
    assert codes[-1] == 429
    assert codes.count(401) <= email_auth._DEMO_VERIFY_PER_IP
    _set_env(None, None)


def test_start_never_sends_mail_for_the_demo_address():
    """No code is issued or emailed for the demo address — a fixed code means
    there is nothing to send, and nothing to leak."""
    _set_env(DEMO, CODE)
    c = _client()
    issued = []
    email_auth.issue_code = lambda email: issued.append(email) or "999999"
    assert c.post("/auth/email/start", json={"email": DEMO}).json() == {"ok": True}
    assert issued == []
    _set_env(None, None)


def test_normal_otp_path_is_untouched():
    """With the demo account configured, an ordinary address still goes through
    check_code and nothing else."""
    _set_env(DEMO, CODE)
    c = _client()
    seen = []
    email_auth.check_code = lambda email, code: seen.append((email, code)) or True
    r = c.post("/auth/email/verify",
               json={"email": "student@psu.edu", "code": "123456"})
    assert r.status_code == 200
    assert seen == [("student@psu.edu", "123456")]
    assert r.json()["user_id"] == "email:student@psu.edu"
    _set_env(None, None)


if __name__ == "__main__":
    _fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for _fn in _fns:
        _fn()
        print("  ok  " + _fn.__name__)
    print("\n%d passed" % len(_fns))
