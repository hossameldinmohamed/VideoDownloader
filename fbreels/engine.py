"""Scanning and downloading, shared by the CLI and the web app.

A *scan* turns a resolved Target into groups of items (a channel's Videos
tab, its Shorts tab, a playlist, one video...). Each group maps to one
folder. *prepare_items* assigns every item its stable number in that folder,
and *run_items* downloads them in parallel, reporting progress through a
Reporter so the caller can print it or push it to the UI.
"""

import concurrent.futures
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import yt_dlp
from yt_dlp.postprocessor import (
    EmbedThumbnailPP,
    FFmpegEmbedSubtitlePP,
    FFmpegExtractAudioPP,
    FFmpegMetadataPP,
    FFmpegThumbnailsConvertorPP,
    PostProcessor,
)

from .resolver import Target

AUDIO_FORMATS = ("mp3", "m4a")
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov")
AUDIO_EXTS = (".mp3", ".m4a")
PARTIAL_SUFFIXES = (".part", ".ytdl", ".converting.mp4", ".temp.mp4")
UNAVAILABLE_TITLES = {"[private video]", "[deleted video]", "[unavailable video]"}
TAB_ORDER = ["videos", "shorts", "streams", "podcasts", "playlists", "releases", "courses"]
TAB_LABELS = {"videos": "Videos", "shorts": "Shorts", "streams": "Live", "podcasts": "Podcasts",
              "playlists": "Playlists", "releases": "Releases", "courses": "Courses"}
COLLECTION_TABS = {"podcasts", "playlists", "releases", "courses"}

_archive_lock = threading.Lock()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class Cancelled(Exception):
    pass


class Reporter:
    """Default reporter: prints to the console. The web app subclasses it."""

    def status(self, message: str) -> None:
        print(message)

    def update(self, item: dict, **fields) -> None:
        item.update(fields)

    def cancelled(self) -> bool:
        return False


# --------------------------------------------------------------------------
# helpers


def sanitize_folder(name: str) -> str:
    name = (name or "").replace(" | Facebook", "")
    name = re.sub(r'[\/:*?"<>|\\]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:80] or "Untitled"


def _js_runtimes() -> dict:
    # YouTube needs a JS runtime to unlock every format; yt-dlp only looks for
    # deno by default, so point it at node/bun too if that's what's installed.
    return {rt: {} for rt in ("deno", "node", "bun") if shutil.which(rt)}


class _QuietLogger:
    def debug(self, msg):
        pass

    info = warning = error = debug


def base_opts(options: dict | None = None, platform: str = "youtube", cookiefile=None) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _QuietLogger()}
    runtimes = _js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    browser = (options or {}).get("cookies_browser")
    if browser and platform == "youtube":
        opts["cookiesfrombrowser"] = (browser,)
    elif cookiefile:
        opts["cookiefile"] = str(cookiefile)
    return opts


def clean_error(e: Exception) -> str:
    msg = _ANSI_RE.sub("", str(e)).replace("ERROR: ", "").strip()
    low = msg.lower()
    if "not a bot" in low or "sign in to confirm" in low:
        msg += " — YouTube wants proof you're human: pick your browser under Options → Browser cookies (be logged in to YouTube there)."
    elif "members-only" in low or "join this channel" in low:
        msg += " — members-only video: set Browser cookies to a browser logged in with a member account."
    elif "age" in low and ("restricted" in low or "confirm your age" in low):
        msg += " — age-restricted: set Browser cookies to a browser logged in to YouTube."
    elif "ffmpeg" in low and "not found" in low:
        msg += " — install ffmpeg (brew install ffmpeg)."
    return msg[:600]


@functools.lru_cache(maxsize=1)
def h264_encoder() -> str:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except OSError:
        return "libx264"
    if sys.platform == "darwin" and "h264_videotoolbox" in out:
        return "h264_videotoolbox"
    return "libx264"


