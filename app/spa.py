"""Serve the built frontend from the same origin as the API."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

SPA_PREFIXES = ("api/", "api", "docs", "redoc", "openapi.json", "health", "static", "auth/")
INDEX_NAME = "index.html"


def dist_root() -> Path | None:
    explicit = os.environ.get("FRONTEND_DIST", "").strip()
    if explicit:
        path = Path(explicit)
        return path if (path / INDEX_NAME).is_file() else None
    for candidate in (Path("frontend/out"), Path("frontend/dist"), Path("static")):
        if (candidate / INDEX_NAME).is_file():
            return candidate
    return None


def _is_reserved(full_path: str) -> bool:
    path = full_path.lstrip("/")
    if path in {"docs", "redoc", "openapi.json", "health", "static"}:
        return True
    return path.startswith("api/") or path.startswith("auth/") or path.startswith("static/")


def _safe_file(root: Path, relative: str) -> Path | None:
    if not relative or relative.endswith("/"):
        relative = relative.rstrip("/")
    candidate = (root / relative).resolve() if relative else root.resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        return None
    if candidate.is_file():
        return candidate
    for alt in (
        root / f"{relative}.html",
        root / relative / INDEX_NAME,
    ):
        resolved = alt.resolve()
        if root_resolved == resolved or root_resolved in resolved.parents:
            if resolved.is_file():
                return resolved
    return None


def register_spa(app: FastAPI) -> None:
    root = dist_root()
    next_dir = (root / "_next") if root else None
    if next_dir and next_dir.is_dir():
        app.mount("/_next", StaticFiles(directory=str(next_dir)), name="next-static")

    @app.get("/", include_in_schema=False)
    def spa_index():
        return _html_or_503()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if _is_reserved(full_path):
            raise HTTPException(status_code=404, detail="Not Found")
        return _file_or_index(full_path)


def _html_or_503():
    root = dist_root()
    if root is None:
        raise HTTPException(status_code=503, detail="frontend not built")
    return FileResponse(root / INDEX_NAME, media_type="text/html", headers={"Cache-Control": "no-cache"})


def _file_or_index(full_path: str):
    root = dist_root()
    if root is None:
        raise HTTPException(status_code=503, detail="frontend not built")
    found = _safe_file(root, full_path)
    if found is not None:
        headers = {"Cache-Control": "no-cache"} if found.name == INDEX_NAME else None
        return FileResponse(found, headers=headers)
    return FileResponse(root / INDEX_NAME, media_type="text/html", headers={"Cache-Control": "no-cache"})
