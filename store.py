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
