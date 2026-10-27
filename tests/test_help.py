"""The help's topics hold together: every page has one, every screenshot they show exists for
everyone who reads it, and nobody is shown another role's screen."""

import json
import re
from dataclasses import dataclass, field

import pytest

from guildfm.config import ROOT
from guildfm.models import Role
from guildfm.permissions import ROLE_PERMISSIONS, Permission

WEB = ROOT / "web" / "src"
TOPICS = WEB / "help" / "topics"
SHOTS = json.loads((WEB / "help" / "shots.json").read_text())
SIZES = ("phone", "desktop")
ROLES = ("user", "curator", "admin")  # lowest first, as the help falls back
# Pages that aren't the app's own: redirects from old addresses, and the help itself (loaded
# while it's needed, so wrapped in Suspense, and in main when signed out).
NOT_PAGES = {"Navigate", "OldLibrary", "OldLibraryItem", "WelcomePage", "Suspense", "main"}


@dataclass
class Topic:
    id: str
    meta: dict[str, str]
    # Each screenshot, with the blocks it's in: ("needs", "vote"), ("phone", "") and so on.
    shots: list[tuple[str, tuple[tuple[str, str], ...]]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    blocks: list[tuple[str, str]] = field(default_factory=list)


def parse(path) -> Topic:
    text = path.read_text()
    found = re.match(r"---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert found, f"{path.name} has no front matter"
    meta = dict(line.split(":", 1) for line in found[1].splitlines())
    topic = Topic(path.stem, {key.strip(): value.strip() for key, value in meta.items()})
    open_blocks: list[tuple[str, str]] = []
    for line in found[2].splitlines():
        if block := re.match(r"^:::\s*(needs|lacks)\s+([a-z_]+)\s*$", line):
            open_blocks.append((block[1], block[2]))
            topic.blocks.append((block[1], block[2]))
        elif screen := re.match(r"^:::\s*(phone|desktop)\s*$", line):
            open_blocks.append((screen[1], ""))
        elif re.match(r"^:::\s*$", line):
            assert open_blocks, f"{path.name} closes a block it didn't open"
            open_blocks.pop()
        else:
            assert not line.startswith(":::"), f"{path.name} has a block it can't read: {line}"
            for shot in re.findall(r"!\[[^\]]*\]\(shot:([^)]+)\)", line):
                topic.shots.append((shot, tuple(open_blocks)))
            topic.links += re.findall(r"\]\(topic:([^)]+)\)", line)
    assert not open_blocks, f"{path.name} leaves a block open"
    return topic


ALL = [parse(path) for path in sorted(TOPICS.glob("*.md"))]
AREAS = re.findall(r'\{ id: "(\w+)", title:', (WEB / "help" / "topics.ts").read_text())


def can(role: str, permission: str) -> bool:
    return Permission(permission) in ROLE_PERMISSIONS[Role(role)]


def readers(topic: Topic, blocks: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    """Who sees something in a topic, inside `blocks`: (role, screen size) pairs, with "guest"
    for a public topic read before signing in."""
    seen = []
    needs = topic.meta.get("needs")
    for role in (*ROLES, "guest"):
        if role == "guest":
            if topic.meta.get("public") != "yes":
                continue
        elif needs and not can(role, needs):
            continue
        for size in SIZES:
            shown = all(
                (kind == "needs" and role != "guest" and can(role, arg))
                or (kind == "lacks" and (role == "guest" or not can(role, arg)))
                or kind == size
                for kind, arg in blocks
            )
            if shown:
                seen.append((role, size))
    return seen


@pytest.mark.parametrize("topic", ALL, ids=lambda topic: topic.id)
def test_topic_holds_together(topic: Topic) -> None:
    assert topic.meta.get("title") and topic.meta.get("summary")
    assert topic.meta.get("area") in AREAS
    if needs := topic.meta.get("needs"):
        assert needs in set(Permission), f"{needs} isn't a permission"
    for _, permission in topic.blocks:
        assert permission in set(Permission), f"{permission} isn't a permission"
    if topic.meta.get("public") == "yes":
        # Guests can't do anything yet, so blocks for what people can do would mislead them.
        assert not topic.meta.get("needs") and not topic.blocks
    for link in topic.links:
        assert (TOPICS / f"{link}.md").exists(), f"there's no topic {link}"


@pytest.mark.parametrize("topic", ALL, ids=lambda topic: topic.id)
def test_every_reader_sees_their_own_screenshots(topic: Topic) -> None:
    """Each screenshot exists for every role and screen size that reads it, taken as that role
    or one below it, so nobody sees controls they don't have. Guests see whatever there is."""
    for shot, blocks in topic.shots:
        assert shot in SHOTS, f"there's no screenshot {shot}"
        for role, size in readers(topic, blocks):
            taken = SHOTS[shot].get(size, {})
            fits = taken if role == "guest" else [r for r in taken if r == "guest" or (
                r in ROLES and ROLES.index(r) <= ROLES.index(role)
            )]  # fmt: skip
            assert fits, f"{shot} isn't taken for {role} on a {size}"


def test_every_screenshot_is_used() -> None:
    used = {shot for topic in ALL for shot, _ in topic.shots}
    assert set(SHOTS) - used == set(), "screenshots no topic shows"


def routes() -> list[tuple[str, str]]:
    """The app's pages, as (address, page), from App.tsx."""
    app = (WEB / "App.tsx").read_text()
    found = re.findall(
        r'<Route\s+(?:index|path="([^"]*)")\s+element=\{\s*(?:<Allowed[^>]*>\s*)?<(\w+)', app
    )
    return [(f"/{path}", page) for path, page in found if page not in NOT_PAGES]


@pytest.mark.parametrize(("address", "page"), routes())
def test_every_page_has_help(address: str, page: str) -> None:
    """Its ? opens a topic, so the page has one, and the ? is on it."""
    assert any(
        address in [p.strip() for p in topic.meta.get("pages", "").split(",")] for topic in ALL
    ), f"no topic is the help for {address}"
    assert "<HelpLink" in (WEB / "pages" / f"{page}.tsx").read_text(), f"{page} has no ?"


def test_routes_are_read() -> None:
    assert ("/", "NowPlayingPage") in routes()
    assert ("/radio/:id", "StationEditor") in routes()
