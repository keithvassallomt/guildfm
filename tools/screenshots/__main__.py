"""Takes the help's screenshots: `python -m tools.screenshots [name ...]`, where names can use
wildcards such as `queue-*`. With none, takes every one. Needs the front end built."""

import asyncio
import logging
import os
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import time_machine
import uvicorn
from playwright.async_api import async_playwright

from guildfm.config import ROOT
from tools.screenshots import shots  # noqa: F401  (registers the shots)
from tools.screenshots.camera import save, take
from tools.screenshots.office import MOMENT, PORT, build, seed

SETTING_UP = timedelta(minutes=5)  # the office is set up this long before the moment


def chromium() -> str | None:
    """The browser to use: CHROMIUM if set, or the system's Chromium, or else Playwright's
    own (`uv run playwright install chromium`)."""
    return (
        os.environ.get("CHROMIUM") or shutil.which("chromium") or shutil.which("chromium-browser")
    )


async def main(patterns: list[str]) -> None:
    if not (ROOT / "web" / "dist" / "index.html").exists():
        raise SystemExit("Build the front end first: make build")
    logging.getLogger("guildfm").setLevel(logging.WARNING)

    with tempfile.TemporaryDirectory() as data, time_machine.travel(MOMENT - SETTING_UP) as clock:
        app, speakers = build(Path(data))
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
        )
        serving = asyncio.create_task(server.serve())
        while not server.started:
            if serving.done():
                serving.result()
            await asyncio.sleep(0.05)
        try:
            print("Setting up the office")
            office = await seed(app, speakers)
            clock.move_to(MOMENT)
            print("Taking screenshots")
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(executable_path=chromium())
                manifest, failed = await take(
                    browser, office, patterns, lambda: clock.move_to(MOMENT)
                )
                await browser.close()
            await office.close()
        finally:
            server.should_exit = True
            await serving
    save(manifest)
    if failed:
        raise SystemExit("These shots failed:\n" + "\n\n".join(failed))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
