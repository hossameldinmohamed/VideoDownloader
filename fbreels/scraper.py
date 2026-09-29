import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from .config import STATE_DIR

REEL_URL_RE = re.compile(r"https://www\.facebook\.com/reel/(\d+)")

# Path prefixes that identify a single post/video/reel permalink rather than
# a page's own timeline — these can't be turned into a page's Reels tab.
SINGLE_POST_PATH_RE = re.compile(r"^/(reel|videos|posts|watch|photo\.php|story\.php)(/|$)")

STATE_FILE = STATE_DIR / "state.json"
COOKIES_FILE = STATE_DIR / "cookies.txt"

LOGIN_WAIT_SECONDS = 300
SCROLL_PAUSE_SECONDS = 1.5
MAX_IDLE_SCROLLS = 4


class NotAPageError(Exception):
    """Raised when the given URL resolves to a single post/reel, not a page.
    args[0] is the resolved URL, so callers can download it as one video."""


class Cancelled(Exception):
    pass


def _classify(resolved_url: str):
    """Given a fully-resolved (post-redirect) Facebook URL, return
    (reels_tab_url, fallback_identifier), or raise NotAPageError if it
    points at a single post/reel/video instead of a page's own timeline.
    """
    parsed = urlparse(resolved_url)
    path = parsed.path.rstrip("/") or "/"

    if SINGLE_POST_PATH_RE.match(path):
        raise NotAPageError(resolved_url)

    if path.endswith("profile.php"):
        pid = parse_qs(parsed.query).get("id", [None])[0]
        if not pid:
            raise NotAPageError(resolved_url)
        return f"https://www.facebook.com/{pid}/reels", pid

    segment = path.strip("/").split("/")[0] if path.strip("/") else ""
    if not segment:
        raise NotAPageError(resolved_url)
    base = f"https://www.facebook.com/{segment}"
    target = base if base.endswith("/reels") else f"{base}/reels"
    return target, segment


def _sanitize_name(name: str) -> str:
    if not name:
        return ""
    name = name.replace(" | Facebook", "").strip()
    name = re.sub(r'[\/:*?"<>|\\]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:80]


def _is_logged_in(context) -> bool:
    return any(c["name"] == "c_user" for c in context.cookies())


def has_saved_session() -> bool:
    if not STATE_FILE.exists():
        return False
    try:
        cookies = json.loads(STATE_FILE.read_text()).get("cookies", [])
    except (OSError, json.JSONDecodeError):
        return False
    return any(c.get("name") == "c_user" for c in cookies)


def logout() -> None:
    for f in (STATE_FILE, COOKIES_FILE):
        if f.exists():
            f.unlink()


def ensure_logged_in(on_status=print) -> None:
    """Make sure we have a saved, working Facebook session before scraping."""
    if STATE_FILE.exists():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(STATE_FILE))
            page = context.new_page()
            page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
            logged_in = _is_logged_in(context)
            browser.close()
            if logged_in:
                return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
        on_status(
            "A Facebook login window has opened. Log in there — this continues "
            f"automatically once you're signed in (waiting up to {LOGIN_WAIT_SECONDS // 60} minutes)."
        )

        deadline = time.time() + LOGIN_WAIT_SECONDS
        while time.time() < deadline:
            if _is_logged_in(context):
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(STATE_FILE))
                browser.close()
                on_status("Login detected — session saved. Future runs will be headless and faster.")
                return
            time.sleep(1)

        browser.close()
        raise TimeoutError("Timed out waiting for Facebook login. Run the tool again to retry.")


def export_cookies_txt() -> Path:
    """Convert the saved Playwright session into a Netscape cookies.txt for yt-dlp."""
    data = json.loads(STATE_FILE.read_text())
    lines = ["# Netscape HTTP Cookie File"]
    for c in data.get("cookies", []):
        domain = c.get("domain", "")
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        expires = c.get("expires", -1)
        expiry = str(int(expires)) if expires and expires > 0 else "0"
        lines.append(
            "\t".join(
                [
                    domain,
                    include_sub,
                    c.get("path", "/"),
                    "TRUE" if c.get("secure") else "FALSE",
                    expiry,
                    c.get("name", ""),
                    c.get("value", ""),
                ]
            )
        )
    COOKIES_FILE.write_text("\n".join(lines) + "\n")
    return COOKIES_FILE


def collect_reel_urls(page_url: str, limit=None, headless: bool = True, on_status=print, cancel=None):
    """Return (page_name, [reel_urls]) for every reel found on the page's Reels tab.

    reel_urls preserves the order Facebook displays them in (newest first).
    `cancel` is an optional callable returning True to stop scrolling early.
    """
    ensure_logged_in(on_status)

    seen = set()
    ordered = []
    page_name = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(STATE_FILE))
        page = context.new_page()

        # Navigate to whatever URL we were given first (a page slug, a
        # profile.php link, or a share/short link) and see where Facebook
        # actually takes us before deciding how to reach the Reels tab.
        page.goto(page_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        try:
            target, fallback_identifier = _classify(page.url)
        except NotAPageError:
            browser.close()
            raise

        if page.url.rstrip("/") != target.rstrip("/"):
            page.goto(target, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

        page_name = page.evaluate(
            """() => {
                const og = document.querySelector('meta[property="og:title"]');
                if (og && og.content) return og.content;
                return document.title || "";
            }"""
        )

        def collect_visible():
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            gained = 0
            for href in hrefs:
                m = REEL_URL_RE.match(href.split("?")[0])
                if m:
                    url = f"https://www.facebook.com/reel/{m.group(1)}"
                    if url not in seen:
                        seen.add(url)
                        ordered.append(url)
                        gained += 1
            return gained

        collect_visible()
        idle_rounds = 0
        while not (limit and len(ordered) >= limit):
            if cancel and cancel():
                browser.close()
                raise Cancelled()
            page.mouse.wheel(0, 20000)
            page.wait_for_timeout(int(SCROLL_PAUSE_SECONDS * 1000))
            gained = collect_visible()
            if gained:
                on_status(f"Scrolling the Reels tab… {len(ordered)} reels found so far")
            idle_rounds = 0 if gained else idle_rounds + 1
            if idle_rounds >= MAX_IDLE_SCROLLS:
                break

        browser.close()

    urls = ordered[:limit] if limit else ordered
    name = _sanitize_name(page_name) or fallback_identifier
    return name, urls
