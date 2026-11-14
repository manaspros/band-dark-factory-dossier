"""The browser side: one static HTML shell for every screen, and its static assets.

The shell carries no dossier data and needs no token: a top-level browser navigation cannot
send a bearer header. The single-page app in ``app/ui/`` then reads everything through the
authenticated JSON API (plan E8, E19). ``GET /dossiers/{domain}`` is shared with the API:
it returns the shell only when the request accepts ``text/html``.
"""
from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, Response

from app.errors import not_found

UI_DIR = Path(__file__).parent / "ui"
SHELL = UI_DIR / "index.html"
_CONTENT_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                  ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml"}
_NO_CACHE = {"Cache-Control": "no-cache"}


def wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "").lower()


async def shell(request: Request) -> Response:
    return FileResponse(SHELL, media_type="text/html; charset=utf-8", headers=_NO_CACHE)


async def static(request: Request) -> Response:
    """A file under ``app/ui``; anything outside it, or unknown, is 404."""
    relative = request.path_params["path"]
    target = (UI_DIR / relative).resolve()
    if UI_DIR.resolve() not in target.parents or not target.is_file() \
            or target.suffix not in _CONTENT_TYPES:
        raise not_found()
    return FileResponse(target, media_type=_CONTENT_TYPES[target.suffix], headers=_NO_CACHE)
