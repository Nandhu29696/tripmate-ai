"""Account routes: email + password, Google sign-in, session, account deletion.

Design rules:
- Responses never reveal whether an email is registered (register and
  forgot-password answer identically either way, and do the same work).
- Email addresses are only trusted after the owner proves control: via a
  one-time emailed link, or via Google's verified email.
- Failed logins are throttled per IP and per account.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

import accounts
import backend
import config
import mailer
import oauth_google
import security
import web_common as web

logger = logging.getLogger("tripmate.auth")
router = APIRouter()

OAUTH_COOKIE = "tm_oauth"
GENERIC_REGISTER = "If this address can be registered, we have sent a confirmation link. Please check your email."
GENERIC_FORGOT = "If an account exists for that address, we have sent a password reset link."


class RegisterRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    name: str = Field(default="", max_length=80)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class ForgotRequest(BaseModel):
    email: str = Field(max_length=254)


class ResetRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(max_length=200)


class DeleteAccountRequest(BaseModel):
    confirm: bool


def _users():
    return backend.get_user_store()


def _link(request: Request, path: str, token: str) -> str:
    return f"{web.base_url(request)}{path}{token}"


def _send_verification(user: dict, request: Request) -> None:
    token, hashed = accounts.new_token()
    _users().add_token(user["id"], "verify", hashed, config.VERIFY_TOKEN_TTL_SECONDS)
    mailer.send_email(
        user["email"],
        "Confirm your TripMate AI account",
        "Welcome to TripMate AI!\n\nConfirm your email address to finish creating your account:\n\n"
        f"{_link(request, '/auth/verify?token=', token)}\n\n"
        f"This link works once and expires in {config.VERIFY_TOKEN_TTL_SECONDS // 3600} hours. "
        "If you did not create an account, you can ignore this message.\n",
    )


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _signed_in(request: Request, response, user: dict) -> None:
    web.promote_configured_admin(user)
    _users().touch_login(user["id"])
    web.set_session_cookie(response, request, user["id"])


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
@router.get("/api/session")
def session_status(request: Request):
    user = web.optional_user(request)
    return {
        "success": True,
        "authenticated": user is not None,
        "user": web.public_user(user) if user else None,
        "providers": {"google": oauth_google.configured(), "password": True},
    }


@router.delete("/api/session")
def logout():
    response = JSONResponse({"success": True})
    web.clear_session_cookie(response)
    return response


# ---------------------------------------------------------------------------
# Email + password
# ---------------------------------------------------------------------------
@router.post("/api/auth/register")
def register(body: RegisterRequest, request: Request):
    email = accounts.normalize_email(body.email)
    problem = accounts.validate_email(email) or accounts.validate_password(body.password, email)
    if problem:
        # Rejected input costs nothing (no email, no database write), so it is not throttled.
        return web.error_response(400, problem)

    wait = security.register_limiter.try_acquire(web.client_ip(request))
    if wait:
        return web.error_response(429, "Too many sign-up attempts. Please try again later.",
                                  headers={"Retry-After": str(wait)})

    # Always hash, so the response time does not reveal whether the email exists.
    password_hash = accounts.hash_password(body.password)
    existing = _users().get_by_email(email)

    if existing is None:
        try:
            user = _users().create_user(email, body.name.strip(), password_hash, None, False)
            _send_verification(user, request)
        except accounts.DuplicateEmailError:
            pass  # lost a race with a concurrent sign-up; same generic answer
    elif not existing["email_verified"]:
        if security.resend_limiter.try_acquire(email) == 0:
            _send_verification(existing, request)  # the password already on file is kept
    else:
        mailer.send_email(
            email,
            "You already have a TripMate AI account",
            "Someone (hopefully you) tried to create a TripMate AI account with this address, "
            "but one already exists.\n\nTo sign in, use the Sign in page. If you forgot your "
            "password, use 'Forgot password' to reset it.\n",
        )

    return {"success": True, "message": GENERIC_REGISTER}


@router.get("/auth/verify")
def verify_email(request: Request, token: str = ""):
    user_id = _users().consume_token(accounts.hash_token(token), "verify") if token else None
    if not user_id:
        return _redirect("/?auth_error=invalid_link")

    _users().mark_verified(user_id)
    user = _users().get(user_id)
    if not user or not user["is_active"]:
        return _redirect("/?auth_error=invalid_link")

    response = _redirect("/?verified=1")
    _signed_in(request, response, user)
    return response


@router.post("/api/auth/login")
def login(body: LoginRequest, request: Request):
    ip = web.client_ip(request)
    email = accounts.normalize_email(body.email)

    wait = max(security.login_failures_ip.retry_after(ip), security.login_failures_email.retry_after(email))
    if wait:
        return web.error_response(429, "Too many failed attempts. Please wait and try again.",
                                  headers={"Retry-After": str(wait)})

    user = _users().get_by_email(email)
    # verify_password does equivalent work even when there is no such account.
    stored = _users().get_password_hash(user["id"]) if user and user["has_password"] else None
    password_ok = accounts.verify_password(body.password, stored)

    if not (user and password_ok and user["is_active"]):
        security.login_failures_ip.record(ip)
        security.login_failures_email.record(email)
        logger.warning("Failed sign-in from %s", ip)
        return web.error_response(401, "Invalid email or password.", auth_required=True)

    if not user["email_verified"]:
        if security.resend_limiter.try_acquire(email) == 0:
            _send_verification(user, request)
        return web.error_response(
            403, "Please confirm your email first. We have sent you a new confirmation link.",
            code="email_not_verified",
        )

    response = JSONResponse({"success": True, "authenticated": True})
    _signed_in(request, response, user)
    return response


@router.post("/api/auth/forgot")
def forgot_password(body: ForgotRequest, request: Request):
    if security.forgot_ip_limiter.try_acquire(web.client_ip(request)):
        return web.error_response(429, "Too many requests. Please try again later.")

    email = accounts.normalize_email(body.email)
    user = _users().get_by_email(email) if not accounts.validate_email(email) else None

    if user and user["is_active"] and security.forgot_limiter.try_acquire(email) == 0:
        token, hashed = accounts.new_token()
        _users().add_token(user["id"], "reset", hashed, config.RESET_TOKEN_TTL_SECONDS)
        mailer.send_email(
            email,
            "Reset your TripMate AI password",
            "We received a request to reset your TripMate AI password.\n\n"
            f"{_link(request, '/?reset=', token)}\n\n"
            f"This link works once and expires in {config.RESET_TOKEN_TTL_SECONDS // 60} minutes. "
            "If you did not ask for this, you can ignore this message; your password has not changed.\n",
        )

    return {"success": True, "message": GENERIC_FORGOT}


@router.post("/api/auth/reset")
def reset_password(body: ResetRequest, request: Request):
    problem = accounts.validate_password(body.password)
    if problem:
        return web.error_response(400, problem)

    user_id = _users().consume_token(accounts.hash_token(body.token), "reset")
    user = _users().get(user_id) if user_id else None
    if not user or not user["is_active"]:
        return web.error_response(400, "This reset link is invalid or has expired. Please request a new one.")

    # Revokes every older session; the reset link proves control of the address.
    _users().set_password(user["id"], accounts.hash_password(body.password), revoke_sessions=True)
    _users().mark_verified(user["id"])
    mailer.send_email(
        user["email"],
        "Your TripMate AI password was changed",
        "Your TripMate AI password was just changed and you were signed out everywhere else.\n"
        "If this was not you, reset your password again immediately.\n",
    )

    response = JSONResponse({"success": True, "authenticated": True})
    _signed_in(request, response, _users().get(user["id"]))
    return response


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------
@router.get("/auth/google/login")
def google_login(request: Request):
    if not oauth_google.configured():
        return _redirect("/?auth_error=google_not_configured")

    url, state_cookie = oauth_google.start(web.base_url(request))
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        OAUTH_COOKIE, state_cookie, max_age=oauth_google.STATE_TTL_SECONDS, httponly=True,
        samesite="lax", secure=request.url.scheme == "https", path="/auth/google",
    )
    return response


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return _redirect("/?auth_error=google_denied")

    try:
        profile = oauth_google.finish(code, state, request.cookies.get(OAUTH_COOKIE), web.base_url(request))
        user = _user_for_google_profile(profile)
    except oauth_google.OAuthError as exc:
        logger.warning("Google sign-in failed: %s", exc)
        return _redirect("/?auth_error=google_failed")
    except Exception as exc:  # noqa: BLE001 - network errors etc.
        logger.error("Google sign-in error: %s: %s", type(exc).__name__, exc)
        return _redirect("/?auth_error=google_failed")

    response = _redirect("/")
    response.delete_cookie(OAUTH_COOKIE, path="/auth/google")
    _signed_in(request, response, user)
    return response


def _user_for_google_profile(profile: dict) -> dict:
    users = _users()
    user = users.get_by_google_sub(profile["sub"])

    if user is None:
        existing = users.get_by_email(profile["email"])
        if existing is not None:
            if existing["has_google"]:
                # Same address already tied to a different Google identity: do not merge.
                raise oauth_google.OAuthError("Email already linked to another Google account.")
            if not existing["email_verified"] and existing["has_password"]:
                # Pre-hijack defence: a password set by someone who never proved they own
                # the address must not survive the real owner signing in with Google.
                users.set_password(existing["id"], None, revoke_sessions=True)
            users.link_google(existing["id"], profile["sub"], profile["name"])
            user = users.get(existing["id"])
        else:
            user = users.create_user(profile["email"], profile["name"], None, profile["sub"], True)

    if not user or not user["is_active"]:
        raise oauth_google.OAuthError("Account is disabled.")
    return user


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------
@router.post("/api/account/delete")
def delete_account(body: DeleteAccountRequest, request: Request):
    user = web.optional_user(request)
    if user is None:
        raise web.AuthError()
    if not body.confirm:
        return web.error_response(400, "Please confirm that you want to delete your account.")

    removed = backend.delete_account(user["id"])
    response = JSONResponse({"success": True, "trips_deleted": removed})
    web.clear_session_cookie(response)
    return response
