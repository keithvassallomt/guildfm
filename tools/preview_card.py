"""Draws the picture chats show when someone shares a link to GuildFM: `make preview-card`. It's
a page in GuildFM's own look, with its logo and fonts, photographed at 1200 by 630 into
web/public/og-image.png. Needs the front end's packages installed, for the fonts."""

import asyncio
import re
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

from guildfm.config import ROOT
from tools.screenshots.__main__ import chromium

WEB = ROOT / "web"
OUT = WEB / "public" / "og-image.png"
FONTS = WEB / "node_modules" / "@fontsource"
BRICOLAGE = (
    WEB / "node_modules/@fontsource-variable/bricolage-grotesque/files"
    "/bricolage-grotesque-latin-wght-normal.woff2"
)
PLEX = FONTS / "ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2"
PLEX_MONO = FONTS / "ibm-plex-mono/files/ibm-plex-mono-latin-500-normal.woff2"

HEADLINE = "The office jukebox"
# The same words as the page's description, so a preview and the page agree.
TEXT = "Pick what plays in the office. Request songs, vote on the queue, and hear your name on air."


def logo() -> str:
    """The orange GuildFM mark from the favicon, without its square, filling its box."""
    favicon = (WEB / "public" / "favicon.svg").read_text()
    mark = favicon[favicon.index("<svg", 1) : favicon.rindex("</svg>")]
    return re.sub(
        r'x="[^"]*" y="[^"]*" width="[^"]*" height="[^"]*"', 'width="100%"', mark, count=1
    )


def dial() -> str:
    """A tuner's scale along the bottom, 88 to 108, with the needle on air."""
    labels = "".join(f'<span style="left: {120 + i * 192}px">{88 + i * 4}</span>' for i in range(6))
    return f'<div class="scale"></div><div class="labels">{labels}</div><div class="needle"></div>'


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Bricolage; src: url("{bricolage}"); font-weight: 200 800; }}
@font-face {{ font-family: Plex; src: url("{plex}"); }}
@font-face {{ font-family: PlexMono; src: url("{plex_mono}"); }}
html, body {{ margin: 0; width: 1200px; height: 630px; }}
body {{
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(640px 420px at 82% 88%, rgba(255, 138, 61, 0.2), transparent 70%),
    radial-gradient(900px 600px at 10% 0%, #29201c, transparent 70%),
    #1c1512;
  color: #f3f1ea;
  font-family: Plex, sans-serif;
}}
.logo {{ position: absolute; left: 88px; top: 72px; width: 380px; }}
.logo svg {{ display: block; }}
h1 {{
  position: absolute; left: 88px; top: 296px; margin: 0;
  font-family: Bricolage, sans-serif; font-weight: 750; font-size: 64px; letter-spacing: -0.02em;
}}
p {{
  position: absolute; left: 88px; top: 384px; width: 860px; margin: 0;
  font-size: 28px; line-height: 1.4; color: #b8ab9f;
}}
.scale {{
  position: absolute; left: 88px; right: 88px; bottom: 58px; height: 34px;
  background:
    repeating-linear-gradient(90deg, #6b5a50 0 3px, transparent 3px 192px) 32px 0 / 100% 34px
      no-repeat,
    repeating-linear-gradient(90deg, #413530 0 2px, transparent 2px 24px) 32px 16px / 100% 18px
      no-repeat;
  border-bottom: 2px solid #413530;
}}
.labels span {{
  position: absolute; bottom: 18px; transform: translateX(-50%);
  font-family: PlexMono, monospace; font-size: 18px; color: #6b5a50;
}}
.needle {{
  position: absolute; left: 868px; bottom: 40px; width: 5px; height: 92px; border-radius: 3px;
  background: #ff8a3d; box-shadow: 0 0 18px rgba(255, 138, 61, 0.9);
}}
</style></head><body>
<div class="logo">{logo}</div>
<h1>{headline}</h1>
<p>{text}</p>
{dial}
</body></html>
"""


async def draw() -> None:
    page_html = PAGE.format(
        bricolage=BRICOLAGE.as_uri(),
        plex=PLEX.as_uri(),
        plex_mono=PLEX_MONO.as_uri(),
        logo=logo(),
        headline=HEADLINE,
        text=TEXT,
        dial=dial(),
    )
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "card.html"
        source.write_text(page_html)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=chromium())
            page = await browser.new_page(viewport={"width": 1200, "height": 630})
            await page.goto(source.as_uri())
            await page.evaluate("document.fonts.ready")
            await page.screenshot(path=OUT)
            await browser.close()
    print(f"Drew {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(draw())