def _thumb(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def _avatar(info: dict):
    thumbs = info.get("thumbnails") or []
    for t in reversed(thumbs):
        if "avatar" in str(t.get("id", "")):
            return t.get("url")
    return None


# --------------------------------------------------------------------------
# scanning
#
# lookup()      → what is this? (a channel and which tabs it has, a playlist,
#                 a video, a Facebook page) — fast, no full listing.
# load_group()  → list one tab / playlist on demand; cached on the lookup.
# scan()        → lookup + load the requested tabs in one go (CLI, bulk jobs).


def _entry_thumb(entry: dict, vertical: bool = False):
    thumbs = [t for t in (entry.get("thumbnails") or []) if t.get("url")]
    if vertical and thumbs:
        # Shorts come with portrait thumbnails; pick a reasonably small one.
        sized = sorted(thumbs, key=lambda t: abs((t.get("width") or 0) - 360))
        return sized[0]["url"]
    if entry.get("id") and not entry.get("ie_key") == "YoutubeTab":
        return _thumb(entry["id"])
    return thumbs[-1]["url"] if thumbs else None


def _yt_entries(info: dict, vertical: bool = False):
    seen = set()
    for entry in info.get("entries") or []:
        if not entry or entry.get("_type") == "playlist" or entry.get("ie_key") == "YoutubeTab":
            continue
        vid = entry.get("id")
        title = entry.get("title") or vid
        if not vid or vid in seen or str(title).lower() in UNAVAILABLE_TITLES:
            continue
        seen.add(vid)
        live = entry.get("live_status")
        yield {
            "key": vid,
            "archive": f"youtube {vid}",
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": title,
            "thumbnail": _entry_thumb(entry, vertical),
            "duration": entry.get("duration"),
            "views": entry.get("view_count"),
            "unavailable": {"is_live": "Live now", "is_upcoming": "Upcoming"}.get(live),
        }


def _yt_collections(info: dict):
    """Entries of a Playlists/Podcasts/Releases/Courses tab — each one is a
    playlist the user can open."""
    seen = set()
    for entry in info.get("entries") or []:
        if not entry:
            continue
        pid = entry.get("id")
        url = entry.get("url") or ""
        if not pid and "list=" in url:
            pid = url.split("list=", 1)[1].split("&", 1)[0]
        if not pid or pid in seen:
            continue
        seen.add(pid)
        yield {
            "key": pid,
            "title": entry.get("title") or pid,
            "thumbnail": _entry_thumb(entry),
            "count": entry.get("playlist_count"),
        }


def _flat(options, **extra) -> dict:
    return {**base_opts(options), "extract_flat": "in_playlist", **extra}


def _probe_tab(base_url: str, tab: str, options: dict):
    try:
        with yt_dlp.YoutubeDL(_flat(options, playlistend=1)) as ydl:
            return tab, ydl.extract_info(f"{base_url}/{tab}", download=False)
    except Exception:
        return tab, None  # "This channel does not have a ... tab"


def _video_group(key, label, folder, items, *, kind="videos", single=False, limit_from="end", chrono="oldest_first"):
    return {"key": key, "label": label, "type": kind, "folder": folder, "single": single,
            "limit_from": limit_from, "chrono": chrono, "items": items}


def lookup(target: Target, options: dict, reporter: Reporter | None = None) -> dict:
    reporter = reporter or Reporter()
    lk = {"platform": target.platform, "kind": target.kind, "url": target.url, "title": target.label,
          "avatar": None, "subtitle": None, "subscribers": None, "count": None, "tabs": [], "default_tab": None,
          "folder": None, "playlist": target.playlist or None, "groups": {}, "target": target.to_dict()}

    if target.platform == "facebook":
        if target.kind == "video":
            g = _scan_facebook_video(target.url, options)
            lk.update(title=g["folder"][0], folder=g["folder"])
            lk["groups"]["video"] = g
            lk["tabs"] = [{"key": "video", "label": "Video", "type": "videos"}]
        else:
            lk["tabs"] = [{"key": "reels", "label": "Reels", "type": "videos"}]
        lk["default_tab"] = lk["tabs"][0]["key"]
        return lk

    if target.kind == "video":
        with yt_dlp.YoutubeDL(base_opts(options)) as ydl:
            info = ydl.extract_info(target.url, download=False, process=False)
        channel = info.get("channel") or info.get("uploader") or "YouTube"
        vid = info.get("id")
        folder = [sanitize_folder(channel)]
        item = {"key": vid, "archive": f"youtube {vid}", "url": target.url, "title": info.get("title") or vid,
                "thumbnail": _thumb(vid), "duration": info.get("duration"), "views": info.get("view_count"),
                "unavailable": {"is_live": "Live now", "is_upcoming": "Upcoming"}.get(info.get("live_status"))}
        lk.update(title=channel, folder=folder, default_tab="video",
                  tabs=[{"key": "video", "label": "Video", "type": "videos"}])
        lk["groups"]["video"] = _video_group("video", "Video", folder, [item], single=True, chrono=None)
        return lk

    if target.kind == "playlist":
        with yt_dlp.YoutubeDL(_flat(options)) as ydl:
            info = ydl.extract_info(target.url, download=False)
        title = info.get("title") or "Playlist"
        owner = info.get("channel") or info.get("uploader")
        # Same place as when it's opened from the channel's Playlists tab, so
        # "already downloaded" matches no matter how you got there.
        folder = [sanitize_folder(owner), "Playlists", sanitize_folder(title)] if owner else [sanitize_folder(title)]
        items = list(_yt_entries(info))
        lk.update(title=title, subtitle=f"Playlist by {owner}" if owner else "Playlist", folder=folder, count=len(items),
                  default_tab="playlist", tabs=[{"key": "playlist", "label": "Playlist", "type": "videos"}])
        lk["groups"]["playlist"] = _video_group("playlist", title, folder, items, limit_from="start", chrono=None)
        return lk

    # A channel: find out which tabs it actually has, all at once.
    reporter.status("Looking up the channel…")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(TAB_ORDER)) as pool:
        probes = dict(pool.map(lambda t: _probe_tab(target.url, t, options), TAB_ORDER))
    found = [t for t in TAB_ORDER if probes.get(t)]
    if not found:
        raise RuntimeError("Couldn't find that channel — check the link or handle.")
    info = probes.get("videos") or probes[found[0]]
    channel = info.get("channel") or info.get("uploader") or (info.get("title") or "").rsplit(" - ", 1)[0] or target.label
    lk.update(
        title=channel,
        avatar=next((_avatar(p) for p in probes.values() if p and _avatar(p)), None),
        subscribers=info.get("channel_follower_count"),
        folder=[sanitize_folder(channel)],
        tabs=[{"key": t, "label": TAB_LABELS[t], "type": "collections" if t in COLLECTION_TABS else "videos"} for t in found],
    )
    lk["default_tab"] = target.tab if target.tab in found else found[0]
    return lk


