"""Pages, channels and videos looked up before, so the input can suggest them
again from a few typed letters. Kept on this computer, shared by every device."""

import json
import threading
import time

from . import config

MAX_RECENT = 100
_lock = threading.Lock()


def _file():
    return config.STATE_DIR / "recent.json"


def load() -> list[dict]:
    if not _file().exists():
        return _from_job_history()
    try:
        data = json.loads(_file().read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _from_job_history() -> list[dict]:
    """Before the first lookup is remembered, start from the queue's history."""
    try:
        jobs = json.loads((config.STATE_DIR / "jobs.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []
    entries, seen = [], set()
    for j in sorted(jobs if isinstance(jobs, list) else [], key=lambda j: j.get("created") or 0, reverse=True):
        url = (j.get("target") or {}).get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        entries.append({"url": url, "input": j.get("input") or url, "platform": j.get("platform"),
                        "kind": j.get("kind"), "title": j.get("title") or j.get("input") or url,
                        "avatar": j.get("avatar"), "used": j.get("created")})
    return entries[:MAX_RECENT]


def _save(entries):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(entries, indent=1))


def remember(input_text: str, platform: str, kind: str, url: str, title: str | None = None, avatar: str | None = None):
    """Move this target to the top of the list (one entry per URL)."""
    with _lock:
        entries = load()
        old = next((e for e in entries if e.get("url") == url), {})
        entry = {"url": url, "input": input_text.strip(), "platform": platform, "kind": kind,
                 "title": title or old.get("title") or input_text.strip(),
                 "avatar": avatar or old.get("avatar"), "used": time.time()}
        entries = [entry] + [e for e in entries if e.get("url") != url]
        try:
            _save(entries[:MAX_RECENT])
        except OSError:
            pass  # suggestions are a convenience: never fail a lookup over them


def forget(url: str) -> bool:
    with _lock:
        entries = load()
        kept = [e for e in entries if e.get("url") != url]
        _save(kept)
    return len(kept) != len(entries)
