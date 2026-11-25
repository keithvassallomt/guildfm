"""Keeps GuildFM to the office when it's reached from outside, through Cloudflare.

Cloudflare tells GuildFM who each visitor is with the Cf-Connecting-Ip header. Anyone on the
office Wi-Fi reaches the internet from the same public address as the office machine itself, so
a visitor is let in when their address is the machine's own. The office's address can change,
so the machine looks its own up, and looks again when someone arrives from an address it
doesn't know. Requests that don't come through Cloudflare, such as the speakers' and anything
by name on the office network, carry no header and are left alone.

Some people in the office still arrive from another address: Safari's iCloud Private Relay
sends them out through Apple. The page that turns them away offers two other ways in. They can
confirm their location, once an admin has set the office's, or let Safari show GuildFM their
real address. Either way they get a day pass: a signed cookie that lets that browser in until
midnight, office time, whatever address it comes from.
"""

import asyncio
import ipaddress
import logging
import math
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
from itsdangerous import BadSignature, Signer
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection, Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from guildfm.prefs import get_pref

log = logging.getLogger(__name__)

HEADER = b"cf-connecting-ip"
TRACE = "https://cloudflare.com/cdn-cgi/trace"
# How often a stranger's visit may send the machine to look its own address up again.
RECHECK_SECONDS = 60

# The day pass, and the note that a browser was turned away. Safari's Show IP Address only lasts
# until the tab reloads, so a browser that was turned away a little while ago and comes back from
# the office's address gets a day pass, and needn't do it again.
PASS_COOKIE = "guildfm_office_pass"
TURNED_AWAY_COOKIE = "guildfm_turned_away"
TURNED_AWAY_SECONDS = 30 * 60

# Confirming a location: near enough to the office, and sure enough about it. Phones indoors are
# usually sure to within 10 to 50 m. With precise location off they're only sure to a few km.
HERE = "/office/here"
NEAR_METRES = 150
ROUGH_METRES = 500

# How to let Safari show GuildFM the address, in pictures.
PICTURES = {
    f"/office/{name}.webp": Path(__file__).parent / "connect" / f"{name}.webp"
    for name in ("iphone", "mac")
}

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


class DayPass:
    """A signed note of when a browser's pass runs out."""

    def __init__(self, secret: str) -> None:
        self._signer = Signer(secret, salt="guildfm-office-pass")

    def issue(self, until: datetime) -> str:
        return self._signer.sign(str(int(until.timestamp()))).decode()

    def valid(self, value: str | None, now: datetime) -> bool:
        if not value:
            return False
        try:
            until = int(self._signer.unsign(value))
        except BadSignature, ValueError:
            return False
        return now.timestamp() < until


def midnight_after(now: datetime, zone: ZoneInfo) -> datetime:
    tomorrow = now.astimezone(zone).date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=zone)


def metres_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The distance between two points on the Earth, each a latitude and longitude."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2
    h += math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


class Reading(BaseModel):
    """Where a browser says it is, and how sure it is, in metres."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float = Field(ge=0, le=20_000_000)


def cookie(name: str, value: str, **when: Any) -> str:
    """A Set-Cookie header's value, for the whole site, over HTTPS only."""
    response = Response()
    response.set_cookie(name, value, path="/", secure=True, httponly=True, samesite="lax", **when)
    return response.headers["set-cookie"]


