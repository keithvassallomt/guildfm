"""Keeps GuildFM to the office when it's reached from outside, through Cloudflare.

Cloudflare tells GuildFM who each visitor is with the Cf-Connecting-Ip header. Anyone on the
office Wi-Fi reaches the internet from the same public address as the office machine itself, so
a visitor is let in when their address is the machine's own. The office's address can change,
so the machine looks its own up, and looks again when someone arrives from an address it
doesn't know. Requests that don't come through Cloudflare, such as the speakers' and anything
by name on the office network, carry no header and are left alone.
"""

import asyncio
import ipaddress
import logging
import time
from collections.abc import Awaitable, Callable

import httpx2
from starlette.responses import HTMLResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)

HEADER = b"cf-connecting-ip"
TRACE = "https://cloudflare.com/cdn-cgi/trace"
# How often a stranger's visit may send the machine to look its own address up again.
RECHECK_SECONDS = 60

Address = ipaddress.IPv4Address | ipaddress.IPv6Address
Lookup = Callable[[], Awaitable[list[str]]]


async def own_addresses() -> list[str]:
    """The office's public addresses as Cloudflare sees them, over IPv4 and, if the office has
    it, IPv6."""
    found = []
    for local in ("0.0.0.0", "::"):
        transport = httpx2.AsyncHTTPTransport(local_address=local)
        try:
            async with httpx2.AsyncClient(transport=transport, timeout=5) as http:
                response = await http.get(TRACE)
            for line in response.text.splitlines():
                if line.startswith("ip="):
                    found.append(line.removeprefix("ip="))
        except httpx2.HTTPError:
            continue
    return found


class Office:
    """The office's public addresses: the IPv4 address, and the IPv6 network (a /64, which
    every device on the same network shares)."""

    def __init__(self, lookup: Lookup = own_addresses) -> None:
        self._lookup = lookup
        self._networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        self._looked = float("-inf")
        self._lock = asyncio.Lock()

    def _knows(self, visitor: Address) -> bool:
        return any(visitor in network for network in self._networks)

    async def _refresh(self) -> None:
        async with self._lock:
            if time.monotonic() - self._looked < RECHECK_SECONDS:
                return
            self._looked = time.monotonic()
            try:
                found = await self._lookup()
            except Exception:
                log.exception("Couldn't look up the office's public address")
                return
            networks = []
            for text in found:
                try:
                    address = ipaddress.ip_address(text)
                except ValueError:
                    continue
                prefix = 32 if address.version == 4 else 64
                networks.append(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
            if networks and networks != self._networks:
                log.info("The office reaches the internet from %s", ", ".join(map(str, networks)))
                self._networks = networks

    async def admits(self, visitor: str) -> bool:
        """Whether a visitor's address is the office's, looking the office up again if not."""
        try:
            address = ipaddress.ip_address(visitor.strip())
        except ValueError:
            return False
        if self._knows(address):
            return True
        await self._refresh()
        return self._knows(address)


ELSEWHERE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GuildFM</title>
<style>
  :root { color-scheme: light dark; --bg: #f6f4ef; --fg: #1d1b18; --muted: #6b665d; }
  @media (prefers-color-scheme: dark) { :root { --bg: #151412; --fg: #f1eee8; --muted: #a39d92; } }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg);
         color: var(--fg); font: 17px/1.5 system-ui, sans-serif; }
  main { max-width: 26rem; padding: 2rem 1rem; text-align: center; }
  h1 { font-size: 1.5rem; margin: 0 0 .75rem; }
  p { margin: 0 0 .75rem; color: var(--muted); }
</style>
</head>
<body>
<main>
  <h1>Connect to TJardinePrivate</h1>
  <p>GuildFM only works inside the office, on the TJardinePrivate Wi-Fi.</p>
  <p>Join it, turn mobile data off if it keeps getting used, and open this page again.</p>
</main>
</body>
</html>
"""


class OfficeOnly:
    """Turns away visitors who reach GuildFM through Cloudflare from outside the office."""

    def __init__(self, app: ASGIApp, office: Office) -> None:
        self.app = app
        self.office = office

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        visitor = dict(scope["headers"]).get(HEADER)
        if visitor is None or await self.office.admits(visitor.decode("latin-1")):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = HTMLResponse(ELSEWHERE, status_code=403, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)
