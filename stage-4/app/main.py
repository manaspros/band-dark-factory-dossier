"""The Dossier HTTP service: routes, error envelope and startup."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from dataclasses import dataclass, field

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.routing import Route

from app import auth, batches, control, dossiers, ui_routes
from app.build import Builds
from app.clock import Clock
from app.commit import recover_interrupted
from app.db import Database
from app.errors import ApiError
from app.http import error_response, json_response
from app.store import Store
from app.web import WebClient

log = logging.getLogger("dossier")


DEFAULT_DATA_DIR = "/srv/data"


@dataclass
class Services:
    """Everything a handler needs: the state, the clock and the build runner. The state and
    the clock start as the database last held them (stage-3 "Restarts")."""
    store: Store = field(default_factory=Store)
    clock: Clock = field(default_factory=Clock)
    builds: Builds = field(init=False)

    def __post_init__(self) -> None:
        self.clock.restore(self.store.db.clock())
        recover_interrupted(self.store)   # before anything is served (stage-4 Restarts)
        self.builds = Builds(self.store)


def _endpoint(services: Services, handler):
    async def endpoint(request: Request):
        return await handler(services, request)
    return endpoint


def _dossier_or_shell(services: Services):
    """`GET /dossiers/{domain}` is the dossier screen for browsers, the API otherwise."""
    async def endpoint(request: Request):
        if ui_routes.wants_html(request):
            return await ui_routes.shell(request)
        return await dossiers.read(services, request)
    return endpoint


def _auth_endpoint(services: Services, handler):
    async def endpoint(request: Request):
        return await handler(services.store, request)
    return endpoint


async def _api_error(request: Request, exc: ApiError):
    return error_response(exc)


async def _http_error(request: Request, exc: HTTPException):
    if exc.status_code == 405:
        return error_response(ApiError(405, "method_not_allowed", "method not allowed"))
    if exc.status_code == 404:
        return error_response(ApiError(404, "not_found", "no such resource"))
    return error_response(ApiError(exc.status_code, "error", str(exc.detail)))


async def _unexpected(request: Request, exc: Exception):
    log.exception("unhandled error")
    return json_response(500, {"error": {"code": "internal_error",
                                         "message": "unexpected error"}})


def create_app(services: Services | None = None, web_factory=WebClient) -> Starlette:
    services = services or Services()
    services.builds.web_factory = web_factory
    s = services
    routes = [
        Route("/health", _endpoint(s, control.health), methods=["GET"]),
        Route("/_test/reset", _endpoint(s, control.reset), methods=["POST"]),
        Route("/_test/clock", _endpoint(s, control.set_clock), methods=["POST"]),
        Route("/_test/export", _endpoint(s, control.export), methods=["GET"]),
        Route("/_test/import", _endpoint(s, control.import_), methods=["POST"]),
        Route("/auth/signup", _auth_endpoint(s, auth.signup), methods=["POST"]),
        Route("/auth/login", _auth_endpoint(s, auth.login), methods=["POST"]),
        Route("/dossiers", _endpoint(s, dossiers.create), methods=["POST"]),
        Route("/dossiers", _endpoint(s, dossiers.list_), methods=["GET"]),
        Route("/dossiers/{domain:path}/refresh", _endpoint(s, dossiers.refresh), methods=["POST"]),
        Route("/dossiers/{domain:path}/history", _endpoint(s, dossiers.history), methods=["GET"]),
        Route("/dossiers/{domain:path}/values", _endpoint(s, dossiers.values), methods=["GET"]),
        Route("/changes", _endpoint(s, dossiers.changes), methods=["GET"]),
        Route("/batches", _endpoint(s, batches.create), methods=["POST"]),
        Route("/batches/{batch_id}", _endpoint(s, batches.read), methods=["GET"]),
        # Browser screens (static shell); the evidence route must precede the shared one.
        Route("/", ui_routes.shell, methods=["GET"]),
        Route("/signup", ui_routes.shell, methods=["GET"]),
        Route("/login", ui_routes.shell, methods=["GET"]),
        Route("/contested", ui_routes.shell, methods=["GET"]),
        Route("/dossiers/{domain:path}/evidence", ui_routes.shell, methods=["GET"]),
        Route("/dossiers/{domain:path}", _dossier_or_shell(s), methods=["GET"]),
        Route("/static/{path:path}", ui_routes.static, methods=["GET"]),
    ]
    app = Starlette(routes=routes, exception_handlers={
        ApiError: _api_error, HTTPException: _http_error, Exception: _unexpected})
    app.state.services = services
    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT") or "8080")
    data_dir = Path(os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    services = Services(store=Store(Database(str(data_dir / "dossier.db"))))
    uvicorn.run(create_app(services), host="0.0.0.0", port=port, workers=1, log_level="warning",
                access_log=False)


if __name__ == "__main__":
    main()
