"""FastAPI application factory.

``create_app`` takes every collaborator explicitly. ``build_app`` is the production
composition root: it reads settings and picks the real database, fetcher, and auth
provider. Tests call ``create_app`` with a temporary SQLite database, a fake fetcher,
and a local or fake-backed auth provider.
"""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from shelfmark.auth import AuthProvider, LocalAuth
from shelfmark.auth.auth0 import Auth0Auth, Auth0Config, normalize_domain
from shelfmark.clients.fetcher import Fetcher, PublicWebFetcher
from shelfmark.config import Settings
from shelfmark.db import Database, migrate
from shelfmark.logging import configure_logging
from shelfmark.routers import health, library
from shelfmark.services.library import LibraryError, utc_now
from shelfmark.services.refresher import run_periodically
from shelfmark.web.serve import mount_frontend

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "frame-src https://www.youtube-nocookie.com; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'self' https://ampcode.com; form-action 'self'"
)


def create_app(
    settings: Settings,
    *,
    database: Database,
    fetcher: Fetcher,
    auth: AuthProvider,
    clock=utc_now,
    run_migrations: bool = True,
    background_refresh: bool = True,
    serve_frontend: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings)
        if run_migrations:
            await asyncio.to_thread(migrate, database.url)
        task = None
        if background_refresh and settings.refresh_minutes > 0:
            task = asyncio.create_task(
                run_periodically(database, fetcher, clock, settings.refresh_minutes)
            )
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await database.dispose()

    app = FastAPI(title="shelfmark", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.fetcher = fetcher
    app.state.auth = auth
    app.state.clock = clock

    csp = f"{CSP} {auth.external_origin}" if auth.external_origin else CSP

    app.add_exception_handler(library.ApiError, library.api_error_handler)
    app.add_exception_handler(LibraryError, library.api_error_handler)

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if not request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response

    app.include_router(health.router)
    app.include_router(library.router)
    provider_routes = auth.router()
    if provider_routes is not None:
        app.include_router(provider_routes)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE"])
    async def api_not_found(rest: str) -> JSONResponse:
        return JSONResponse({"detail": "Not found."}, status_code=404)

    if serve_frontend:
        mount_frontend(app)
    return app


def select_auth(settings: Settings) -> AuthProvider:
    if settings.auth_provider == "local":
        if settings.env != "development":
            raise RuntimeError(
                "SHELFMARK_AUTH=local is only allowed with SHELFMARK_ENV=development"
            )
        return LocalAuth()
    redirect = settings.auth0_redirect_uri.strip()
    if not redirect and settings.deployment_url:
        redirect = settings.deployment_url.rstrip("/") + "/auth/callback"
    return Auth0Auth(
        Auth0Config(
            domain=normalize_domain(settings.auth0_domain),
            client_id=settings.auth0_client_id.strip(),
            client_secret=settings.auth0_client_secret.strip(),
            redirect_uri=redirect,
            session_secret=settings.session_secret.strip(),
        )
    )


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    return create_app(
        settings,
        database=Database(settings.database_url),
        fetcher=PublicWebFetcher(),
        auth=select_auth(settings),
    )