class OfficeOnly:
    """Turns away visitors who reach GuildFM through Cloudflare from outside the office, unless
    they have a day pass."""

    def __init__(
        self,
        app: ASGIApp,
        office: Office,
        secret: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.app = app
        self.office = office
        self.passes = DayPass(secret)
        self.now = now

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        visitor = dict(scope["headers"]).get(HEADER)
        if visitor is None:
            return await self.app(scope, receive, send)
        visitor_text = visitor.decode("latin-1")
        path = scope["path"]
        if scope["type"] == "http" and path in PICTURES:
            pictures = FileResponse(
                PICTURES[path], headers={"Cache-Control": "public, max-age=86400"}
            )
            return await pictures(scope, receive, send)
        if scope["type"] == "http" and path == HERE and scope["method"] == "POST":
            return await self.locate(scope, receive, send, visitor_text)

        cookies = HTTPConnection(scope).cookies
        if self.passes.valid(cookies.get(PASS_COOKIE), self.now()):
            return await self.app(scope, receive, send)
        if await self.office.admits(visitor_text):
            if scope["type"] == "http" and TURNED_AWAY_COOKIE in cookies:
                log.info("%s was turned away and is back on the office's address", visitor_text)
                forget = cookie(TURNED_AWAY_COOKIE, "", max_age=0)
                send = self.adding(send, await self.day_pass(scope), forget)
            return await self.app(scope, receive, send)

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        place, _ = await self.office_prefs(scope)
        page = HTMLResponse(
            connect_page(locating=place is not None),
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )
        page.raw_headers.append(
            (b"set-cookie", cookie(TURNED_AWAY_COOKIE, "1", max_age=TURNED_AWAY_SECONDS).encode())
        )
        await page(scope, receive, send)

    async def office_prefs(self, scope: Scope) -> tuple[dict[str, float] | None, ZoneInfo]:
        """Where the office is, if an admin has set it, and its time zone."""
        async with scope["app"].state.sessionmaker() as db:
            place = await get_pref(db, "office_location")
            zone = ZoneInfo(await get_pref(db, "timezone"))
        return place, zone

    async def day_pass(self, scope: Scope) -> str:
        _, zone = await self.office_prefs(scope)
        until = midnight_after(self.now(), zone)
        return cookie(PASS_COOKIE, self.passes.issue(until), expires=until.astimezone(UTC))

    @staticmethod
    def adding(send: Send, *cookies: str) -> Send:
        """`send`, with cookies set on the response."""

        async def sending(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for value in cookies:
                    headers.append("set-cookie", value)
            await send(message)

        return sending

    async def locate(self, scope: Scope, receive: Receive, send: Send, visitor: str) -> None:
        """Lets a browser in for the day if it says it's in the office."""
        try:
            reading = Reading.model_validate(await Request(scope, receive).json())
        except ValueError, ValidationError:
            return await JSONResponse({"in": False, "why": "unreadable"}, 422)(scope, receive, send)
        place, _ = await self.office_prefs(scope)
        if place is None:
            answer: dict[str, Any] = {"in": False, "why": "off"}
        else:
            distance = metres_between(
                (reading.latitude, reading.longitude), (place["latitude"], place["longitude"])
            )
            if reading.accuracy > ROUGH_METRES:
                answer = {"in": False, "why": "rough", "accuracy": round(reading.accuracy)}
            elif distance > NEAR_METRES:
                answer = {"in": False, "why": "far", "distance": round(distance)}
            else:
                answer = {"in": True}
            # How far and how sure, to tune the distance by. Not where anyone was.
            log.info(
                "Location check from %s: %d m from the office, give or take %d m. %s",
                visitor, distance, reading.accuracy,
                "Let in for the day" if answer["in"] else "Turned away",
            )  # fmt: skip
        response = JSONResponse(answer, headers={"Cache-Control": "no-store"})
        if answer["in"]:
            response.raw_headers.append((b"set-cookie", (await self.day_pass(scope)).encode()))
        await response(scope, receive, send)


CONNECT_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GuildFM</title>
<style>
  :root { color-scheme: light dark; --bg: #f6f4ef; --fg: #1d1b18; --muted: #6b665d;
          --line: #dcd6cb; --accent: #ff8a3d; --on-accent: #1a0e05; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #151412; --fg: #f1eee8; --muted: #a39d92; --line: #36322d; } }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg);
         color: var(--fg); font: 17px/1.5 system-ui, sans-serif; }
  main { max-width: 34rem; padding: 2rem 1rem; text-align: center; }
  h1 { font-size: 1.5rem; margin: 0 0 .75rem; }
  h2 { font-size: 1.15rem; margin: 2rem 0 .5rem; padding-top: 1.5rem;
       border-top: 1px solid var(--line); }
  h3 { font-size: 1rem; margin: 1.75rem 0 .5rem; }
  p { margin: 0 0 .75rem; color: var(--muted); }
  b { color: var(--fg); }
  .small { font-size: .9rem; }
  button { font: inherit; font-weight: 600; min-height: 44px; padding: .5rem 1.25rem;
           border: 0; border-radius: 999px; background: var(--accent); color: var(--on-accent);
           cursor: pointer; margin: .25rem 0 .75rem; }
  button:disabled { opacity: .6; cursor: default; }
  .status:empty { display: none; }
  .status { color: var(--fg); }
  img { display: block; width: 100%; height: auto; margin: .25rem 0 .75rem;
        border-radius: 10px; border: 1px solid var(--line); }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<main>
  <h1>Connect to TJardinePrivate</h1>
  <p>GuildFM only works inside the office, on the TJardinePrivate Wi-Fi.</p>
  <p>Join it, turn mobile data off if it keeps getting used, and open this page again.</p>

  <section id="already" {already_hidden}>
    <h2>Already on it?</h2>
    <p>Then GuildFM can't tell you're in the office. Once it can, this browser gets in for the
       rest of the day.</p>
    {locating}
    <div id="relay" hidden>
      <h3>Let Safari show your address</h3>
      <p>iCloud Private Relay sends Safari through Apple, so GuildFM can't tell you're in the
         office.</p>
      <div data-for="phone" hidden>
        <div class="steps">
          <p>Tap <b>&#x1D00;A</b> in the address bar, then <b>Show IP Address</b>, then
             <b>Continue</b>.</p>
          <img src="/office/iphone.webp" width="1200" height="797" loading="lazy"
               alt="Safari on an iPhone: Show IP Address in the address bar's menu, then Continue.">
        </div>
        <p class="small">To stop it happening at all, go to Settings, Wi-Fi, tap &#9432; next
           to TJardinePrivate and turn off <b>Limit IP Address Tracking</b>.</p>
      </div>
      <div data-for="mac" hidden>
        <p>In Safari's <b>View</b> menu, choose <b>Reload and Show IP Address</b>.</p>
        <img src="/office/mac.webp" width="1600" height="905" loading="lazy"
             alt="Safari on a Mac: the View menu, with Reload and Show IP Address picked.">
      </div>
    </div>
  </section>
</main>
<script>
(function () {
  var ua = navigator.userAgent;
  var touchMac = /Macintosh/.test(ua) && navigator.maxTouchPoints > 1;  // an iPad
  var phone = /iPhone|iPad|iPod/.test(ua) || touchMac;
  var mac = /Macintosh/.test(ua) && !touchMac;
  var app = navigator.standalone === true;  // added to the home screen
  var notSafari = /CriOS|FxiOS|EdgiOS|OPiOS|GSA\\/|Chrome|Chromium|Firefox|Edg\\//.test(ua);
  var safari = !notSafari && (app || /Safari\\//.test(ua));
  if (safari && (phone || mac)) {
    document.getElementById("already").hidden = false;
    document.getElementById("relay").hidden = false;
    document.querySelector('[data-for="' + (phone ? "phone" : "mac") + '"]').hidden = false;
    // A home-screen app has no address bar, so only the setting helps there.
    if (app) document.querySelector('[data-for="phone"] .steps').hidden = true;
  }

  var button = document.getElementById("locate");
  if (!button) return;
  var status = document.getElementById("locate-status");
  function say(words) { status.textContent = words; }
  function away(metres) {
    return metres < 1000 ? metres + " m" : (metres / 1000).toFixed(1) + " km";
  }
  var precise = phone
    ? "Turn on Precise Location (Settings, Privacy & Security, Location Services, Safari " +
      "Websites) and try again."
    : "Let this browser use your precise location and try again.";
  function answered(answer) {
    if (answer.in) { say("You're in the office. Opening GuildFM..."); location.reload(); return; }
    button.disabled = false;
    if (answer.why === "rough") {
      say("Your location only came through roughly, to within " + away(answer.accuracy) +
          ", so GuildFM can't tell you're in the office. " + precise);
    } else if (answer.why === "far") {
      say("You seem to be about " + away(answer.distance) + " from the office. If you're " +
          "in it, try again in a minute, nearer a window.");
    } else {
      say("GuildFM can't check locations right now. Ask an admin.");
    }
  }
  button.addEventListener("click", function () {
    if (!navigator.geolocation) { say("This browser can't share its location."); return; }
    button.disabled = true;
    say("Finding where you are...");
    navigator.geolocation.getCurrentPosition(function (position) {
      var c = position.coords;
      fetch("/office/here", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ latitude: c.latitude, longitude: c.longitude,
                               accuracy: c.accuracy })
      }).then(function (response) { return response.json(); })
        .then(answered)
        .catch(function () { button.disabled = false; say("Couldn't reach GuildFM. Try again."); });
    }, function (error) {
      button.disabled = false;
      say(error.code === 1
        ? "This browser isn't allowed to share your location. Allow it for guildfm.com in " +
          "its settings and try again."
        : "This browser couldn't work out where you are. Try again.");
    }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
  });
})();
</script>
</body>
</html>
"""

LOCATING = """<div id="here">
      <h3>Confirm your location</h3>
      <button type="button" id="locate">Confirm my location</button>
      <p class="small">Your browser tells GuildFM where you are, just this once. If you're in
         the office, you're in.</p>
      <p class="status" id="locate-status" role="status"></p>
    </div>"""


def connect_page(locating: bool) -> str:
    """The page that tells visitors to join the Wi-Fi, with a location check if the office's
    location is set. The Safari part shows itself, in Safari on Apple devices only."""
    return CONNECT_PAGE.replace("{locating}", LOCATING if locating else "").replace(
        "{already_hidden}", "" if locating else "hidden"
    )
