"""Sign in with Google: OAuth 2.0 authorization-code flow with PKCE (OpenID Connect).

Protections: ``state`` (login-CSRF), ``nonce`` (token replay), PKCE (code
interception), ID-token signature/issuer/audience/expiry checked by Google's
own library, and ``email_verified`` required.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

import config
import security

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_TTL_SECONDS = 600


class OAuthError(Exception):
    """The Google sign-in could not be completed. Message is safe to log, not to show."""


def configured() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def redirect_uri(base_url: str) -> str:
    return f"{(config.PUBLIC_BASE_URL or base_url).rstrip('/')}/auth/google/callback"


def start(base_url: str) -> tuple[str, str]:
    """Return (google_url_to_redirect_to, signed_state_cookie_value)."""
    if not configured():
        raise OAuthError("Google sign-in is not configured.")

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    url = AUTH_URL + "?" + urlencode(
        {
            "client_id": config.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri(base_url),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    cookie = security.issue_signed({"s": state, "n": nonce, "v": verifier}, STATE_TTL_SECONDS)
    return url, cookie


def _exchange_code(code: str, verifier: str, base_url: str) -> str:
    """Trade the authorization code for an ID token (replaced in tests)."""
    response = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri(base_url),
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise OAuthError(f"Token endpoint returned {response.status_code}.")
    token = response.json().get("id_token")
    if not token:
        raise OAuthError("No id_token in the token response.")
    return token


def _verify_id_token(raw_token: str) -> dict[str, Any]:
    """Verify signature, issuer, audience and expiry (replaced in tests)."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        return id_token.verify_oauth2_token(raw_token, google_requests.Request(), config.GOOGLE_CLIENT_ID)
    except ValueError as exc:
        raise OAuthError(f"Invalid ID token: {exc}") from exc


def finish(code: str, state_param: str, state_cookie: str | None, base_url: str) -> dict[str, Any]:
    """Complete the login and return the verified Google profile."""
    saved = security.read_signed(state_cookie)
    if not saved or not state_param or not hmac.compare_digest(str(saved.get("s", "")), state_param):
        raise OAuthError("State mismatch or expired login attempt.")

    claims = _verify_id_token(_exchange_code(code, str(saved.get("v", "")), base_url))

    if not hmac.compare_digest(str(claims.get("nonce", "")), str(saved.get("n", ""))):
        raise OAuthError("Nonce mismatch.")
    if claims.get("email_verified") is not True:
        raise OAuthError("The Google account's email is not verified.")
    if not claims.get("sub") or not claims.get("email"):
        raise OAuthError("Missing subject or email.")

    return {
        "sub": str(claims["sub"]),
        "email": str(claims["email"]).strip().lower(),
        "name": str(claims.get("name") or "")[:80],
    }
