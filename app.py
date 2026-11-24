"""TripMate AI - FastAPI application.

Routes are plain ``def`` handlers so FastAPI runs them in its thread pool: a
long LangGraph run no longer blocks the event loop, ``/health`` or other
requests (F-12).
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import queue
import threading
import time
from urllib.parse import urlparse

import uvicorn
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

import admin_routes
import auth_routes
import backend
import config
import observability
import security
import spa
import web_common as web
from web_common import current_session

config.configure_logging()
logger = logging.getLogger("tripmate.api")

THREAD_ID_PATTERN = r"^trip_[0-9a-f]{32}$"
PURGE_INTERVAL_SECONDS = 6 * 3600

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


# =========================
# Lifespan: initialise and tear down resources (F-30)
# =========================
async def _purge_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(backend.purge_expired)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Retention purge failed: %s: %s", type(exc).__name__, exc)
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(backend.init_backend)
    purge_task = asyncio.create_task(_purge_loop())
    try:
        yield
    finally:
        purge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await purge_task
        await asyncio.to_thread(backend.shutdown_backend)


app = FastAPI(
    title="TripMate AI",
    description=(
        "LangGraph Multi-Agent Travel Planner with Supervisor, Guardrails, "
        "Human-in-the-Loop, and FastAPI Frontend"
    ),
    version="2.2.0",
    lifespan=lifespan,
)

app.include_router(auth_routes.router)
app.include_router(admin_routes.router)


# =========================
# Models (bounded input: F-09)
# =========================
class TravelRequest(BaseModel):
    message: str = Field(max_length=config.MAX_MESSAGE_CHARS)

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be empty.")
        return value


class ApprovalRequest(BaseModel):
    thread_id: str = Field(pattern=THREAD_ID_PATTERN)
    approved: bool
    feedback: str = Field(default="", max_length=config.MAX_FEEDBACK_CHARS)


# =========================
# Helpers
# =========================
_error = web.error_response


@app.exception_handler(web.AuthError)
async def _auth_error_handler(request: Request, exc: web.AuthError):
    return _error(401, "Please sign in to continue.", auth_required=True)


@app.exception_handler(web.ForbiddenError)
async def _forbidden_handler(request: Request, exc: web.ForbiddenError):
    return _error(403, "You do not have access to this.")


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    message = str(first.get("msg", "Invalid request.")).removeprefix("Value error, ")
    field = ".".join(str(part) for part in first.get("loc", [])[1:])
    return _error(400, f"{field}: {message}" if field and "empty" not in message.lower() else message)


def _failure_parts(exc: Exception, what: str) -> tuple[int, str, dict[str, str]]:
    """Map internal failures to a safe (status, message, headers) (F-07, F-17)."""
    if isinstance(exc, backend.ThreadNotFoundError):
        return 404, "Trip not found.", {}
    if isinstance(exc, backend.ThreadStateError):
        return 409, str(exc), {}

    try:
        import groq
    except ImportError:  # pragma: no cover
        groq = None

    if groq is not None:
        if isinstance(exc, groq.RateLimitError):
            retry = "30"
            with contextlib.suppress(Exception):
                retry = str(int(float(exc.response.headers.get("retry-after", "30"))) or 30)
            logger.warning("%s: upstream rate limit", what)
            return 429, "The AI service is busy right now. Please try again shortly.", {"Retry-After": retry}
        if isinstance(exc, (groq.APITimeoutError, groq.APIConnectionError)):
            logger.warning("%s: upstream unavailable: %s", what, type(exc).__name__)
            return 503, "The AI service is temporarily unavailable. Please try again.", {}

    logger.exception("%s failed", what)
    from config import request_id_var

    return 500, f"Something went wrong. Please try again. (reference {request_id_var.get()})", {}


def _handle_failure(exc: Exception, what: str) -> JSONResponse:
    status, message, headers = _failure_parts(exc, what)
    return _error(status, message, headers=headers or None)


# =========================
# Middleware: request id, CSRF origin check, security headers, access log
# =========================
@app.middleware("http")
async def request_context(request: Request, call_next):
    from config import new_request_id, request_id_var

    request_id = new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    response = None
    logged = False

    def log_request(status: int) -> None:
        nonlocal logged
        if logged:
            return
        logged = True
        observability.record_request(
            request.method,
            request.url.path,
            status,
            (time.perf_counter() - started) * 1000,
            getattr(request.state, "user_id", None),
            web.client_ip(request),
            request_id,
        )

    try:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                response = _error(403, "Cross-origin request blocked.")
                return response

        response = await call_next(request)
    finally:
        request_id_var.reset(token)
        if response is None:
            log_request(500)
        elif not hasattr(response, "body_iterator"):
            log_request(response.status_code)  # not streamed: the work is already done

    # Streamed responses (live planning progress) do their work while the body is sent, so
    # their duration is only known when the last chunk has gone out.
    if hasattr(response, "body_iterator"):
        original = response.body_iterator
        status_code = response.status_code

        async def timed_body():
            try:
                async for chunk in original:
                    yield chunk
            finally:
                log_request(status_code)

        response.body_iterator = timed_body()

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = CSP
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

    if request.url.path not in {"/health", "/favicon.ico"} and not request.url.path.startswith("/assets"):
        logger.info(
            "%s %s -> %s in %dms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
    return response


# =========================
# Trip API
# =========================
@app.post("/api/travel")
def travel_planner(body: TravelRequest, sid: str = Depends(current_session)):
    wait = security.acquire_plan_quota(sid)
    if wait:
        return _error(
            429,
            "You have reached the planning limit for now. Please try again later.",
            headers={"Retry-After": str(wait)},
        )

    try:
        return {"success": True, **backend.start_trip(sid, body.message)}
    except Exception as exc:  # noqa: BLE001
        return _handle_failure(exc, "start_trip")


@app.post("/api/travel/approve")
def approve_travel_plan(body: ApprovalRequest, sid: str = Depends(current_session)):
    if not body.approved and not body.feedback.strip():
        return _error(400, "Please provide revision feedback when rejecting the draft.")

    try:
        return {
            "success": True,
            **backend.resume_trip(sid, body.thread_id, body.approved, body.feedback),
        }
    except Exception as exc:  # noqa: BLE001
        return _handle_failure(exc, "resume_trip")


# =========================
# Streaming variants: live progress as NDJSON (one JSON object per line)
# =========================
def _ndjson_stream(work, what: str) -> StreamingResponse:
    """Run ``work(emit)`` in a background thread and relay its events.

    The run is NOT tied to the connection: if the browser goes away the plan
    still finishes and is saved, so it can be restored from "Your trips".
    """
    from config import request_id_var

    events: queue.Queue = queue.Queue()
    request_id = request_id_var.get()

    def worker() -> None:
        try:
            payload = work(events.put)
            events.put({"type": "result", "success": True, **payload})
        except Exception as exc:  # noqa: BLE001
            status, message, headers = _failure_parts(exc, what)
            events.put(
                {
                    "type": "error",
                    "success": False,
                    "status": status,
                    "error": message,
                    "retry_after": headers.get("Retry-After"),
                    "request_id": request_id,
                }
            )
        finally:
            events.put(None)

    context = contextvars.copy_context()
    threading.Thread(target=context.run, args=(worker,), name=f"{what}-stream", daemon=True).start()

    def relay():
        while True:
            try:
                item = events.get(timeout=15)
            except queue.Empty:
                yield b'{"type":"ping"}\n'  # keeps proxies from closing an idle stream
                continue
            if item is None:
                return
            yield (json.dumps(item) + "\n").encode()

    return StreamingResponse(
        relay(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/travel/stream")
def travel_planner_stream(body: TravelRequest, sid: str = Depends(current_session)):
    wait = security.acquire_plan_quota(sid)
    if wait:
        return _error(
            429,
            "You have reached the planning limit for now. Please try again later.",
            headers={"Retry-After": str(wait)},
        )
    return _ndjson_stream(lambda emit: backend.start_trip(sid, body.message, on_event=emit), "start_trip")


@app.post("/api/travel/approve/stream")
def approve_travel_plan_stream(body: ApprovalRequest, sid: str = Depends(current_session)):
    if not body.approved and not body.feedback.strip():
        return _error(400, "Please provide revision feedback when rejecting the draft.")
    try:
        backend.check_resumable(sid, body.thread_id)  # 404/409 stay real HTTP statuses
    except Exception as exc:  # noqa: BLE001
        return _handle_failure(exc, "resume_trip")
    return _ndjson_stream(
        lambda emit: backend.resume_trip(sid, body.thread_id, body.approved, body.feedback, on_event=emit),
        "resume_trip",
    )


@app.get("/api/travel/threads")
def list_trips(sid: str = Depends(current_session)):
    return {"success": True, "trips": backend.list_trips(sid)}


@app.get("/api/travel/{thread_id}")
def get_trip(thread_id: str, sid: str = Depends(current_session)):
    if not _valid_thread_id(thread_id):
        return _error(404, "Trip not found.")
    try:
        return {"success": True, **backend.get_trip(sid, thread_id)}
    except Exception as exc:  # noqa: BLE001
        return _handle_failure(exc, "get_trip")


@app.delete("/api/travel/{thread_id}")
def delete_trip(thread_id: str, sid: str = Depends(current_session)):
    if not _valid_thread_id(thread_id):
        return _error(404, "Trip not found.")
    try:
        backend.delete_trip(sid, thread_id)
        return {"success": True}
    except Exception as exc:  # noqa: BLE001
        return _handle_failure(exc, "delete_trip")


def _valid_thread_id(thread_id: str) -> bool:
    import re

    return bool(re.fullmatch(THREAD_ID_PATTERN, thread_id))


# =========================
# Operations
# =========================
@app.get("/health")
def health_check():
    """Liveness: cheap and dependency-free (used by the Docker healthcheck)."""
    return {
        "status": "ok",
        "message": "TripMate AI API is running",
        "features": ["supervisor_agent", "input_guardrail", "human_in_the_loop"],
    }


@app.get("/ready")
def readiness_check():
    """Readiness: verifies the database is reachable."""
    state = backend.check_ready()
    return JSONResponse(status_code=200 if state["ready"] else 503, content=state)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


# Must be last: its catch-all route only sees paths no other route handled.
spa.mount_spa(app, config.FRONTEND_DIST)


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
