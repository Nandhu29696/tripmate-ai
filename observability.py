"""Operational logs for the admin console: API requests, SQL queries, admin audit.

* API requests: one row per request (method, path, status, duration, user, ip).
  The query string is never stored (it can carry one-time tokens). With a
  database they are written in batches by a background thread, so a request
  never waits on its own log line, and survive restarts; without one they live
  in memory.
* SQL queries: a cursor subclass times every statement. Only the statement text
  (whitespace-collapsed, truncated) is kept, NEVER the parameters, because
  parameters hold passwords hashes, tokens and trip text. Kept in a bounded
  in-memory ring (recent history, lost on restart). Slow ones also reach the
  normal log at WARNING.
* Audit: every admin action (who, what, on whom). Kept in the database.
"""

from __future__ import annotations

import collections
import contextvars
import logging
import queue
import re
import threading
import time
from datetime import UTC, datetime
from typing import Any

import config

logger = logging.getLogger("tripmate.obs")
sql_logger = logging.getLogger("tripmate.sql")

_WS = re.compile(r"\s+")
_SKIP_PATHS = ("/health", "/ready", "/favicon.ico", "/assets/")

# Statements issued by the logging code itself are not recorded (no feedback loop).
_LOG_TABLES = ("api_request_logs", "admin_audit_log")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


# ---------------------------------------------------------------------------
# SQL log
# ---------------------------------------------------------------------------
class SqlLog:
    def __init__(self, size: int = 2000) -> None:
        self._rows: collections.deque[dict[str, Any]] = collections.deque(maxlen=size)
        self._lock = threading.Lock()
        self._seq = 0

    def add(self, sql: str, duration_ms: float, error: str = "", rows: int | None = None) -> None:
        text = _WS.sub(" ", sql).strip()
        if any(table in text for table in _LOG_TABLES):
            return
        entry = {
            "ts": _now().isoformat(),
            "sql": text[:600],
            "duration_ms": round(duration_ms, 2),
            "rows": rows,
            "error": error[:200],
            "request_id": config.request_id_var.get(),
            "slow": duration_ms >= config.SLOW_QUERY_MS,
        }
        with self._lock:
            self._seq += 1
            entry["id"] = self._seq
            self._rows.append(entry)
        if entry["slow"]:
            sql_logger.warning("slow query %.0fms: %s", duration_ms, text[:200])
        else:
            sql_logger.debug("%.1fms %s", duration_ms, text[:200])

    def query(self, text: str = "", slow_only: bool = False, errors_only: bool = False,
              limit: int = 100) -> list[dict[str, Any]]:
        needle = text.lower().strip()
        with self._lock:
            rows = list(self._rows)
        out = []
        for row in reversed(rows):
            if slow_only and not row["slow"]:
                continue
            if errors_only and not row["error"]:
                continue
            if needle and needle not in row["sql"].lower():
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return out

    def summary(self) -> dict[str, Any]:
        with self._lock:
            rows = list(self._rows)
        if not rows:
            return {"count": 0, "slow": 0, "errors": 0, "avg_ms": 0, "max_ms": 0}
        durations = [r["duration_ms"] for r in rows]
        return {
            "count": len(rows),
            "slow": sum(1 for r in rows if r["slow"]),
            "errors": sum(1 for r in rows if r["error"]),
            "avg_ms": round(sum(durations) / len(durations), 2),
            "max_ms": max(durations),
        }

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


sql_log = SqlLog()


