from fastapi import APIRouter

from guildfm.api import account, health, playback, queue, search, settings, spotify, users

router = APIRouter()
router.include_router(health.router)
router.include_router(account.router)
router.include_router(users.router)
router.include_router(playback.router)
router.include_router(search.router)
router.include_router(queue.router)
router.include_router(spotify.router)
router.include_router(settings.router)