def load_group(lk: dict, key: str, options: dict, reporter: Reporter | None = None, headless: bool = True) -> dict:
    """List one tab (or one playlist inside a Playlists/Podcasts tab)."""
    reporter = reporter or Reporter()
    if key in lk["groups"]:
        return lk["groups"][key]

    if lk["platform"] == "facebook":
        if key != "reels":
            raise KeyError(key)
        g = _scan_facebook_page(lk["url"], options, reporter, headless)
        if g.get("redirect_video"):
            # A share link that landed on a single reel/video.
            g = _scan_facebook_video(g["redirect_video"], options)
        lk.update(title=g["folder"][0], folder=g["folder"])
        lk["groups"][key] = g
        return g

    if lk["kind"] != "channel":
        raise KeyError(key)

    if key.startswith("pl:"):
        _, parent, pid = key.split(":", 2)
        with yt_dlp.YoutubeDL(_flat(options)) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/playlist?list={pid}", download=False)
        title = info.get("title") or pid
        folder = lk["folder"] + [TAB_LABELS.get(parent, "Playlists"), sanitize_folder(title)]
        g = _video_group(key, title, folder, list(_yt_entries(info)), limit_from="start", chrono=None)
        g["parent"] = parent
    elif key in COLLECTION_TABS:
        reporter.status(f"Listing {TAB_LABELS[key].lower()}…")
        with yt_dlp.YoutubeDL(_flat(options)) as ydl:
            info = ydl.extract_info(f"{lk['url']}/{key}", download=False)
        g = {"key": key, "label": TAB_LABELS[key], "type": "collections", "items": list(_yt_collections(info))}
    elif key in TAB_LABELS:
        reporter.status(f"Listing {TAB_LABELS[key].lower()}…")
        with yt_dlp.YoutubeDL(_flat(options)) as ydl:
            info = ydl.extract_info(f"{lk['url']}/{key}", download=False)
        items = list(_yt_entries(info, vertical=key == "shorts"))
        items.reverse()  # oldest first → #1 is the first upload, new uploads append
        folder = lk["folder"] + ([] if key == "videos" else [TAB_LABELS[key]])
        g = _video_group(key, TAB_LABELS[key], folder, items, kind="shorts" if key == "shorts" else "videos")
    else:
        raise KeyError(key)

    lk["groups"][key] = g
    return g


