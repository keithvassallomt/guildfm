"""Taking the help's screenshots: a browser per role and screen size, signed in as that role's
reader, each shot framed, the control it's about ringed in orange, and saved as WebP with a
manifest the help reads."""

import hashlib
import io
import json
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

from PIL import Image
from playwright.async_api import Browser, BrowserContext, Locator, Page

from guildfm.config import ROOT
from tools.screenshots.cast import PASSWORD, READERS
from tools.screenshots.office import BASE, MOMENT, PHASES, Office, enter

SHOTS_DIR = ROOT / "web" / "public" / "help" / "shots"
MANIFEST = ROOT / "web" / "src" / "help" / "shots.json"
ROLES = ("user", "curator", "admin")
GUEST = "guest"  # signed out, or signing in for the first time
SIZES: dict[str, dict[str, Any]] = {
    "phone": {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True},
    "desktop": {"viewport": {"width": 1280, "height": 800}},
}
SCALE = 2  # pixels per CSS pixel, so shots are sharp on phones and high-density screens
PAD = 14  # room around a cropped shot, in CSS pixels, enough for a ring

# What a shot shows: the whole screen (None), or a crop round one or more parts of it.
Frame = Locator | list[Locator] | None


@dataclass(frozen=True)
class Shot:
    name: str
    roles: tuple[str, ...]
    take: Callable[[Scene], Awaitable[Frame]]
    phase: str
    # For a guest shot: someone to sign in as, such as the new starter, rather than nobody.
    person: str | None


SHOTS: dict[str, Shot] = {}


def shot(
    name: str, roles: tuple[str, ...] = ROLES, phase: str = PHASES[0], person: str | None = None
):
    """Registers a shot, taken through each of `roles`' eyes on a phone and a desktop, once the
    office has reached `phase`."""
    assert phase in PHASES, phase

    def register(take: Callable[[Scene], Awaitable[Frame]]):
        SHOTS[name] = Shot(name, roles, take, phase, person)
        return take

    return register


RING = """(target, pad) => {
  const box = target.getBoundingClientRect();
  // A modal dialog sits above the page, so a ring for something in one goes inside it.
  const dialog = target.closest("dialog[open]");
  const ring = document.createElement("div");
  ring.dataset.helpRing = "";
  let left = box.left - pad, top = box.top - pad;
  if (dialog) {
    const outer = dialog.getBoundingClientRect();
    left -= outer.left + dialog.clientLeft;
    top -= outer.top + dialog.clientTop;
  } else {
    left += scrollX;
    top += scrollY;
  }
  Object.assign(ring.style, {
    position: "absolute", left: `${left}px`, top: `${top}px`,
    width: `${box.width + pad * 2}px`, height: `${box.height + pad * 2}px`,
    border: "3px solid #ff8a3d", borderRadius: "14px",
    boxShadow: "0 0 0 4px rgba(255, 138, 61, 0.28)",
    pointerEvents: "none", zIndex: 2147483647,
  });
  (dialog ?? document.body).append(ring);
}"""

# Things fixed to the screen, such as the tab bar and the quick controls, would land on a crop of
# the whole page, so they're hidden for crops. Dialogs stay.
UNFIX = """() => {
  for (const element of document.querySelectorAll("body *")) {
    if (getComputedStyle(element).position === "fixed" && !element.closest("dialog")) {
      element.style.visibility = "hidden";
    }
  }
}"""

SETTLED = """() => document.fonts.status === "loaded"
  && [...document.images].every((image) => image.complete)"""


class Scene:
    """One shot being set up: the page, and whose eyes and what size of screen it's for."""

    def __init__(self, page: Page, role: str, size: str, office: Office) -> None:
        self.page = page
        self.role = role
        self.size = size
        self.office = office

    @property
    def phone(self) -> bool:
        return self.size == "phone"

    @property
    def reader(self) -> str | None:
        return READERS.get(self.role)

    async def open(self, path: str, ready: Locator | None = None) -> None:
        """Goes to `path` and waits for it to be drawn, or for `ready` to show."""
        await self.page.goto(f"{BASE}{path}")
        if ready is not None:
            await ready.first.wait_for()
        await self.settle()

    async def settle(self) -> None:
        """Waits for fonts and pictures, and for the live updates to have arrived."""
        await self.page.wait_for_load_state("load")
        await self.page.wait_for_function(SETTLED)
        await self.page.wait_for_timeout(400)

    def sheet(self) -> Frame:
        """The open dialog: the whole screen on a phone, where it's a sheet over the page, and
        just the dialog on a desktop."""
        return None if self.phone else self.page.locator("dialog[open]")

    async def ring(self, target: Locator, pad: int = 5) -> None:
        await target.scroll_into_view_if_needed()
        await target.evaluate(RING, pad)


