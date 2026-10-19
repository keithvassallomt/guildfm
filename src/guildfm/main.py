import asyncio
import contextlib
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from guildfm import __version__, api
from guildfm.accounts import seed_admin
from guildfm.ai import AIClient
from guildfm.announcements import Announcer
from guildfm.awareness import Awareness
from guildfm.config import Settings, get_settings
from guildfm.covers import Painter
from guildfm.db import make_engine, upgrade_to_head
from guildfm.dj import DJ
from guildfm.housekeeping import Housekeeping
from guildfm.jingles import JinglePlayer
from guildfm.live import LiveHub, live_socket
from guildfm.logs import Recent, to_console
from guildfm.monitor import MonitorRelay, MonitorSystem
from guildfm.playback import PlaybackController
from guildfm.prefs import get_pref
from guildfm.queue import QueueEngine
from guildfm.radio import Radio
from guildfm.schedule import Scheduler
from guildfm.speakers import SocoSystem, SpeakerSystem
from guildfm.speech import SpeechClient
from guildfm.spotify import SpotifyClient
from guildfm.web import mount_web

SESSION_DAYS = 180


def create_app(
    settings: Settings | None = None,
    speakers: SpeakerSystem | None = None,
    spotify: SpotifyClient | None = None,
    poll: bool = True,
    now: Callable[[], datetime] | None = None,
    speech: SpeechClient | None = None,
    ai: AIClient | None = None,
    awareness: Awareness | None = None,
    monitor: MonitorSystem | None = None,
) -> FastAPI:
    """Build the app. Tests pass fakes, so nothing touches the office speakers, Spotify, OpenAI
    or the weather, turn off `poll` so they decide when the speakers are read and announcements
    are checked, and set `now` to pick the time."""
    settings = settings or get_settings()
    to_console()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.started_at = time.time()
        app.state.problems = Recent()
        app.state.problems.attach()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(upgrade_to_head, settings.sync_database_url)
        engine = make_engine(settings.database_url)
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with app.state.sessionmaker() as db:
            await seed_admin(db, settings)
            monitoring = await get_pref(db, "monitor")
        if monitoring:
            await app.state.playback.use(app.state.monitor, monitoring=True)
        await app.state.playback.pick_up()
        clock = {"clock": now} if now else {}
        app.state.radio = Radio(
            app.state.sessionmaker,
            app.state.ai,
            app.state.spotify,
            app.state.awareness,
            **clock,
        )
        app.state.queue = QueueEngine(
            app.state.sessionmaker,
            app.state.playback,
            app.state.live,
            sid=settings.sonos_spotify_sid,
            sn=settings.sonos_spotify_sn,
            radio=app.state.radio,
        )
        # New picks are on the Queue screen, and start the music if it had run out.
        app.state.radio.on_picked += [app.state.queue.changed, app.state.queue.keep_fed]
        app.state.covers = Painter(
            app.state.sessionmaker, app.state.ai, settings.data_dir / "media"
        )
        app.state.covers.on_painted.append(app.state.queue.changed)
        await app.state.queue.recover()
        app.state.schedule = Scheduler(app.state.sessionmaker, app.state.playback, **clock)
        await app.state.schedule.tick()
        app.state.housekeeping = Housekeeping(app.state.speech, settings.data_dir, settings.backups)
        app.state.announcer = Announcer(
            app.state.sessionmaker,
            app.state.playback,
            app.state.speech,
            app.state.live,
            port=settings.port,
            **clock,
        )
        app.state.dj = DJ(
            app.state.sessionmaker,
            app.state.announcer,
            app.state.ai,
            app.state.speech,
            app.state.awareness,
            **clock,
        )
        app.state.jingles = JinglePlayer(
            app.state.sessionmaker,
            app.state.announcer,
            settings.data_dir / "media",
        )
        # The jingle first, so it plays before anything the DJ says in the same pause.
        app.state.queue.on_lined_up += [app.state.jingles.lined_up, app.state.dj.lined_up]

        loops = (
            (
                app.state.playback.run(),
                app.state.schedule.run(),
                app.state.announcer.run(),
                app.state.covers.fill_in(),
                app.state.housekeeping.run(),
                app.state.monitor_relay.run(),
            )
            if poll
            else ()
        )
        tasks = [asyncio.create_task(loop) for loop in loops]
        yield
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await app.state.radio.close()
        await app.state.dj.close()
        await app.state.covers.close()
        await app.state.spotify.close()
        await app.state.speech.close()
        await app.state.awareness.close()
        await app.state.ai.close()
        await engine.dispose()
        app.state.problems.detach()

    app = FastAPI(title="GuildFM", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.live = LiveHub()
    app.state.sonos = speakers or SocoSystem(settings.sonos_host_list)
    app.state.monitor = monitor or MonitorSystem()
    app.state.playback = PlaybackController(
        app.state.sonos, app.state.live, memory=settings.data_dir / "speakers.json"
    )
    app.state.monitor_relay = MonitorRelay(
        app.state.monitor, app.state.live, lambda: app.state.playback.monitoring
    )
    app.state.spotify = spotify or SpotifyClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret.get_secret_value(),
        redirect_uri=settings.spotify_redirect_uri,
        market=settings.spotify_market,
    )
    app.state.speech = speech or SpeechClient(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_tts_model,
        media_dir=settings.data_dir / "media",
        eleven_key=settings.elevenlabs_api_key.get_secret_value(),
        eleven_model=settings.elevenlabs_model,
        loudness=settings.audio_loudness,
    )
    app.state.ai = ai or AIClient(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
        effort=settings.openai_effort,
        image_model=settings.openai_image_model,
        image_quality=settings.openai_image_quality,
    )
    app.state.awareness = awareness or Awareness(app.state.ai)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.guildfm_secret_key.get_secret_value(),
        session_cookie="guildfm_session",
        max_age=SESSION_DAYS * 24 * 60 * 60,
        same_site="lax",
    )
    app.include_router(api.router, prefix="/api")
    app.include_router(api.spotify.callback_router)
    app.add_api_websocket_route("/ws", live_socket)
    # Sound files the speakers fetch, such as announcements. Open to the network, since the
    # speakers can't sign in.
    media = settings.data_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media), name="media")
    # Last, so its catch-all route doesn't shadow the API.
    mount_web(app, settings.web_dist)
    return app