_fb_cookie_lock = threading.Lock()


def _fb_cookiefile():
    from . import scraper

    # Several detail lookups run at once; don't let one read a half-written file.
    with _fb_cookie_lock:
        return scraper.export_cookies_txt() if scraper.has_saved_session() else None


def _scan_facebook_video(url: str, options: dict) -> dict:
    with yt_dlp.YoutubeDL(base_opts(options, "facebook", _fb_cookiefile())) as ydl:
        info = ydl.extract_info(url, download=False)
    uploader = info.get("uploader") or info.get("channel") or "Facebook"
    vid = info.get("id") or url
    item = {"key": url, "archive": f"facebook {vid}", "url": url,
            "title": info.get("title") or f"Facebook video {vid}",
            "thumbnail": info.get("thumbnail"), "duration": info.get("duration"), "views": info.get("view_count"),
            "unavailable": None}
    return _video_group("video", "Video", [sanitize_folder(uploader)], [item], single=True, limit_from="start", chrono=None)


def _scan_facebook_page(url: str, options: dict, reporter: Reporter, headless: bool = True) -> dict:
    from . import scraper

    reporter.status("Opening the page's Reels tab…")
    try:
        name, reels = scraper.collect_reels(
            url, limit=options.get("limit"), headless=headless,
            on_status=reporter.status, cancel=reporter.cancelled,
        )
    except scraper.NotAPageError as e:
        return {"redirect_video": str(e)}
    except scraper.Cancelled:
        raise Cancelled() from None

    items = []
    for reel in reels:
        u = reel["url"]
        rid = u.rstrip("/").rsplit("/", 1)[-1]
        items.append({"key": u, "archive": f"facebook {rid}", "url": u, "title": f"Reel {rid}",
                      "thumbnail": reel["thumbnail"], "duration": None, "views": reel["views"],
                      "unavailable": None})
    # Facebook lists newest first; numbers are handed out in that order.
    return _video_group("reels", "Reels", [sanitize_folder(name)], items, kind="shorts",
                        limit_from="start", chrono="newest_first")


def scan(target: Target, options: dict, reporter: Reporter | None = None, headless: bool = True) -> dict:
    """Look up the target and list the tabs asked for in options["tabs"]."""
    reporter = reporter or Reporter()
    lk = lookup(target, options, reporter)
    if lk["kind"] == "channel":
        available = {t["key"] for t in lk["tabs"] if t["type"] == "videos"}
        wanted = [target.tab] if target.tab else options["tabs"]
        keys = [t for t in wanted if t in available]
        if not keys:
            raise RuntimeError(f"That channel has no {', '.join(TAB_LABELS.get(t, t) for t in wanted)} tab.")
    else:
        keys = [lk["tabs"][0]["key"]]
    groups = []
    for key in keys:
        if reporter.cancelled():
            raise Cancelled()
        groups.append(load_group(lk, key, options, reporter, headless))
    return lookup_result(lk, groups)


def lookup_result(lk: dict, groups: list) -> dict:
    return {"platform": lk["platform"], "kind": lk["kind"], "title": lk["title"], "avatar": lk["avatar"],
            "subtitle": lk.get("subtitle"), "groups": groups, "target": lk["target"]}


