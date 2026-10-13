"""Live updates: one websocket per open browser, and a hub that broadcasts events to all of them."""

from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from guildfm import __version__
from guildfm.auth import session_user

# Close code the browser sees when it isn't signed in, so it can stop retrying.
UNAUTHORISED = 4401


class LiveHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    @property
    def count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

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


async def live_socket(websocket: WebSocket) -> None:
    async with websocket.app.state.sessionmaker() as db:
        user = await session_user(websocket.session, db)
    if user is None or user.must_change_password:
        # Accept first: a close code only reaches the browser on an open socket.
        await websocket.accept()
        await websocket.close(code=UNAUTHORISED)
        return

    hub: LiveHub = websocket.app.state.live
    await hub.connect(websocket)
    await hub.send(websocket, "hello", {"version": __version__})
    await hub.broadcast("presence", {"connected": hub.count})
    try:
        while True:
            if await websocket.receive_text() == "ping":
                await hub.send(websocket, "pong")
    except WebSocketDisconnect:
        hub.disconnect(websocket)
        await hub.broadcast("presence", {"connected": hub.count})
