"""MCP tool access for the travel agents.

Design (F-14): all MCP traffic runs on ONE dedicated asyncio event loop in a
background thread. Each MCP server gets a long-lived session owned by its own
task, so stdio subprocesses are started once and reused instead of being
spawned for every tool call. Agent nodes stay synchronous and call the
blocking helpers below, which are safe to use from many threads at once
(parallel agents, FastAPI worker threads).

Security (F-04, F-05, F-06): MCP subprocesses receive only an allowlisted
environment plus their own key; the AviationStack server is version-pinned;
the Tavily key travels in a header, not in the URL.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

WEATHER_SERVER_PATH = config.BASE_DIR / "custom_weather_mcp_server.py"

# Variables a child process legitimately needs to start. Everything else
# (GROQ_API_KEY, DATABASE_URL, SESSION_SECRET, other providers' keys) is NOT
# forwarded to third-party MCP servers.
_ENV_ALLOWLIST = {
    "PATH", "PATHEXT", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ", "VIRTUAL_ENV", "PYTHONPATH",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
    "no_proxy",
}
_ENV_ALLOW_PREFIXES = ("UV_", "XDG_")


def _subprocess_env(**secrets: str | None) -> dict[str, str]:
    """Allowlisted base environment plus only the keys this server needs."""

    env = {
        key: value
        for key, value in os.environ.items()
        if key in _ENV_ALLOWLIST or key.startswith(_ENV_ALLOW_PREFIXES)
    }
    for key, value in secrets.items():
        if value:
            env[key] = value
    return env


def _aviation_command() -> tuple[str, list[str]]:
    """Pinned AviationStack server: installed binary first, else pinned uvx."""

    installed = shutil.which("aviationstack-mcp")
    if installed:
        return installed, []

    uvx = shutil.which("uvx")
    if not uvx:
        scripts = Path(sys.executable).parent
        for name in ("uvx.exe", "uvx"):
            if (scripts / name).is_file():
                uvx = str(scripts / name)
                break

    if not uvx:
        raise RuntimeError(
            "uvx was not found. Install uv, or install the pinned "
            "aviationstack-mcp tool, and try again."
        )

    return uvx, [f"aviationstack-mcp@{config.AVIATIONSTACK_MCP_VERSION}"]


def _server_configs() -> dict[str, dict[str, Any]]:
    servers: dict[str, dict[str, Any]] = {}

    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        servers["tavily"] = {
            "transport": "streamable_http",
            "url": "https://mcp.tavily.com/mcp/",
            "headers": {"Authorization": f"Bearer {tavily_key}"},
        }

    aviation_key = os.getenv("AVIATION_STACK_API_KEY") or os.getenv(
        "AVIATIONSTACK_API_KEY"
    )
    if aviation_key:
        command, args = _aviation_command()
        servers["aviationstack"] = {
            "transport": "stdio",
            "command": command,
            "args": args,
            "env": _subprocess_env(AVIATION_STACK_API_KEY=aviation_key),
        }

    weather_key = os.getenv("OPENWEATHER_API_KEY")
    if weather_key and WEATHER_SERVER_PATH.is_file():
        servers["weather"] = {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(WEATHER_SERVER_PATH)],
            "env": _subprocess_env(OPENWEATHER_API_KEY=weather_key),
        }

    return servers


_REQUIRED_KEYS = {
    "tavily": "TAVILY_API_KEY",
    "aviationstack": "AVIATION_STACK_API_KEY",
    "weather": "OPENWEATHER_API_KEY",
}

# The first call to an uvx-launched server may download it.
_SERVER_TIMEOUTS = {"aviationstack": 120}


class ToolError(RuntimeError):
    """An MCP tool answered, but reported a failure (plan limits, bad input)."""


def _as_text(result: Any) -> str:
    """Flatten MCP content blocks ([{'type': 'text', 'text': ...}]) to plain text."""
    if isinstance(result, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in result
        ]
        return chr(10).join(part for part in parts if part)
    return result if isinstance(result, str) else str(result)


def _raise_if_failed(text: str, server: str, tool_name: str) -> None:
    """Some servers return {"ok": false, "error": ...} instead of raising."""
    stripped = text.lstrip()
    # Cheap pre-check so large successful payloads are not parsed twice.
    if not stripped.startswith("{") or "false" not in stripped[:120].lower():
        return
    try:
        payload = json.loads(stripped)
    except ValueError:
        return
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise ToolError(f"{server}.{tool_name}: {payload.get('error', 'tool reported a failure')}")


class MCPRuntime:
    """Persistent MCP sessions on a private event loop."""

    def __init__(self) -> None:
        self._start_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client = None
        # loop-confined state
        self._entries: dict[str, dict[str, Any]] = {}
        self._open_locks: dict[str, asyncio.Lock] = {}

    # ---- loop management -------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=loop.run_forever, name="mcp-loop", daemon=True
                )
                thread.start()
                self._loop, self._thread = loop, thread
            return self._loop

    def _get_client(self):
        if self._client is None:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            self._client = MultiServerMCPClient(_server_configs())
        return self._client

    # ---- loop-side coroutines --------------------------------------------
    async def _session_worker(self, name: str, ready: asyncio.Future, stop: asyncio.Event):
        from langchain_mcp_adapters.tools import load_mcp_tools

        try:
            async with self._get_client().session(name) as session:
                tools = await load_mcp_tools(session, server_name=name)
                ready.set_result({tool.name: tool for tool in tools})
                await stop.wait()
        except BaseException as exc:  # noqa: BLE001 - must also catch cancellation
            if not ready.done():
                ready.set_exception(exc)
            else:
                logger.warning("MCP session '%s' ended: %s: %s", name, type(exc).__name__, exc)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise

    async def _tools(self, name: str) -> dict[str, Any]:
        lock = self._open_locks.setdefault(name, asyncio.Lock())
        async with lock:
            entry = self._entries.get(name)
            if entry and not entry["task"].done():
                return entry["tools"]

            loop = asyncio.get_running_loop()
            ready: asyncio.Future = loop.create_future()
            stop = asyncio.Event()
            task = loop.create_task(self._session_worker(name, ready, stop))
            try:
                tools = await ready
            except BaseException:
                self._entries.pop(name, None)
                raise
            self._entries[name] = {"tools": tools, "stop": stop, "task": task}
            logger.info("MCP session '%s' started with tools: %s", name, ", ".join(sorted(tools)))
            return tools

    async def _drop(self, name: str) -> None:
        entry = self._entries.pop(name, None)
        if entry:
            entry["stop"].set()
            try:
                await asyncio.wait_for(entry["task"], timeout=5)
            except BaseException:  # noqa: BLE001
                entry["task"].cancel()

    async def _call(self, server: str, tool_name: str, args: dict[str, Any], timeout: int):
        last_error: Exception | None = None

        for attempt in (1, 2):
            tools = await self._tools(server)
            tool = tools.get(tool_name)
            if tool is None:
                available = ", ".join(sorted(tools)) or "none"
                raise RuntimeError(
                    f"MCP tool '{tool_name}' was not found on server "
                    f"'{server}'. Available tools: {available}"
                )
            try:
                return await asyncio.wait_for(tool.ainvoke(args), timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "MCP call %s.%s failed (attempt %d): %s: %s",
                    server, tool_name, attempt, type(exc).__name__, exc,
                )
                # The session may be dead (server restarted, idle timeout):
                # drop it so the next attempt opens a fresh one.
                await self._drop(server)

        assert last_error is not None
        raise last_error

    async def _shutdown(self) -> None:
        for name in list(self._entries):
            await self._drop(name)

    # ---- blocking API used by graph nodes --------------------------------
    def call(self, server: str, tool_name: str, args: dict[str, Any] | None = None):
        key_name = _REQUIRED_KEYS[server]
        if server == "aviationstack":
            if not (os.getenv("AVIATION_STACK_API_KEY") or os.getenv("AVIATIONSTACK_API_KEY")):
                raise RuntimeError("AVIATION_STACK_API_KEY is missing. Add it to the .env file.")
        else:
            config.require_env(key_name)

        timeout = _SERVER_TIMEOUTS.get(server, config.MCP_CALL_TIMEOUT_SECONDS)
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._call(server, tool_name, args or {}, timeout), loop
        )
        # Session start-up (e.g. first uvx download) is bounded by the same
        # timeout; add slack for it plus one retry.
        text = _as_text(future.result(timeout=timeout * 2 + 15))
        _raise_if_failed(text, server, tool_name)
        return text

    def check_servers(self) -> dict[str, str]:
        """Diagnostic: report which MCP servers start and their tools."""
        loop = self._ensure_loop()
        report: dict[str, str] = {}
        for name in _REQUIRED_KEYS:
            try:
                future = asyncio.run_coroutine_threadsafe(self._tools(name), loop)
                tools = future.result(timeout=_SERVER_TIMEOUTS.get(name, 45) + 15)
                report[name] = "OK: " + ", ".join(sorted(tools))
            except ValueError as exc:
                if "find a server" in str(exc):
                    report[name] = f"not configured (set {_REQUIRED_KEYS[name]})"
                else:
                    report[name] = f"FAILED: {type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001
                report[name] = f"FAILED: {type(exc).__name__}: {exc}"
        return report

    def close(self) -> None:
        with self._start_lock:
            loop, thread = self._loop, self._thread
            self._loop = self._thread = None
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), loop).result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP shutdown problem: %s", exc)
        loop.call_soon_threadsafe(loop.stop)
        if thread:
            thread.join(timeout=5)


runtime = MCPRuntime()


# ---------------------------------------------------------------------------
# Convenience wrappers (blocking)
# ---------------------------------------------------------------------------
def tavily_search(query: str):
    return runtime.call("tavily", "tavily_search", {"query": query})


def aviation_call(tool_name: str, tool_args: dict[str, Any] | None = None):
    return runtime.call("aviationstack", tool_name, tool_args or {})


def weather_current(city: str):
    return runtime.call("weather", "get_current_weather", {"city": city})


def weather_forecast(city: str, days: int = 5):
    return runtime.call("weather", "get_forecast", {"city": city, "days": days})


def shutdown() -> None:
    runtime.close()


if __name__ == "__main__":
    # Manual diagnostic: python mcp_client.py   (contacts the real services)
    config.configure_logging()
    for server, status in runtime.check_servers().items():
        print(f"{server}: {status}")
    runtime.close()
