"""
OIDC ID-token verification for Google Sign-In and Sign in with Apple.

Both providers issue RS256-signed JWTs whose public keys are published at a
JWKS endpoint. Verification checks, in order:
  1. Signature against the provider's JWKS key matching the token's `kid`
  2. Issuer  (`iss`) — routes the token to the right provider config
  3. Audience (`aud`) — must be one of OUR client IDs for that provider
  4. Expiry  (`exp`)

The canonical user identity is the provider-scoped subject:
    google:<sub>   e.g. google:110169484474386276334
    apple:<sub>    e.g. apple:001234.a1b2c3d4e5f6.0987

Env vars:
    GOOGLE_CLIENT_IDS  comma-separated OAuth client IDs (iOS/Android/Web —
                       Expo flows produce tokens with any of these as aud).
                       GOOGLE_CLIENT_ID (singular) is also honoured.
    APPLE_CLIENT_IDS   comma-separated bundle IDs / Service IDs.
"""

import os
import time
import logging

import httpx
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
APPLE_JWKS_URL  = "https://appleid.apple.com/auth/keys"

GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
APPLE_ISSUER   = "https://appleid.apple.com"

_JWKS_TTL_SECONDS = 3600  # provider keys rotate rarely; refetched on unknown kid


def _env_ids(*names: str) -> set[str]:
    """Union of comma-separated client IDs from one or more env vars."""
    ids: set[str] = set()
    for name in names:
        raw = os.getenv(name, "")
        ids.update(x.strip() for x in raw.split(",") if x.strip())
    return ids


# JWKS cache: url -> {"fetched_at": epoch, "keys": {kid: jwk_dict}}
_jwks_cache: dict[str, dict] = {}


def _fetch_jwks(url: str) -> dict[str, dict]:
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    keys = {k["kid"]: k for k in resp.json().get("keys", []) if "kid" in k}
    _jwks_cache[url] = {"fetched_at": time.time(), "keys": keys}
    return keys


def _get_signing_key(url: str, kid: str) -> dict | None:
    """Return the JWK for `kid`, refetching on cache miss (key rotation)."""
    cached = _jwks_cache.get(url)
    if cached and time.time() - cached["fetched_at"] < _JWKS_TTL_SECONDS:
        keys = cached["keys"]
    else:
        keys = _fetch_jwks(url)
    if kid not in keys and cached is not None:
        # Unknown kid with a warm cache — provider may have rotated keys.
        keys = _fetch_jwks(url)
    return keys.get(kid)


class TokenVerificationError(Exception):
    """Raised when an ID token fails verification. Message is client-safe."""


def verify_id_token(token: str) -> dict:
    """
    Verify a Google or Apple ID token and return identity claims:
        {
          "user_id":        "google:<sub>" | "apple:<sub>",
          "provider":       "google" | "apple",
          "sub":            raw subject,
          "email":          str | None,
          "email_verified": bool,
          "name":           str | None,
        }
    Raises TokenVerificationError on any failure.
    """
    try:
        unverified = jwt.get_unverified_claims(token)
        header     = jwt.get_unverified_header(token)
    except JWTError:
        raise TokenVerificationError("Malformed token.")

    iss = unverified.get("iss", "")
    if iss in GOOGLE_ISSUERS:
        provider, jwks_url = "google", GOOGLE_JWKS_URL
        allowed_aud = _env_ids("GOOGLE_CLIENT_IDS", "GOOGLE_CLIENT_ID")
    elif iss == APPLE_ISSUER:
        provider, jwks_url = "apple", APPLE_JWKS_URL
        allowed_aud = _env_ids("APPLE_CLIENT_IDS", "APPLE_CLIENT_ID")
    else:
        raise TokenVerificationError("Unknown token issuer.")

    if not allowed_aud:
        # Misconfiguration, not a client error — but never accept a token we
        # can't pin to our own client IDs.
        logger.error("No client IDs configured for provider %s", provider)
        raise TokenVerificationError("Sign-in is not configured on the server.")

    kid = header.get("kid")
    if not kid:
        raise TokenVerificationError("Malformed token.")

    try:
        key = _get_signing_key(jwks_url, kid)
    except Exception:
        logger.exception("JWKS fetch failed for %s", jwks_url)
        raise TokenVerificationError("Could not verify token right now. Try again.")
    if key is None:
        raise TokenVerificationError("Unknown signing key.")

    try:
        # aud is checked manually below because we accept several client IDs
        # (iOS / Android / Web each have their own).
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except JWTError:
        raise TokenVerificationError("Invalid or expired token.")

    aud = claims.get("aud")
    aud_values = set(aud) if isinstance(aud, list) else {aud}
    if not (aud_values & allowed_aud):
        raise TokenVerificationError("Token was not issued for this app.")

    sub = claims.get("sub")
    if not sub:
        raise TokenVerificationError("Token missing subject.")

    email_verified = claims.get("email_verified")
    if isinstance(email_verified, str):  # Apple sends "true"/"false" strings
        email_verified = email_verified.lower() == "true"

    return {
        "user_id":        f"{provider}:{sub}",
        "provider":       provider,
        "sub":            sub,
        "email":          claims.get("email"),
        "email_verified": bool(email_verified),
        "name":           claims.get("name"),  # Google only; Apple sends name once, client-side
    }