# --------------------------------------------------------------------------
# numbering


def _manifest_order(manifest_path: Path) -> list:
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text())
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []
    return []


def assign_indices(keys, manifest_path: Path, write: bool = True) -> dict:
    """Stable numbering per folder: numbers handed out in earlier runs are
    kept, new keys get the next free numbers in the order given."""
    order = _manifest_order(manifest_path)
    known = set(order)
    for key in keys:
        if key not in known:
            order.append(key)
            known.add(key)
    if write:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(order))
    return {key: i + 1 for i, key in enumerate(order)}


def _archive_name(options: dict) -> str:
    return ".downloaded-audio.txt" if options["format"] in AUDIO_FORMATS else ".downloaded.txt"


def _load_archive(path: Path) -> set:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def _numbered_file_exists(out_dir: Path, index: int, exts) -> bool:
    if not out_dir.exists():
        return False
    pat = re.compile(rf"^0*{index}( - |\.)")
    for name in os.listdir(out_dir):
        if pat.match(name) and name.lower().endswith(exts) and not name.endswith(PARTIAL_SUFFIXES):
            return True
    return False


def _group_selection(selected, group_key):
    """selected is None (everything), a set of keys, or {group_key: keys}."""
    if selected is None:
        return None
    if isinstance(selected, dict):
        return set(selected.get(group_key) or [])
    return set(selected)


def _select(group: dict, options: dict, chosen_keys) -> list:
    items = [i for i in group["items"] if not i.get("unavailable")]
    if chosen_keys is not None:
        return [i for i in items if i["key"] in chosen_keys]  # hand-picked: no limit
    limit = options.get("limit")
    if limit and not group.get("single"):
        items = items[-limit:] if group["limit_from"] == "end" else items[:limit]
    return items


def downloaded_keys(root: Path, options: dict) -> set:
    """Every archive entry anywhere under a channel/page folder, so a video
    already saved from the Videos tab shows as downloaded inside a playlist."""
    name = _archive_name(options)
    found = set()
    if root.exists():
        for archive in root.rglob(name):
            found |= _load_archive(archive)
    return found


def annotate_group(group: dict, options: dict, output_dir: str) -> dict:
    """Add number / downloaded flags for the picker, without touching disk."""
    if group.get("type") == "collections":
        return {k: v for k, v in group.items()}
    folder = Path(output_dir).joinpath(*group["folder"])
    nums = {} if group.get("single") else assign_indices(
        [i["key"] for i in group["items"]], folder / ".manifest.json", write=False)
    archived = downloaded_keys(Path(output_dir) / group["folder"][0], options)
    exts = AUDIO_EXTS if options["format"] in AUDIO_FORMATS else VIDEO_EXTS
    items = []
    for it in group["items"]:
        n = nums.get(it["key"])
        got = it["archive"] in archived or (n is not None and _numbered_file_exists(folder, n, exts))
        items.append({**it, "number": n, "downloaded": got})
    return {**group, "folder": str(folder), "items": items}


def preview_numbers(scan_result: dict, output_dir: str) -> dict:
    """{group_key: {item_key: number}} without touching the disk."""
    out = {}
    for g in scan_result["groups"]:
        if g.get("single"):
            continue
        folder = Path(output_dir).joinpath(*g["folder"])
        out[g["key"]] = assign_indices([i["key"] for i in g["items"]], folder / ".manifest.json", write=False)
    return out


