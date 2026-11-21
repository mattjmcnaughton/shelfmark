"""Static file serving for the built frontend."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"


def mount_frontend(app: FastAPI, dist: Path = FRONTEND_DIST) -> None:
    """Serve ``dist/`` when it exists; in development Vite serves the frontend."""
    if not dist.is_dir():
        return
    index = dist / "index.html"

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"x-amp-review-widget": "off"})
