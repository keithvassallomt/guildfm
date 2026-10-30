"""Serves the built React front end, sending unknown paths to index.html so client routes work."""

import ipaddress
import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Browsers expect the app manifest as this; Python doesn't know the extension.
mimetypes.add_type("application/manifest+json", ".webmanifest")

# Left alone by the move to the public address: the speakers fetch media, open pages call the
# API, and Spotify's sign-in comes back to /auth through the SSH tunnel.
UNMOVED = ("/api", "/media", "/auth")


def _by_name(host: str | None) -> bool:
    """Whether a request was addressed to a name, like guildfm.local, rather than an IP address
    as the speakers use."""
    if not host or host == "localhost":
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return False


def send_browsers_to(app: FastAPI, public_url: str) -> None:
    """Send browsers that open a page over plain HTTP by name, such as http://guildfm.local, to
    `public_url` instead, where GuildFM is served over HTTPS. Requests by IP address, and API,
    media and sign-in requests, carry on as they are."""
    public = public_url.rstrip("/")

    @app.middleware("http")
    async def to_public(request: Request, call_next):
        url = request.url
        moved = (
            request.method in ("GET", "HEAD")
            and url.scheme == "http"
            and _by_name(url.hostname)
            and not any(url.path == p or url.path.startswith(f"{p}/") for p in UNMOVED)
        )
        if not moved:
            return await call_next(request)
        query = f"?{url.query}" if url.query else ""
        return RedirectResponse(f"{public}{url.path}{query}", status_code=307)


def mount_web(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.is_file():

        @app.get("/", include_in_schema=False)
        async def not_built() -> PlainTextResponse:
            return PlainTextResponse(
                "The front end isn't built yet. Run `make build`, or use `make dev`.",
                status_code=503,
            )

        return

    root = dist.resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = (dist / path).resolve()
        if path and file.is_file() and root in file.parents:
            return FileResponse(file)
        return FileResponse(index)