def prepare_items(scan_result: dict, options: dict, output_dir: str, selected=None) -> list:
    """Flatten a scan into downloadable items with numbers, folders and
    already-downloaded detection. Writes each folder's manifest.

    Hand-picked videos (selected) are always attempted, even if they were
    downloaded before — yt-dlp still won't redo a file that's already there."""
    audio = options["format"] in AUDIO_FORMATS
    exts = AUDIO_EXTS if audio else VIDEO_EXTS
    items = []
    for g in scan_result["groups"]:
        if g.get("type") == "collections":
            continue
        folder = Path(output_dir).joinpath(*g["folder"])
        picked = _group_selection(selected, g["key"])
        chosen = _select(g, options, picked)
        if not chosen:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        archive_path = folder / _archive_name(options)
        archived = _load_archive(archive_path)
        indices = {} if g.get("single") else assign_indices([i["key"] for i in g["items"]], folder / ".manifest.json")
        width = max(3, len(str(max(indices.values(), default=0))))
        platform = scan_result["platform"]
        for it in chosen:
            index = indices.get(it["key"])
            done = picked is None and (
                it["archive"] in archived or (index is not None and _numbered_file_exists(folder, index, exts)))
            items.append({
                **{k: v for k, v in it.items() if k not in ("number", "downloaded")},
                "group": g["key"],
                "platform": platform,
                "index": index,
                "prefix": f"{index:0{width}d}" if index is not None else "",
                "out_dir": str(folder),
                "archive_path": str(archive_path),
                "status": "skipped" if done else "queued",
                "progress": 1.0 if done else 0.0,
                "speed": None, "eta": None, "error": None, "file": None, "phase": "",
            })
    return items


# --------------------------------------------------------------------------
# conversion to an mp4 that plays everywhere

PLAYABLE_VIDEO = {"h264"}
PLAYABLE_AUDIO = {"aac", "mp3"}


def probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type,codec_name,height:stream_disposition=attached_pic:format=duration",
         "-of", "json", path],
        capture_output=True, text=True,
    ).stdout
    data = json.loads(out or "{}")
    video = audio = None
    height = 0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic") and video is None:
            video, height = s.get("codec_name"), s.get("height") or 0
        elif s.get("codec_type") == "audio" and audio is None:
            audio = s.get("codec_name")
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return {"video": video, "audio": audio, "height": height, "duration": duration}


def _video_bitrate(height: int) -> str:
    for min_h, rate in ((4320, "90M"), (2160, "45M"), (1440, "20M"), (1080, "10M"), (720, "6M")):
        if height >= min_h:
            return rate
    return "3M"


def ensure_playable_mp4(path: str, on_progress=None, cancelled=None) -> bool:
    """Re-encode to H.264/AAC in place if the file uses VP9/AV1/Opus, so the
    .mp4 plays in QuickTime, on phones, TVs and Windows. Returns True if it
    had to convert."""
    info = probe(path)
    video, audio = info["video"], info["audio"]
    if (video is None or video in PLAYABLE_VIDEO) and (audio is None or audio in PLAYABLE_AUDIO):
        return False

    tmp = path + ".converting.mp4"

    def build(encoder):
        cmd = ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", path,
               "-map", "0:v:0?", "-map", "0:a?", "-map_metadata", "0"]
        if video in PLAYABLE_VIDEO or video is None:
            cmd += ["-c:v", "copy"]
        elif encoder == "h264_videotoolbox":
            rate = _video_bitrate(info["height"])
            cmd += ["-c:v", "h264_videotoolbox", "-b:v", rate, "-maxrate", rate, "-pix_fmt", "yuv420p", "-profile:v", "high"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "copy"] if audio in PLAYABLE_AUDIO else ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-movflags", "+faststart", tmp]
        return cmd

    def run(cmd):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if cancelled and cancelled():
                proc.kill()
                proc.wait()
                raise Cancelled() from None
            if line.startswith("out_time_us=") and on_progress and info["duration"]:
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000
                    on_progress(max(0.0, min(1.0, done / info["duration"])))
                except ValueError:
                    pass
        stderr = proc.stderr.read()
        return proc.wait(), stderr

    try:
        encoder = h264_encoder()
        code, err = run(build(encoder))
        if code != 0 and encoder != "libx264":
            code, err = run(build("libx264"))  # hardware encoder unavailable
        if code != 0:
            raise RuntimeError(f"ffmpeg conversion failed: {err.strip()[-300:]}")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return True


