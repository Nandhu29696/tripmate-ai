"""Thread registry: who owns which LangGraph thread (F-02), plus the
metadata needed to list, restore and expire trips (F-11, F-18).

LangGraph's own checkpoint tables are untouched. This adds one small table,
``tripmate_threads``, created with CREATE TABLE IF NOT EXISTS.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol


class ThreadRegistry(Protocol):
    def create(self, thread_id: str, owner_id: str, title: str) -> None: ...
    def owner_of(self, thread_id: str) -> str | None: ...
    def set_status(self, thread_id: str, status: str) -> None: ...
    def list_for_owner(self, owner_id: str, limit: int = 20) -> list[dict[str, Any]]: ...
    def delete(self, thread_id: str) -> None: ...
    def expired(self, days: int) -> list[str]: ...
    def list_all(self, status: str = "", owner_id: str = "", limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]: ...
    def get(self, thread_id: str) -> dict[str, Any] | None: ...
    def counts(self) -> dict[str, Any]: ...
    def add_usage(self, thread_id: str, input_tokens: int, output_tokens: int, llm_calls: int) -> None: ...


# One statement per entry: the pool uses prepare_threshold=0 (extended
# protocol), which rejects multi-statement strings.
_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS tripmate_threads (
        thread_id  TEXT PRIMARY KEY,
        owner_id   TEXT NOT NULL,
        title      TEXT NOT NULL DEFAULT '',
        status     TEXT NOT NULL DEFAULT 'running',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE tripmate_threads ADD COLUMN IF NOT EXISTS input_tokens BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE tripmate_threads ADD COLUMN IF NOT EXISTS output_tokens BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE tripmate_threads ADD COLUMN IF NOT EXISTS llm_calls INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS tripmate_threads_owner_idx "
    "ON tripmate_threads (owner_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS tripmate_threads_updated_idx "
    "ON tripmate_threads (updated_at)",
)


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class PostgresThreadRegistry:
    def __init__(self, pool) -> None:
        self._pool = pool

    def ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)

    def create(self, thread_id: str, owner_id: str, title: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO tripmate_threads (thread_id, owner_id, title) VALUES (%s, %s, %s)",
                (thread_id, owner_id, title[:120]),
            )

    def owner_of(self, thread_id: str) -> str | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT owner_id FROM tripmate_threads WHERE thread_id = %s", (thread_id,)
            ).fetchone()
        return row["owner_id"] if row else None

    def set_status(self, thread_id: str, status: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE tripmate_threads SET status = %s, updated_at = now() WHERE thread_id = %s",
                (status, thread_id),
            )

    def list_for_owner(self, owner_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT thread_id, title, status, created_at, updated_at "
                "FROM tripmate_threads WHERE owner_id = %s "
                "ORDER BY updated_at DESC LIMIT %s",
                (owner_id, limit),
            ).fetchall()
        return [
            {**row, "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])}
            for row in rows
        ]

    def delete(self, thread_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM tripmate_threads WHERE thread_id = %s", (thread_id,))

    def expired(self, days: int) -> list[str]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT thread_id FROM tripmate_threads "
                "WHERE updated_at < now() - make_interval(days => %s)",
                (days,),
            ).fetchall()
        return [row["thread_id"] for row in rows]

    def list_all(self, status="", owner_id="", limit=50, offset=0):
        where, params = ["TRUE"], []
        if status:
            where.append("status = %s")
            params.append(status)
        if owner_id:
            where.append("owner_id = %s")
            params.append(owner_id)
        clause = " AND ".join(where)
        with self._pool.connection() as conn:
            total = conn.execute(f"SELECT count(*) AS n FROM tripmate_threads WHERE {clause}", tuple(params)).fetchone()["n"]
            rows = conn.execute(
                "SELECT thread_id, owner_id, title, status, created_at, updated_at, "
                "input_tokens, output_tokens, llm_calls FROM tripmate_threads "
                f"WHERE {clause} ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            ).fetchall()
        return [{**r, "created_at": _iso(r["created_at"]), "updated_at": _iso(r["updated_at"])} for r in rows], total

    def add_usage(self, thread_id, input_tokens, output_tokens, llm_calls):
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE tripmate_threads SET input_tokens = input_tokens + %s, output_tokens = output_tokens + %s, "
                "llm_calls = llm_calls + %s WHERE thread_id = %s",
                (input_tokens, output_tokens, llm_calls, thread_id),
            )

    def get(self, thread_id):
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT thread_id, owner_id, title, status, created_at, updated_at, "
                "input_tokens, output_tokens, llm_calls FROM tripmate_threads WHERE thread_id = %s", (thread_id,)
            ).fetchone()
        return {**row, "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])} if row else None

    def counts(self):
        with self._pool.connection() as conn:
            by_status = conn.execute("SELECT status, count(*) AS n FROM tripmate_threads GROUP BY status").fetchall()
            recent = conn.execute(
                "SELECT count(*) AS n FROM tripmate_threads WHERE created_at > now() - interval '24 hours'"
            ).fetchone()["n"]
            per_owner = conn.execute(
                "SELECT owner_id, count(*) AS n, sum(input_tokens + output_tokens) AS tokens "
                "FROM tripmate_threads GROUP BY owner_id"
            ).fetchall()
        return {
            "tokens_per_owner": {r["owner_id"]: int(r["tokens"] or 0) for r in per_owner},
            "by_status": {r["status"]: int(r["n"]) for r in by_status},
            "last_24h": int(recent),
            "per_owner": {r["owner_id"]: int(r["n"]) for r in per_owner},
        }


class InMemoryThreadRegistry:
    """Test double with the same behaviour as the Postgres registry."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, thread_id: str, owner_id: str, title: str) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._rows[thread_id] = {
                "thread_id": thread_id, "owner_id": owner_id, "title": title[:120],
                "status": "running", "created_at": now, "updated_at": now,
                "input_tokens": 0, "output_tokens": 0, "llm_calls": 0,
            }

    def owner_of(self, thread_id: str) -> str | None:
        row = self._rows.get(thread_id)
        return row["owner_id"] if row else None

    def set_status(self, thread_id: str, status: str) -> None:
        with self._lock:
            if thread_id in self._rows:
                self._rows[thread_id].update(status=status, updated_at=datetime.now(UTC))

    def list_for_owner(self, owner_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = [r for r in self._rows.values() if r["owner_id"] == owner_id]
        rows.sort(key=lambda r: r["updated_at"], reverse=True)
        return [
            {"thread_id": r["thread_id"], "title": r["title"], "status": r["status"],
             "created_at": _iso(r["created_at"]), "updated_at": _iso(r["updated_at"])}
            for r in rows[:limit]
        ]

    def delete(self, thread_id: str) -> None:
        with self._lock:
            self._rows.pop(thread_id, None)

    def expired(self, days: int) -> list[str]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return [tid for tid, r in self._rows.items() if r["updated_at"] < cutoff]

    def list_all(self, status="", owner_id="", limit=50, offset=0):
        rows = [r for r in self._rows.values()
                if (not status or r["status"] == status) and (not owner_id or r["owner_id"] == owner_id)]
        rows.sort(key=lambda r: r["updated_at"], reverse=True)
        out = [self.get(r["thread_id"]) for r in rows[offset: offset + limit]]
        return out, len(rows)

    def get(self, thread_id):
        r = self._rows.get(thread_id)
        if not r:
            return None
        return {"thread_id": r["thread_id"], "owner_id": r["owner_id"], "title": r["title"], "status": r["status"],
                "created_at": _iso(r["created_at"]), "updated_at": _iso(r["updated_at"]),
                "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"], "llm_calls": r["llm_calls"]}

    def add_usage(self, thread_id, input_tokens, output_tokens, llm_calls):
        with self._lock:
            row = self._rows.get(thread_id)
            if row:
                row["input_tokens"] += input_tokens
                row["output_tokens"] += output_tokens
                row["llm_calls"] += llm_calls

    def counts(self):
        by_status: dict[str, int] = {}
        per_owner: dict[str, int] = {}
        tokens: dict[str, int] = {}
        recent = 0
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        for r in self._rows.values():
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            per_owner[r["owner_id"]] = per_owner.get(r["owner_id"], 0) + 1
            tokens[r["owner_id"]] = tokens.get(r["owner_id"], 0) + r["input_tokens"] + r["output_tokens"]
            recent += 1 if r["created_at"] > cutoff else 0
        return {"by_status": by_status, "last_24h": recent, "per_owner": per_owner, "tokens_per_owner": tokens}
