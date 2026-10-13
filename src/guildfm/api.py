from fastapi import APIRouter, Request

from guildfm import __version__

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    return {"status": "ok", "version": __version__, "connected": request.app.state.live.count}