class PlayableMp4PP(PostProcessor):
    """Runs our H.264/AAC conversion inside yt-dlp's pipeline, before
    subtitles/metadata/thumbnail are embedded, so none of those get lost."""

    def __init__(self, downloader, on_progress, cancelled):
        super().__init__(downloader)
        self._on_progress = on_progress
        self._cancelled = cancelled

    def run(self, info):
        path = info.get("filepath")
        if path and os.path.exists(path):
            ensure_playable_mp4(path, self._on_progress, self._cancelled)
        return [], info


# --------------------------------------------------------------------------
# downloading


def _format_opts(options: dict) -> dict:
    fmt = options["format"]
    height = None if options["quality"] == "best" else options["quality"]
    res = f"res:{height}" if height else "res"
    if fmt == "mp3":
        return {"format": "ba/b"}
    if fmt == "m4a":
        return {"format": "ba[ext=m4a]/ba/b"}
    if fmt == "original":
        return {"format": "bv*+ba/b", "format_sort": [res, "fps"], "merge_output_format": "mp4"}
    # Highest resolution first; at equal resolution prefer SDR H.264 + AAC so
    # most videos need no conversion at all.
    return {
        "format": "bv*+ba[ext=m4a]/bv*+ba/b",
        "format_sort": [res, "fps", "hdr:sdr", "vcodec:h264", "acodec:aac"],
        "merge_output_format": "mp4",
    }


def _format_size(f: dict, duration) -> tuple[int | None, bool]:
    """(bytes, exact) for one format; estimated from bitrate when YouTube
    doesn't say."""
    if f.get("filesize"):
        return f["filesize"], True
    if f.get("filesize_approx"):
        return f["filesize_approx"], False
    if f.get("tbr") and duration:
        return int(f["tbr"] * 1000 / 8 * duration), False
    return None, False


def item_details(url: str, platform: str, options: dict) -> dict:
    """Length, title and expected download size of one video with the current
    quality/format options — the same format pick a download would make."""
    cookiefile = _fb_cookiefile() if platform == "facebook" else None
    opts = {**base_opts(options, platform, cookiefile), **_format_opts(options)}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    duration = info.get("duration")
    size, exact = None, True
    for f in info.get("requested_formats") or [info]:
        n, ok = _format_size(f, duration)
        if n is None:
            size, exact = None, False
            break
        size, exact = (size or 0) + n, exact and ok
    # Converting (to MP3, or non-H.264 video to H.264) changes the final size.
    vcodec = str(info.get("vcodec") or "")
    if options["format"] == "mp3" or (options["format"] == "mp4" and vcodec not in ("", "none")
                                      and not vcodec.startswith(("avc", "h264"))):
        exact = False
    return {"duration": duration, "title": info.get("title"), "size": size,
            "size_exact": exact if size else False}


def _outtmpl(item: dict, options: dict) -> str:
    naming = "title" if item["index"] is None else options["naming"]
    if naming == "number":
        name = item["prefix"]
    elif naming == "title":
        name = "%(title).150B"
    else:
        name = f"{item['prefix']} - %(title).150B"
    return os.path.join(item["out_dir"], name + ".%(ext)s")