def make_cursor_class():
    """A psycopg cursor that records timing and text of every statement."""
    import psycopg

    class LoggingCursor(psycopg.Cursor):
        def execute(self, query, params=None, *args, **kwargs):  # noqa: ANN001
            started = time.perf_counter()
            error = ""
            try:
                return super().execute(query, params, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                error = type(exc).__name__
                raise
            finally:
                if config.LOG_SQL:
                    text = query if isinstance(query, str) else getattr(query, "as_string", lambda _: "")(self)
                    sql_log.add(str(text), (time.perf_counter() - started) * 1000, error,
                                self.rowcount if self.rowcount >= 0 else None)

    return LoggingCursor


# ---------------------------------------------------------------------------
# API request + audit log store
# ---------------------------------------------------------------------------
_REQUEST_DDL = (
    """
    CREATE TABLE IF NOT EXISTS api_request_logs (
        id          BIGSERIAL PRIMARY KEY,
        ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
        request_id  TEXT NOT NULL DEFAULT '',
        method      TEXT NOT NULL,
        path        TEXT NOT NULL,
        status      INTEGER NOT NULL,
        duration_ms REAL NOT NULL,
        user_id     TEXT,
        ip          TEXT NOT NULL DEFAULT ''
    )
    """,
    "ALTER TABLE api_request_logs ADD COLUMN IF NOT EXISTS input_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE api_request_logs ADD COLUMN IF NOT EXISTS output_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE api_request_logs ADD COLUMN IF NOT EXISTS llm_calls INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS api_request_logs_ts_idx ON api_request_logs (ts DESC)",
    """
    CREATE TABLE IF NOT EXISTS admin_audit_log (
        id          BIGSERIAL PRIMARY KEY,
        ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
        actor_id    TEXT NOT NULL,
        actor_email TEXT NOT NULL DEFAULT '',
        action      TEXT NOT NULL,
        target      TEXT NOT NULL DEFAULT '',
        detail      TEXT NOT NULL DEFAULT '',
        ip          TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS admin_audit_log_ts_idx ON admin_audit_log (ts DESC)",
)

_REQUEST_COLUMNS = "id, ts, request_id, method, path, status, duration_ms, user_id, ip, input_tokens, output_tokens, llm_calls"


def _req_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["ts"] = _iso(out["ts"])
    out["duration_ms"] = round(float(out["duration_ms"]), 1)
    return out


class MemoryLogStore:
    """Used without a database (tests, local experiments). Same interface."""

    def __init__(self, size: int = 5000) -> None:
        self._requests: collections.deque[dict[str, Any]] = collections.deque(maxlen=size)
        self._audit: collections.deque[dict[str, Any]] = collections.deque(maxlen=size)
        self._lock = threading.Lock()
        self._seq = 0

    def add_request(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            self._requests.append({"id": self._seq, **entry})

    def add_audit(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            self._audit.append({"id": self._seq, **entry})

    def query_requests(self, *, status: str = "", method: str = "", path: str = "", user_id: str = "",
                       min_ms: float = 0, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._requests)
        out = [r for r in reversed(rows) if _match_request(r, status, method, path, user_id, min_ms)]
        return out[offset: offset + limit]

    def query_audit(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._audit)
        return list(reversed(rows))[offset: offset + limit]

    def request_stats(self, hours: int = 24) -> dict[str, Any]:
        cutoff = _now().timestamp() - hours * 3600
        with self._lock:
            rows = [r for r in self._requests if datetime.fromisoformat(r["ts"]).timestamp() >= cutoff]
        return _stats_from_rows(rows, hours)

    def purge(self, days: int) -> int:
        return 0

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def _match_request(row: dict[str, Any], status: str, method: str, path: str, user_id: str, min_ms: float) -> bool:
    if status:
        code = int(row["status"])
        if status.endswith("xx"):
            if code // 100 != int(status[0]):
                return False
        elif str(code) != status:
            return False
    if method and row["method"] != method.upper():
        return False
    if path and path.lower() not in row["path"].lower():
        return False
    if user_id and row.get("user_id") != user_id:
        return False
    return not (min_ms and row["duration_ms"] < min_ms)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return round(ordered[index], 1)


def _stats_from_rows(rows: list[dict[str, Any]], hours: int) -> dict[str, Any]:
    durations = [float(r["duration_ms"]) for r in rows]
    buckets: dict[str, dict[str, int]] = {}
    for r in rows:
        hour = datetime.fromisoformat(r["ts"]).strftime("%Y-%m-%dT%H:00:00+00:00")
        bucket = buckets.setdefault(hour, {"requests": 0, "errors": 0})
        bucket["requests"] += 1
        bucket["errors"] += 1 if int(r["status"]) >= 500 else 0
    return {
        "hours": hours,
        "total": len(rows),
        "client_errors": sum(1 for r in rows if 400 <= int(r["status"]) < 500),
        "server_errors": sum(1 for r in rows if int(r["status"]) >= 500),
        "avg_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "p95_ms": _percentile(durations, 0.95),
        "input_tokens": sum(int(r.get("input_tokens", 0)) for r in rows),
        "output_tokens": sum(int(r.get("output_tokens", 0)) for r in rows),
        "llm_calls": sum(int(r.get("llm_calls", 0)) for r in rows),
        "series": [{"hour": k, **v} for k, v in sorted(buckets.items())],
    }


class PostgresLogStore:
    """Writes in batches from a background thread; reads straight from the table."""

    FLUSH_SECONDS = 2.0
    BATCH = 200

    def __init__(self, pool) -> None:
        self._pool = pool
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=10_000)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            for statement in _REQUEST_DDL:
                conn.execute(statement)
        self._thread = threading.Thread(target=self._run, name="request-log-writer", daemon=True)
        self._thread.start()

    # -- writes --------------------------------------------------------------
    def add_request(self, entry: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(entry)
        except queue.Full:  # never block or fail a request because logging is behind
            logger.warning("Request log queue full; dropping an entry.")

    def add_audit(self, entry: dict[str, Any]) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO admin_audit_log (actor_id, actor_email, action, target, detail, ip) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (entry["actor_id"], entry["actor_email"], entry["action"], entry["target"],
                 entry["detail"][:500], entry["ip"]),
            )

    def _run(self) -> None:
        while not self._stop.is_set():
            batch: list[dict[str, Any]] = []
            try:
                item = self._queue.get(timeout=self.FLUSH_SECONDS)
                if item is not None:
                    batch.append(item)
                while len(batch) < self.BATCH:
                    item = self._queue.get_nowait()
                    if item is not None:
                        batch.append(item)
            except queue.Empty:
                pass
            if batch:
                self._write(batch)

    def _write(self, batch: list[dict[str, Any]]) -> None:
        try:
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO api_request_logs (ts, request_id, method, path, status, duration_ms, user_id, ip, "
                    "input_tokens, output_tokens, llm_calls) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (e["ts"], e["request_id"], e["method"], e["path"], e["status"],
                         e["duration_ms"], e["user_id"], e["ip"],
                         e.get("input_tokens", 0), e.get("output_tokens", 0), e.get("llm_calls", 0))
                        for e in batch
                    ],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write %d request log(s): %s: %s", len(batch), type(exc).__name__, exc)

    def flush(self) -> None:
        batch = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                batch.append(item)
        if batch:
            self._write(batch)

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.flush()

    # -- reads ---------------------------------------------------------------
    def query_requests(self, *, status: str = "", method: str = "", path: str = "", user_id: str = "",
                       min_ms: float = 0, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        self.flush()
        where, params = ["TRUE"], []
        if status:
            if status.endswith("xx"):
                where.append("status / 100 = %s")
                params.append(int(status[0]))
            else:
                where.append("status = %s")
                params.append(int(status))
        if method:
            where.append("method = %s")
            params.append(method.upper())
        if path:
            where.append("position(lower(%s) in lower(path)) > 0")
            params.append(path)
        if user_id:
            where.append("user_id = %s")
            params.append(user_id)
        if min_ms:
            where.append("duration_ms >= %s")
            params.append(min_ms)
        with self._pool.connection() as conn:
            rows = conn.execute(
                f"SELECT {_REQUEST_COLUMNS} FROM api_request_logs WHERE {' AND '.join(where)} "
                "ORDER BY id DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            ).fetchall()
        return [_req_row(r) for r in rows]

    def query_audit(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, ts, actor_id, actor_email, action, target, detail, ip FROM admin_audit_log "
                "ORDER BY id DESC LIMIT %s OFFSET %s",
                (limit, offset),
            ).fetchall()
        return [{**r, "ts": _iso(r["ts"])} for r in rows]

    def request_stats(self, hours: int = 24) -> dict[str, Any]:
        self.flush()
        with self._pool.connection() as conn:
            head = conn.execute(
                "SELECT count(*) AS total, "
                "count(*) FILTER (WHERE status BETWEEN 400 AND 499) AS client_errors, "
                "count(*) FILTER (WHERE status >= 500) AS server_errors, "
                "coalesce(avg(duration_ms), 0) AS avg_ms, "
                "coalesce(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), 0) AS p95_ms, "
                "coalesce(sum(input_tokens), 0) AS input_tokens, coalesce(sum(output_tokens), 0) AS output_tokens, "
                "coalesce(sum(llm_calls), 0) AS llm_calls "
                "FROM api_request_logs WHERE ts > now() - make_interval(hours => %s)",
                (hours,),
            ).fetchone()
            series = conn.execute(
                "SELECT date_trunc('hour', ts) AS hour, count(*) AS requests, "
                "count(*) FILTER (WHERE status >= 500) AS errors "
                "FROM api_request_logs WHERE ts > now() - make_interval(hours => %s) "
                "GROUP BY 1 ORDER BY 1",
                (hours,),
            ).fetchall()
        return {
            "hours": hours,
            "total": head["total"],
            "client_errors": head["client_errors"],
            "server_errors": head["server_errors"],
            "avg_ms": round(float(head["avg_ms"]), 1),
            "p95_ms": round(float(head["p95_ms"]), 1),
            "input_tokens": int(head["input_tokens"]),
            "output_tokens": int(head["output_tokens"]),
            "llm_calls": int(head["llm_calls"]),
            "series": [{"hour": _iso(s["hour"]), "requests": s["requests"], "errors": s["errors"]} for s in series],
        }

    def purge(self, days: int) -> int:
        with self._pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM api_request_logs WHERE ts < now() - make_interval(days => %s)", (days,)
            )
            return cur.rowcount


# ---------------------------------------------------------------------------
# Module-level access
# ---------------------------------------------------------------------------
_store: MemoryLogStore | PostgresLogStore = MemoryLogStore()
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)


def use_store(store) -> None:
    global _store
    _store = store


def get_store():
    return _store


def reset_memory() -> None:
    """Tests: start from an empty in-memory store and SQL ring."""
    global _store
    _store = MemoryLogStore()
    sql_log.clear()


def record_request(method: str, path: str, status: int, duration_ms: float, user_id: str | None, ip: str,
                   request_id: str | None = None, usage: dict[str, int] | None = None) -> None:
    if path in _SKIP_PATHS or path.startswith(_SKIP_PATHS[-1]):
        return
    try:
        _store.add_request(
            {
                "ts": _now().isoformat(),
                "request_id": request_id or config.request_id_var.get(),
                "method": method,
                "path": path[:300],
                "status": status,
                "duration_ms": round(duration_ms, 1),
                "user_id": user_id,
                "ip": ip,
                "input_tokens": (usage or {}).get("input_tokens", 0),
                "output_tokens": (usage or {}).get("output_tokens", 0),
                "llm_calls": (usage or {}).get("llm_calls", 0),
            }
        )
    except Exception as exc:  # noqa: BLE001 - logging must never break a request
        logger.warning("Could not record request log: %s: %s", type(exc).__name__, exc)


def audit(actor: dict[str, Any], action: str, target: str = "", detail: str = "", ip: str = "") -> None:
    entry = {
        "ts": _now().isoformat(),
        "actor_id": actor["id"],
        "actor_email": actor["email"],
        "action": action,
        "target": target,
        "detail": detail,
        "ip": ip,
    }
    logging.getLogger("tripmate.audit").info("%s by %s target=%s %s", action, actor["email"], target, detail)
    try:
        _store.add_audit(entry)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not record audit entry: %s: %s", type(exc).__name__, exc)
