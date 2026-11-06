from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles


class ImmutableStaticFiles(StaticFiles):
    """Vite names assets by content hash, so a URL never changes meaning (INK-100)."""

    def file_response(self, *args, **kwargs):
        r = super().file_response(*args, **kwargs)
        r.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return r


def mount_web(app: FastAPI, dist: Path | None) -> bool:
    """Serve the built web app from the API. Only three fixed paths exist, so nothing else
    in or beside dist (web/dev.log, source maps outside assets/) can be reached; StaticFiles
    refuses ../ out of assets/. Call after every router and API route."""
    if dist is None or not (dist / "index.html").is_file() or not (dist / "assets").is_dir():
        return False
    app.mount("/assets", ImmutableStaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    if (dist / "favicon.svg").is_file():

        @app.get("/favicon.svg", include_in_schema=False)
        def favicon() -> FileResponse:
            return FileResponse(dist / "favicon.svg")

    return True
