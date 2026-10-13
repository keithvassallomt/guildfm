import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from guildfm import __version__, api
from guildfm.accounts import seed_admin
from guildfm.config import Settings, get_settings
from guildfm.db import make_engine, upgrade_to_head
from guildfm.live import LiveHub, live_socket
from guildfm.playback import PlaybackController
from guildfm.speakers import SocoSystem, SpeakerSystem
from guildfm.web import mount_web

SESSION_DAYS = 180


def create_app(settings: Settings | None = None, speakers: SpeakerSystem | None = None) -> FastAPI:
    """Build the app. Tests pass fake `speakers` so nothing touches the office Sonos system."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(upgrade_to_head, settings.sync_database_url)
        engine = make_engine(settings.database_url)
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with app.state.sessionmaker() as db:
            await seed_admin(db, settings)

        poller = asyncio.create_task(app.state.playback.run())
        yield
        poller.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller
        await engine.dispose()

    app = FastAPI(title="GuildFM", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.live = LiveHub()
    app.state.playback = PlaybackController(
        speakers or SocoSystem(settings.sonos_host_list), app.state.live
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.guildfm_secret_key.get_secret_value(),
        session_cookie="guildfm_session",
        max_age=SESSION_DAYS * 24 * 60 * 60,
        same_site="lax",
    )
    app.include_router(api.router, prefix="/api")
    app.add_api_websocket_route("/ws", live_socket)
    # Sound files the speakers fetch, such as announcements. Open to the network, since the
    # speakers can't sign in.
    media = settings.data_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media), name="media")
    # Last, so its catch-all route doesn't shadow the API.
    mount_web(app, settings.web_dist)
    return app
