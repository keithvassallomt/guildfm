from fastapi import APIRouter

from guildfm.api import account, health, playback, users

router = APIRouter()
router.include_router(health.router)
router.include_router(account.router)
router.include_router(users.router)
router.include_router(playback.router)
