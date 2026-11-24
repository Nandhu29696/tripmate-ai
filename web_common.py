"""Helpers shared by the app and the account routes."""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

import backend
import config
import security

SESSION_COOKIE = "tm_session"


class AuthError(Exception):
    """The caller is not signed in (or the session was revoked)."""


class ForbiddenError(Exception):
    """The caller is signed in but not allowed to do this."""


def error_response(status: int, message: str, headers: dict[str, str] | None = None, **extra):
    return JSONResponse(
        status_code=status,
        content={"success": False, "error": message, "request_id": config.request_id_var.get(), **extra},
        headers=headers,
    )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def base_url(request: Request) -> str:
    """Public site URL: PUBLIC_BASE_URL if set, else the request's own origin."""
    return config.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")


def set_session_cookie(response: Response, request: Request, user_id: str) -> None:
    # Lax (not Strict): the cookie must survive the redirect back from Google and
    # from email links. State-changing requests are POST/DELETE with an Origin check.
    response.set_cookie(
        SESSION_COOKIE,
        security.issue_session_token(user_id),
        max_age=config.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def is_admin(user: dict[str, Any]) -> bool:
    return user.get("role") == "admin" and user.get("email_verified", False)


def promote_configured_admin(user: dict[str, Any]) -> dict[str, Any]:
    """Make a verified user an administrator if their address is in ADMIN_EMAILS."""
    if user["email"] in config.ADMIN_EMAILS and user["email_verified"] and user.get("role") != "admin":
        backend.get_user_store().set_role(user["id"], "admin")
        return backend.get_user_store().get(user["id"]) or user
    return user


def optional_user(request: Request) -> dict[str, Any] | None:
    """The signed-in user, or None. Rejects revoked sessions and disabled users."""
    payload = security.read_session_token(request.cookies.get(SESSION_COOKIE))
    if not payload:
        return None

    user = backend.get_user_store().get(payload["sid"])
    if not user or not user["is_active"]:
        return None
    if float(payload.get("iat", 0)) < user["sessions_valid_after"]:
        return None  # issued before a password reset / revocation
    request.state.user_id = user["id"]  # for the request log
    return user


def current_user(request: Request) -> dict[str, Any]:
    user = optional_user(request)
    if user is None:
        raise AuthError()
    return user


def current_admin(request: Request) -> dict[str, Any]:
    """Dependency for /api/admin/*: signed in AND an administrator, else 403.

    The role is read from the database on every call, so demoting or disabling an
    admin takes effect immediately, not when their cookie expires.
    """
    user = current_user(request)
    if not is_admin(user):
        raise ForbiddenError()
    return user


def current_session(request: Request) -> str:
    """Dependency: the signed-in user's id (the owner id for trips), or 401."""
    return current_user(request)["id"]


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "email": user["email"],
        "name": user["name"] or user["email"].split("@")[0],
        "has_password": user["has_password"],
        "has_google": user["has_google"],
        "role": "admin" if is_admin(user) else "user",
    }
