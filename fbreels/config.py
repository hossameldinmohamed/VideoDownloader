import json
import threading
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_DIR / ".fbreels"
SETTINGS_FILE = STATE_DIR / "settings.json"
JOBS_FILE = STATE_DIR / "jobs.json"

DEFAULT_OPTIONS = {
    "quality": "best",        # best | 2160 | 1440 | 1080 | 720 | 480 | 360
    "format": "mp4",          # mp4 (plays everywhere) | original | mp3 | m4a
    "tabs": ["videos"],       # youtube channel tabs: videos, shorts, streams
    "naming": "number_title", # number_title | number | title
    "limit": None,            # only the N newest videos
    "subtitles": False,
    "sub_langs": "en.*",
    "auto_subs": False,
    "embed_thumbnail": True,
    "embed_metadata": True,
    "workers": 3,
    "cookies_browser": "",    # "", chrome, safari, firefox, edge, brave
    "rate_limit": "",         # e.g. "5M" to cap bandwidth per download
}

DEFAULT_SETTINGS = {
    "output_dir": str(PROJECT_DIR / "downloads"),
    "options": DEFAULT_OPTIONS,
    "open_browser": True,
    "port": 8787,
}

_lock = threading.Lock()


def load_settings() -> dict:
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    merged = {**DEFAULT_SETTINGS, **data}
    merged["options"] = {**DEFAULT_OPTIONS, **(data.get("options") or {})}
    return merged


def save_settings(settings: dict) -> dict:
    merged = {**load_settings(), **settings}
    merged["options"] = {**DEFAULT_OPTIONS, **(settings.get("options") or merged["options"])}
    with _lock:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(merged, indent=2))
    return merged


def normalize_options(options: dict | None) -> dict:
    opts = {**load_settings()["options"], **(options or {})}
    try:
        opts["workers"] = max(1, min(16, int(opts.get("workers") or 3)))
    except (TypeError, ValueError):
        opts["workers"] = 3
    try:
        limit = int(opts.get("limit") or 0)
        opts["limit"] = limit if limit > 0 else None
    except (TypeError, ValueError):
        opts["limit"] = None
    tabs = [t for t in (opts.get("tabs") or []) if t in ("videos", "shorts", "streams")]
    opts["tabs"] = tabs or ["videos"]
    if opts.get("quality") not in ("best", "2160", "1440", "1080", "720", "480", "360"):
        opts["quality"] = "best"
    if opts.get("format") not in ("mp4", "original", "mp3", "m4a"):
        opts["format"] = "mp4"
    if opts.get("naming") not in ("number_title", "number", "title"):
        opts["naming"] = "number_title"
    if opts.get("cookies_browser") not in ("", "chrome", "safari", "firefox", "edge", "brave", "chromium", "opera", "vivaldi"):
        opts["cookies_browser"] = ""
    return opts
