"""Admin console API (/api/admin/*).

Every route requires a signed-in administrator (checked against the database on
each call). Every change is written to the audit log. Admins can manage accounts
and trips but cannot read trip content: the console shows metadata only.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

import accounts
import backend
import config
import oauth_google
import observability
import web_common as web
from web_common import current_admin

logger = logging.getLogger("tripmate.admin")
router = APIRouter(prefix="/api/admin")

_THREAD_ID = re.compile(r"^trip_[0-9a-f]{32}$")
_USER_ID = re.compile(r"^usr_[0-9a-f]{32}$")
APP_VERSION = "2.2.0"


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(user|admin)$")
    is_active: bool | None = None
    verify_email: bool | None = None


def _users():
    return backend.get_user_store()


def _admin_view(user: dict[str, Any], trips: int = 0) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user.get("role", "user"),
        "email_verified": user["email_verified"],
        "has_password": user["has_password"],
        "has_google": user["has_google"],
        "is_active": user["is_active"],
        "created_at": user["created_at"],
        "last_login": user["last_login"],
        "trips": trips,
    }


def _audit(admin: dict[str, Any], request: Request, action: str, target: str = "", detail: str = "") -> None:
    observability.audit(admin, action, target, detail, web.client_ip(request))


def _guard_last_admin(target: dict[str, Any]) -> str | None:
    """Return a message if changing/removing this admin would leave nobody in charge."""
    if target.get("role") == "admin" and _users().user_counts()["admins"] <= 1:
        return "This is the only administrator. Make someone else an administrator first."
    return None


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
@router.get("/overview")
def overview(admin: dict = Depends(current_admin)):
    trips = backend.get_registry().counts()
    store = observability.get_store()
    return {
        "success": True,
        "users": _users().user_counts(),
        "trips": {"by_status": trips["by_status"], "last_24h": trips["last_24h"],
                  "total": sum(trips["by_status"].values())},
        "requests": store.request_stats(24),
        "sql": observability.sql_log.summary(),
        "ready": backend.check_ready(),
    }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@router.get("/users")
def list_users(
    q: str = Query("", max_length=100),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(current_admin),
):
    rows, total = _users().list_users(q, limit, offset)
    per_owner = backend.get_registry().counts()["per_owner"]
    return {"success": True, "total": total, "users": [_admin_view(u, per_owner.get(u["id"], 0)) for u in rows]}


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserUpdate, request: Request, admin: dict = Depends(current_admin)):
    target = _users().get(user_id) if _USER_ID.match(user_id) else None
    if target is None:
        return web.error_response(404, "User not found.")

    is_self = user_id == admin["id"]
    changes: list[str] = []

    if body.role is not None and body.role != target.get("role", "user"):
        if is_self:
            return web.error_response(400, "You cannot change your own role.")
        if body.role == "user" and (problem := _guard_last_admin(target)):
            return web.error_response(400, problem)
        if body.role == "admin" and not target["email_verified"]:
            return web.error_response(400, "Only users with a verified email can become administrators.")
        _users().set_role(user_id, body.role)
        changes.append(f"role={body.role}")

    if body.is_active is not None and body.is_active != target["is_active"]:
        if is_self:
            return web.error_response(400, "You cannot disable your own account.")
        if not body.is_active and (problem := _guard_last_admin(target)):
            return web.error_response(400, problem)
        _users().set_active(user_id, body.is_active)
        changes.append("enabled" if body.is_active else "disabled")

    if body.verify_email and not target["email_verified"]:
        _users().mark_verified(user_id)
        changes.append("email verified")

    if changes:
        _audit(admin, request, "user.update", target["email"], ", ".join(changes))
    updated = _users().get(user_id)
    return {"success": True, "user": _admin_view(updated or target)}


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(user_id: str, request: Request, admin: dict = Depends(current_admin)):
    target = _users().get(user_id) if _USER_ID.match(user_id) else None
    if target is None:
        return web.error_response(404, "User not found.")
    _users().revoke_sessions(user_id)
    _audit(admin, request, "user.revoke_sessions", target["email"])
    return {"success": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, request: Request, admin: dict = Depends(current_admin)):
    target = _users().get(user_id) if _USER_ID.match(user_id) else None
    if target is None:
        return web.error_response(404, "User not found.")
    if user_id == admin["id"]:
        return web.error_response(400, "Use the Account page to delete your own account.")
    if problem := _guard_last_admin(target):
        return web.error_response(400, problem)

    removed = backend.delete_account(user_id)
    _audit(admin, request, "user.delete", target["email"], f"{removed} trip(s) removed")
    return {"success": True, "trips_deleted": removed}


# ---------------------------------------------------------------------------
# Trips (metadata only)
# ---------------------------------------------------------------------------
@router.get("/trips")
def list_trips(
    status: str = Query("", pattern="^(|running|awaiting_approval|completed|blocked|failed)$"),
    owner: str = Query("", max_length=60),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(current_admin),
):
    rows, total = backend.get_registry().list_all(status, owner, limit, offset)
    emails: dict[str, str] = {}
    trips = []
    for row in rows:
        owner_id = row["owner_id"]
        if owner_id not in emails:
            user = _users().get(owner_id)
            emails[owner_id] = user["email"] if user else "(deleted user)"
        trips.append({**row, "owner_email": emails[owner_id]})
    return {"success": True, "total": total, "trips": trips}


@router.delete("/trips/{thread_id}")
def delete_trip(thread_id: str, request: Request, admin: dict = Depends(current_admin)):
    if not _THREAD_ID.match(thread_id):
        return web.error_response(404, "Trip not found.")
    try:
        row = backend.get_registry().get(thread_id)
        backend.admin_delete_trip(thread_id)
    except backend.ThreadNotFoundError:
        return web.error_response(404, "Trip not found.")
    _audit(admin, request, "trip.delete", thread_id, f"owner={row['owner_id'] if row else '?'}")
    return {"success": True}


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
@router.get("/logs/requests")
def request_logs(
    status: str = Query("", pattern=r"^(|[1-5]xx|[1-5][0-9]{2})$"),
    method: str = Query("", pattern="^(|GET|POST|PUT|PATCH|DELETE)$"),
    path: str = Query("", max_length=100),
    user_id: str = Query("", max_length=60),
    min_ms: float = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(current_admin),
):
    rows = observability.get_store().query_requests(
        status=status, method=method, path=path, user_id=user_id, min_ms=min_ms, limit=limit, offset=offset
    )
    return {"success": True, "logs": rows}


@router.get("/logs/sql")
def sql_logs(
    q: str = Query("", max_length=100),
    slow: bool = False,
    errors: bool = False,
    limit: int = Query(100, ge=1, le=500),
    admin: dict = Depends(current_admin),
):
    return {
        "success": True,
        "enabled": config.LOG_SQL,
        "slow_threshold_ms": config.SLOW_QUERY_MS,
        "summary": observability.sql_log.summary(),
        "logs": observability.sql_log.query(q, slow, errors, limit),
    }


@router.get("/logs/audit")
def audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(current_admin),
):
    return {"success": True, "logs": observability.get_store().query_audit(limit, offset)}


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
@router.get("/system")
def system_info(admin: dict = Depends(current_admin)):
    """Non-secret settings, for support. Secrets are reported only as configured / not."""
    return {
        "success": True,
        "version": APP_VERSION,
        "ready": backend.check_ready(),
        "settings": {
            "model": config.GROQ_MODEL,
            "max_revisions": config.MAX_REVISIONS,
            "plans_per_user_per_hour": config.MAX_PLANS_PER_USER_PER_HOUR,
            "plans_per_day": config.MAX_PLANS_PER_DAY,
            "session_hours": round(config.SESSION_TTL_SECONDS / 3600, 1),
            "trip_retention_days": config.RETENTION_DAYS,
            "log_retention_days": config.LOG_RETENTION_DAYS,
            "slow_query_ms": config.SLOW_QUERY_MS,
            "sql_logging": config.LOG_SQL,
            "public_base_url": config.PUBLIC_BASE_URL or "(from request)",
            "admin_emails_configured": len(config.ADMIN_EMAILS),
        },
        "integrations": {
            "google_sign_in": oauth_google.configured(),
            "email_delivery": bool(config.SMTP_HOST),
            "database_ssl": "sslmode=disable" not in config.get_database_url() if _has_db_url() else None,
        },
        "password_policy": {"min_length": config.MIN_PASSWORD_LENGTH, "roles": list(accounts.ROLES)},
    }


def _has_db_url() -> bool:
    import os

    return bool(os.getenv("DATABASE_URL"))


@router.post("/system/purge")
def purge_now(request: Request, admin: dict = Depends(current_admin)):
    removed = backend.purge_expired()
    _audit(admin, request, "system.purge", "", f"{removed} expired trip(s)")
    return {"success": True, "trips_removed": removed}
