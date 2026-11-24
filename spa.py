"""Serve the built React app (frontend/dist) from FastAPI.

- ``/assets/*``: content-hashed build files (cached for a year, set in app middleware).
- Any other path that is not an API/auth route returns ``index.html`` so client-side
  routes (``/login``, ``/trips/<id>``, ``/account`` ...) work on a hard refresh.
- Unknown ``/api/*`` and ``/auth/*`` paths stay real JSON 404s; they are never
  answered with the HTML shell.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("tripmate.spa")

_MISSING = (
    "<!doctype html><title>TripMate AI</title><body style='font-family:sans-serif;max-width:40rem;margin:4rem auto'>"
    "<h1>TripMate AI</h1><p>The web app has not been built yet. "
    "Run <code>npm ci &amp;&amp; npm run build</code> in the <code>frontend</code> folder "
    "(or use the Docker image, which builds it).</p></body>"
)


def mount_spa(app: FastAPI, dist: Path) -> None:
    dist = dist.resolve()
    index = dist / "index.html"

    if not index.is_file():
        logger.warning("Frontend build not found at %s; serving a placeholder page.", dist)

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        first = path.split("/", 1)[0]
        if first in {"api", "auth", "assets"}:
            return JSONResponse(status_code=404, content={"success": False, "error": "Not found."})

        if path:
            candidate = (dist / path).resolve()
            # Root files such as favicon.svg; never anything outside the build folder.
            if candidate.is_file() and dist in candidate.parents:
                return FileResponse(candidate)

        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(_MISSING, status_code=503)