async def capture(scene: Scene, frame: Frame) -> tuple[bytes, bool]:
    """The shot as PNG, and whether it's the whole screen."""
    page = scene.page
    await page.wait_for_timeout(150)
    if frame is None:
        return await page.screenshot(animations="disabled"), True
    parts = frame if isinstance(frame, list) else [frame]
    boxes = [await part.bounding_box() for part in parts]
    if any(box is None for box in boxes):
        raise RuntimeError("Part of a shot isn't on the screen")
    in_dialog = await parts[0].evaluate("(part) => !!part.closest('dialog[open]')")
    # A dialog is cropped to its edge, leaving out the page dimmed behind it.
    pad = 0 if in_dialog else PAD
    left = min(box["x"] for box in boxes) - pad
    top = min(box["y"] for box in boxes) - pad
    right = max(box["x"] + box["width"] for box in boxes) + pad
    bottom = max(box["y"] + box["height"] for box in boxes) + pad
    width, height = page.viewport_size["width"], page.viewport_size["height"]
    if in_dialog:
        # Dialogs stay put on the screen, so they're cropped from what's on it.
        clip = {"x": max(0, left), "y": max(0, top)}
        clip |= {"width": min(width, right) - clip["x"], "height": min(height, bottom) - clip["y"]}
        return await page.screenshot(clip=clip, animations="disabled"), False
    # Anything else is cropped from the whole page, so a long part needn't fit on the screen.
    await page.evaluate(UNFIX)
    scroll_x, scroll_y = await page.evaluate("[scrollX, scrollY]")
    left, right = max(0, left), min(width, right)
    clip = {"x": left + scroll_x, "y": max(0, top + scroll_y)}
    clip |= {"width": right - left, "height": bottom + scroll_y - clip["y"]}
    return await page.screenshot(clip=clip, full_page=True, animations="disabled"), False


def webp(png: bytes) -> tuple[bytes, int, int]:
    """The shot as WebP, with its size in CSS pixels."""
    picture = Image.open(io.BytesIO(png)).convert("RGB")
    out = io.BytesIO()
    picture.save(out, "WEBP", quality=80, method=6)
    return out.getvalue(), round(picture.width / SCALE), round(picture.height / SCALE)


async def sign_in(context: BrowserContext, username: str, password: str) -> None:
    response = await context.request.post(
        f"{BASE}/api/auth/login", data={"username": username, "password": password}
    )
    if not response.ok:
        raise RuntimeError(f"Couldn't sign in as {username}: {await response.text()}")


async def browse(browser: Browser, size: str) -> BrowserContext:
    return await browser.new_context(
        **SIZES[size],
        device_scale_factor=SCALE,
        reduced_motion="reduce",
        color_scheme="dark",
        timezone_id="Europe/London",
        locale="en-GB",
    )


async def take(
    browser: Browser, office: Office, patterns: list[str], rewind: Callable[[], None]
) -> tuple[dict[str, Any], list[str]]:
    """Takes the shots whose names match `patterns` (all of them when it's empty), moving the
    office through its phases as they need, and turning the clock back to the moment for each,
    so the times shown don't depend on how long the shots take. Returns the manifest with them
    in, and the shots that failed, with why. A failed shot doesn't stop the rest."""
    wanted = [
        s for s in SHOTS.values() if not patterns or any(fnmatch(s.name, p) for p in patterns)
    ]
    if not wanted:
        raise SystemExit(f"No shots match {' '.join(patterns)}")
    manifest: dict[str, Any] = (
        json.loads(MANIFEST.read_text()) if patterns and MANIFEST.exists() else {}
    )
    if not patterns:
        shutil.rmtree(SHOTS_DIR, ignore_errors=True)
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    last = max(PHASES.index(each.phase) for each in wanted)
    for number, phase in enumerate(PHASES[: last + 1]):
        if number:
            print(f"The office moves on: {phase}")
            await enter(office, phase)
        rewind()
        for role in (GUEST, *ROLES):
            for size in SIZES:
                batch = [s for s in wanted if s.phase == phase and role in s.roles]
                if not batch:
                    continue
                context = await browse(browser, size)
                if role != GUEST:
                    await sign_in(context, READERS[role], PASSWORD)
                for each in batch:
                    own = None
                    if each.person:
                        own = await browse(browser, size)
                        password = office.passwords.get(each.person, PASSWORD)
                        await sign_in(own, each.person, password)
                    page = await (own or context).new_page()
                    await page.clock.set_fixed_time(MOMENT)
                    scene = Scene(page, role, size, office)
                    who = each.person or READERS.get(role, role)
                    try:
                        png, screen = await capture(scene, await each.take(scene))
                    except Exception as error:
                        failed.append(f"{each.name} as {who} on a {size}: {error}")
                        print(f"  FAILED {failed[-1].splitlines()[0]}")
                    else:
                        data, width, height = webp(png)
                        (SHOTS_DIR / f"{each.name}.{role}.{size}.webp").write_bytes(data)
                        version = hashlib.sha1(data).hexdigest()[:8]
                        entry = manifest.setdefault(each.name, {}).setdefault(size, {})
                        entry[role] = {"w": width, "h": height, "v": version, "screen": screen}
                        print(f"  {each.name} as {who} on a {size}")
                    await page.close()
                    if own:
                        await own.close()
                await context.close()

    # Shots taken again lose any roles they're no longer taken for. A role whose shot is the
    # same as the role's below goes too: the help shows a reader the nearest role's below theirs.
    for each in wanted:
        for size in SIZES:
            sizes = manifest.get(each.name, {}).get(size, {})
            below = None
            for role in [r for r in (GUEST, *ROLES) if r in sizes]:
                same = below is not None and sizes[role]["v"] == below and role != GUEST
                if role not in each.roles or same:
                    del sizes[role]
                    (SHOTS_DIR / f"{each.name}.{role}.{size}.webp").unlink(missing_ok=True)
                else:
                    below = sizes[role]["v"]
    return dict(sorted(manifest.items())), failed


def save(manifest: dict[str, Any]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n")
