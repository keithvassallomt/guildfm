"""Live updates: one websocket per open browser, and a hub that broadcasts events to all of them."""

from contextlib import suppress
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from guildfm import __version__
from guildfm.auth import session_user

# Close code the browser sees when it isn't signed in, so it can stop retrying.
UNAUTHORISED = 4401


class LiveHub:
    def __init__(self) -> None:
        # Each open connection, and the id of the user who opened it.
        self._clients: dict[WebSocket, int] = {}

    @property
    def count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        self._clients[websocket] = user_id

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.pop(websocket, None)

    async def send(self, websocket: WebSocket, event: str, data: dict[str, Any] | None = None):
        await websocket.send_json({"event": event, "data": data or {}})

    async def broadcast(self, event: str, data: dict[str, Any] | None = None) -> None:
        dead = []
        for websocket in list(self._clients):
            try:
                await self.send(websocket, event, data)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)

    async def sign_out_user(self, user_id: int) -> None:
        """Close every connection a user has open, after a password reset or deletion."""
        for websocket, owner in list(self._clients.items()):
            if owner == user_id:
                self.disconnect(websocket)
                with suppress(Exception):
                    await websocket.close(code=UNAUTHORISED)


async def live_socket(websocket: WebSocket) -> None:
    async with websocket.app.state.sessionmaker() as db:
        user = await session_user(websocket.session, db)
    if user is None or user.must_change_password:
        # Accept first: a close code only reaches the browser on an open socket.
        await websocket.accept()
        await websocket.close(code=UNAUTHORISED)
        return

    hub: LiveHub = websocket.app.state.live
    await hub.connect(websocket, user.id)
    await hub.send(websocket, "hello", {"version": __version__})
    await hub.broadcast("presence", {"connected": hub.count})
    try:
        # The hub may close this socket from elsewhere, which ends the loop.
        while websocket.application_state == WebSocketState.CONNECTED:
            if await websocket.receive_text() == "ping":
                await hub.send(websocket, "pong")
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)
        await hub.broadcast("presence", {"connected": hub.count})
