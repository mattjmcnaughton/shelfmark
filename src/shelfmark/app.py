"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from shelfmark.logging import configure_logging
from shelfmark.routers import health
from shelfmark.web.serve import mount_frontend


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    configure_logging()
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="shelfmark",
        description="A keyboard-first personal reading desk",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)

    # Mount frontend static files (only serves if dist/ exists)
    mount_frontend(app)

    return app


app = create_app()