def _download_one(item: dict, options: dict, reporter: Reporter, fb_cookiefile) -> bool:
    if reporter.cancelled():
        reporter.update(item, status="cancelled")
        return False

    parts = {}

    def progress_hook(d):
        if reporter.cancelled():
            raise yt_dlp.utils.DownloadCancelled()
        if d.get("status") == "downloading":
            fid = (d.get("info_dict") or {}).get("format_id", "")
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            parts[fid] = (d.get("downloaded_bytes") or 0, total)
            got = sum(p[0] for p in parts.values())
            tot = sum(p[1] for p in parts.values())
            reporter.update(
                item, status="downloading", phase="Downloading",
                progress=(got / tot) if tot else 0.0,
                speed=d.get("speed"), eta=d.get("eta"),
            )

    def pp_hook(d):
        if d.get("status") == "started":
            name = d.get("postprocessor", "")
            label = {
                "Merger": "Merging video + audio", "PlayableMp4": "Converting to H.264 MP4",
                "ExtractAudio": "Extracting audio", "EmbedSubtitle": "Embedding subtitles",
                "Metadata": "Adding metadata", "EmbedThumbnail": "Embedding thumbnail",
            }.get(name, "Processing")
            reporter.update(item, status="processing", phase=label, speed=None, eta=None)

    def convert_progress(frac):
        reporter.update(item, status="processing", phase="Converting to H.264 MP4", progress=frac)

    opts = {
        **base_opts(options, item["platform"], fb_cookiefile if item["platform"] == "facebook" else None),
        **_format_opts(options),
        "outtmpl": _outtmpl(item, options),
        "concurrent_fragment_downloads": 4,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [pp_hook],
        "overwrites": False,
        "continuedl": True,
    }
    if options.get("rate_limit"):
        rate = yt_dlp.utils.parse_bytes(str(options["rate_limit"]))
        if rate:
            opts["ratelimit"] = rate
    audio = options["format"] in AUDIO_FORMATS
    if options.get("subtitles") and not audio:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = bool(options.get("auto_subs"))
        opts["subtitleslangs"] = [s.strip() for s in str(options.get("sub_langs") or "en.*").split(",") if s.strip()]
    if options.get("embed_thumbnail"):
        opts["writethumbnail"] = True

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            if options.get("embed_thumbnail"):
                ydl.add_post_processor(FFmpegThumbnailsConvertorPP(ydl, format="jpg"), when="before_dl")
            if audio:
                ydl.add_post_processor(FFmpegExtractAudioPP(ydl, preferredcodec=options["format"], preferredquality="0"))
            elif options["format"] == "mp4":
                ydl.add_post_processor(PlayableMp4PP(ydl, convert_progress, reporter.cancelled))
            if opts.get("writesubtitles"):
                ydl.add_post_processor(FFmpegEmbedSubtitlePP(ydl, already_have_subtitle=False))
            if options.get("embed_metadata"):
                ydl.add_post_processor(FFmpegMetadataPP(ydl, add_metadata=True, add_chapters=True, add_infojson=False))
            if options.get("embed_thumbnail"):
                ydl.add_post_processor(EmbedThumbnailPP(ydl, already_have_thumbnail=False))
            reporter.update(item, status="downloading", phase="Starting", progress=0.0)
            info = ydl.extract_info(item["url"], download=True)
    except (yt_dlp.utils.DownloadCancelled, Cancelled):
        reporter.update(item, status="cancelled", phase="", speed=None, eta=None)
        return False
    except Exception as e:  # DownloadError, ffmpeg failures, network errors...
        reporter.update(item, status="failed", phase="", error=clean_error(e), speed=None, eta=None)
        return False

    path = ((info or {}).get("requested_downloads") or [{}])[0].get("filepath")
    # Only mark as done once the final file is in place, so an interrupted
    # conversion gets retried on the next run.
    with _archive_lock:
        with open(item["archive_path"], "a") as f:
            f.write(item["archive"] + "\n")
    size = os.path.getsize(path) if path and os.path.exists(path) else None
    reporter.update(
        item, status="done", phase="", progress=1.0, speed=None, eta=None,
        file=os.path.basename(path) if path else None, size=size,
    )
    return True


def run_items(items: list, options: dict, reporter: Reporter | None = None) -> dict:
    reporter = reporter or Reporter()
    pending = [i for i in items if i["status"] in ("queued", "failed", "cancelled")]
    fb_cookiefile = _fb_cookiefile() if any(i["platform"] == "facebook" for i in pending) else None
    for i in pending:
        reporter.update(i, status="queued", error=None, progress=0.0, phase="")
    with concurrent.futures.ThreadPoolExecutor(max_workers=options["workers"]) as pool:
        list(pool.map(lambda it: _download_one(it, options, reporter, fb_cookiefile), pending))
    return summarize(items)


def summarize(items: list) -> dict:
    counts = {"total": len(items), "done": 0, "skipped": 0, "failed": 0, "cancelled": 0, "active": 0, "queued": 0}
    for i in items:
        s = i["status"]
        if s in counts:
            counts[s] += 1
        elif s in ("downloading", "processing"):
            counts["active"] += 1
    return counts
