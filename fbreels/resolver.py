"""Turn whatever the user typed — a full link, an @handle, a page name, a
channel/profile id — into a concrete (platform, kind, url) target."""

import re
from dataclasses import asdict, dataclass
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "fb.com", "www.fb.com", "fb.watch"}

YT_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
YT_CHANNEL_PATH_RE = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)(?:/([^/]+))?/?$")
YT_SINGLE_PATH_RE = re.compile(r"^/(shorts|live|embed|v)/([\w-]{11})")
YT_TABS = {"videos", "shorts", "streams"}

FB_SINGLE_PATH_RE = re.compile(r"^/(reel/|videos/|watch|story\.php|photo\.php|[^/]+/videos/\d|[^/]+/posts/)")

HANDLE_RE = re.compile(r"^@?[\w.\-]{2,100}$", re.UNICODE)


class ResolveError(ValueError):
    def __init__(self, message: str, ambiguous: bool = False):
        super().__init__(message)
        self.ambiguous = ambiguous


@dataclass
class Target:
    platform: str  # "youtube" | "facebook"
    kind: str      # "channel" | "playlist" | "video" | "page"
    url: str
    label: str     # human readable, e.g. "@mkbhd" or "YouTube video"
    tab: str = ""  # youtube channel tab explicitly present in the URL
    playlist: str = ""  # a video link that also names a playlist (watch?v=…&list=…)

    def to_dict(self):
        return asdict(self)


def _with_scheme(text: str) -> str:
    return text if re.match(r"^https?://", text, re.I) else "https://" + text


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _looks_like_url(text: str) -> bool:
    return "/" in text or bool(re.search(r"\.(com|be|watch)\b", text, re.I))


def _real_playlist(query) -> str:
    """Playlist id from ?list=, ignoring auto-generated Mixes (RD…) and the
    private Watch later / Liked lists, which can't be listed without login."""
    pid = (query.get("list") or [""])[0]
    return "" if not pid or pid.startswith("RD") or pid in ("WL", "LL") else pid


def _resolve_youtube_url(url: str) -> Target:
    parsed = urlparse(url)
    host = _host(url)
    path = parsed.path or "/"
    query = parse_qs(parsed.query)

    if host.endswith("youtu.be"):
        vid = path.strip("/").split("/")[0]
        if not vid:
            raise ResolveError("That youtu.be link has no video id in it.")
        return Target("youtube", "video", f"https://www.youtube.com/watch?v={vid}", "YouTube video",
                      playlist=_real_playlist(query))

    if path.rstrip("/") == "/watch" and query.get("v"):
        # A watch link that's part of a playlist still means "this video", but
        # remember the playlist so the app can offer to open all of it.
        return Target("youtube", "video", f"https://www.youtube.com/watch?v={query['v'][0]}", "YouTube video",
                      playlist=_real_playlist(query))

    if path.rstrip("/") == "/playlist" and query.get("list"):
        return Target("youtube", "playlist", f"https://www.youtube.com/playlist?list={query['list'][0]}", "YouTube playlist")

    m = YT_SINGLE_PATH_RE.match(path)
    if m:
        return Target("youtube", "video", f"https://www.youtube.com/watch?v={m.group(2)}", "YouTube video")

    m = YT_CHANNEL_PATH_RE.match(path)
    if m:
        base = f"https://www.youtube.com/{m.group(1)}"
        tab = (m.group(2) or "").lower()
        label = m.group(1) if m.group(1).startswith("@") else m.group(1).split("/", 1)[1]
        return Target("youtube", "channel", base, label, tab if tab in YT_TABS else "")

    raise ResolveError("That YouTube link isn't a channel, playlist or video.")


def _resolve_facebook_url(url: str) -> Target:
    parsed = urlparse(url)
    host = _host(url)
    path = parsed.path or "/"

    if host == "fb.watch" or FB_SINGLE_PATH_RE.match(path):
        return Target("facebook", "video", url, "Facebook video")
    if path.startswith("/share/"):
        # Share links can point at a page or a single reel; the scanner
        # follows the redirect and decides.
        return Target("facebook", "page", url, "Facebook share link")
    if path.rstrip("/").endswith("profile.php"):
        pid = parse_qs(parsed.query).get("id", [None])[0]
        if not pid:
            raise ResolveError("That profile.php link has no id in it.")
        return Target("facebook", "page", f"https://www.facebook.com/profile.php?id={pid}", pid)

    segment = path.strip("/").split("/")[0]
    if not segment:
        raise ResolveError("That Facebook link doesn't point to a page.")
    return Target("facebook", "page", f"https://www.facebook.com/{segment}", segment)


def resolve(text: str, platform: str = "auto") -> Target:
    """platform is "auto", "youtube" or "facebook"."""
    text = (text or "").strip().strip("<>").strip()
    if not text:
        raise ResolveError("Paste a link, @handle or page name.")

    if _looks_like_url(text):
        url = _with_scheme(text)
        host = _host(url)
        if host in YOUTUBE_HOSTS:
            return _resolve_youtube_url(url)
        if host in FACEBOOK_HOSTS:
            return _resolve_facebook_url(url)
        raise ResolveError("Only YouTube and Facebook links are supported.")

    if YT_CHANNEL_ID_RE.match(text) and platform in ("auto", "youtube"):
        return Target("youtube", "channel", f"https://www.youtube.com/channel/{text}", text)

    if text.isdigit() and platform in ("auto", "facebook"):
        return Target("facebook", "page", f"https://www.facebook.com/profile.php?id={text}", text)

    if not HANDLE_RE.match(text):
        raise ResolveError("That doesn't look like a link, @handle or page name.")

    name = text.lstrip("@")
    if platform == "youtube" or (platform == "auto" and text.startswith("@")):
        return Target("youtube", "channel", f"https://www.youtube.com/@{name}", f"@{name}")
    if platform == "facebook":
        return Target("facebook", "page", f"https://www.facebook.com/{name}", name)

    raise ResolveError(f"Is “{name}” a YouTube channel or a Facebook page? Pick one.", ambiguous=True)
