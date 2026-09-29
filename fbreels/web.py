"""Local web UI: `python -m fbreels.web` (or ./app.sh) and open the browser."""

import argparse
import glob
import json
import os
import platform as platform_mod
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, engine
from .config import PROJECT_DIR, load_settings, normalize_options, save_settings
from .jobs import JobManager
from .resolver import ResolveError, Target, resolve

STATIC_DIR = Path(__file__).resolve().parent / "static"
RESTART_EXIT_CODE = 3

app = FastAPI(title="fbreels", docs_url=None, redoc_url=None, openapi_url=None)
manager: JobManager | None = None
_allowed_hosts: set[str] = set()


def get_manager() -> JobManager:
    global manager
    if manager is None:
        manager = JobManager()
    return manager


# --------------------------------------------------------------------------
# security: this server can run downloads and open folders, so only accept
# requests addressed to localhost (blocks DNS rebinding) and require a
# custom header on writes (browsers won't send it cross-site without a CORS
# preflight, which we never approve).


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = (request.headers.get("host") or "").lower()
    if _allowed_hosts and host not in _allowed_hosts:
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-fbreels") != "1":
        return JSONResponse({"detail": "Missing X-Fbreels header"}, status_code=403)
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# --------------------------------------------------------------------------
# models


class ResolveIn(BaseModel):
    input: str
    platform: str = "auto"


class LookupIn(ResolveIn):
    options: dict | None = None


class GroupIn(BaseModel):
    key: str
    options: dict | None = None


class JobIn(BaseModel):
    inputs: list[str] = []
    platform: str = "auto"
    options: dict | None = None
    output_dir: str | None = None
    lookup_id: str | None = None
    selections: dict[str, list[str]] | None = None  # {tab/playlist key: [video keys]}


class PathIn(BaseModel):
    path: str
    reveal: bool = False


# --------------------------------------------------------------------------
# lookups are cached so the picker can load tabs one at a time and the
# download reuses the listings instead of fetching the channel again.

_lookups: dict[str, dict] = {}
_lookups_lock = threading.Lock()
MAX_LOOKUPS = 12


def _remember_lookup(lk) -> str:
    lid = uuid.uuid4().hex[:12]
    with _lookups_lock:
        _lookups[lid] = {"t": time.time(), "lk": lk, "lock": threading.Lock()}
        for old in sorted(_lookups, key=lambda k: _lookups[k]["t"])[:-MAX_LOOKUPS]:
            _lookups.pop(old, None)
    return lid


def _get_lookup(lid):
    with _lookups_lock:
        entry = _lookups.get(lid)
    if not entry:
        raise HTTPException(410, {"message": "This list expired — press Find videos again."})
    entry["t"] = time.time()
    return entry


def _public_lookup(lid, lk):
    return {"lookup_id": lid, **{k: lk.get(k) for k in (
        "platform", "kind", "title", "avatar", "subtitle", "subscribers", "count", "tabs", "default_tab",
        "playlist", "target")},
        "folder": str(Path(_output_dir()).joinpath(*lk["folder"])) if lk.get("folder") else None,
        "folder_parts": lk.get("folder")}


def _output_dir(value: str | None = None) -> str:
    out = value or load_settings()["output_dir"]
    return str(Path(os.path.expanduser(out)).resolve())


def _resolve_or_400(text, platform) -> Target:
    try:
        return resolve(text, platform)
    except ResolveError as e:
        raise HTTPException(400, {"message": str(e), "ambiguous": e.ambiguous}) from None


# --------------------------------------------------------------------------
# routes: core


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/resolve")
def api_resolve(body: ResolveIn):
    return _resolve_or_400(body.input, body.platform).to_dict()


@app.post("/api/lookup")
def api_lookup(body: LookupIn):
    target = _resolve_or_400(body.input, body.platform)
    options = normalize_options(body.options)
    try:
        lk = engine.lookup(target, options)
    except Exception as e:
        raise HTTPException(422, {"message": engine.clean_error(e)}) from None
    return _public_lookup(_remember_lookup(lk), lk)


@app.post("/api/lookup/{lookup_id}/group")
def api_lookup_group(lookup_id: str, body: GroupIn):
    entry = _get_lookup(lookup_id)
    lk = entry["lk"]
    options = normalize_options(body.options)
    try:
        with entry["lock"]:  # two clicks on the same tab shouldn't list it twice
            group = engine.load_group(lk, body.key, options)
    except KeyError:
        raise HTTPException(404, {"message": "That tab doesn't exist here."}) from None
    except Exception as e:
        raise HTTPException(422, {"message": engine.clean_error(e)}) from None
    return {"group": engine.annotate_group(group, options, _output_dir()),
            "lookup": _public_lookup(lookup_id, lk)}


@app.post("/api/jobs")
def api_create_jobs(body: JobIn):
    m = get_manager()
    out_dir = _output_dir(body.output_dir)
    options = normalize_options(body.options)
    created = []
    if body.lookup_id:
        lk = _get_lookup(body.lookup_id)["lk"]
        picks = {k: v for k, v in (body.selections or {}).items() if v and k in lk["groups"]}
        if not picks:
            raise HTTPException(400, {"message": "Tick at least one video first."})
        groups = [lk["groups"][k] for k in picks]
        result = engine.lookup_result(lk, groups)
        target = Target(**lk["target"])
        label = body.inputs[0] if body.inputs else target.url
        created.append(m.create(label, target, options, out_dir, scan=result, selected=picks))
    else:
        inputs = [i.strip() for i in body.inputs if i and i.strip()]
        if not inputs:
            raise HTTPException(400, {"message": "Paste at least one link, @handle or page name."})
        targets = [(text, _resolve_or_400(text, body.platform)) for text in inputs]
        for text, target in targets:
            created.append(m.create(text, target, options, out_dir))
    return {"jobs": [j.to_dict() for j in created]}


@app.get("/api/jobs")
def api_jobs():
    m = get_manager()
    return {"jobs": m.list(), "current": m.current}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = get_manager().get(job_id)
    if not job:
        raise HTTPException(404, {"message": "No such job."})
    with get_manager().lock:
        return job.to_dict(items="all")


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel(job_id: str):
    return {"ok": get_manager().cancel(job_id)}


@app.post("/api/jobs/{job_id}/retry")
def api_retry(job_id: str):
    return {"ok": get_manager().retry(job_id)}


@app.delete("/api/jobs/{job_id}")
def api_remove(job_id: str):
    return {"ok": get_manager().remove(job_id)}


@app.post("/api/jobs/clear")
def api_clear():
    get_manager().clear_finished()
    return {"ok": True}


# --------------------------------------------------------------------------
# routes: settings, library, files


@app.get("/api/settings")
def api_settings():
    s = load_settings()
    s["output_dir"] = _output_dir(s["output_dir"])
    return s


@app.put("/api/settings")
def api_save_settings(body: dict):
    data = {}
    if "output_dir" in body and body["output_dir"]:
        out = Path(os.path.expanduser(str(body["output_dir"]).strip())).resolve()
        try:
            out.mkdir(parents=True, exist_ok=True)
            probe = out / ".vidstash-write-test"
            probe.write_text("ok")
            probe.unlink()
        except OSError as e:
            if os.environ.get("VERCEL"):
                # this deployment's filesystem is read-only by design — no folder here will ever work
                raise HTTPException(400, {"message": "This hosted preview can't save files anywhere. "
                                                       "Run Vidstash on your own computer with ./app.sh to download to a real folder."}) from None
            raise HTTPException(400, {"message": f"Can't save to {out}: {e.strerror or e}. Pick another folder."}) from None
        data["output_dir"] = str(out)
    if "options" in body:
        data["options"] = normalize_options(body["options"])
    if "open_browser" in body:
        data["open_browser"] = bool(body["open_browser"])
    return save_settings(data)


MEDIA_EXTS = engine.VIDEO_EXTS + engine.AUDIO_EXTS


def _folder_stats(path: Path):
    count, size, latest = 0, 0, 0.0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.lower().endswith(MEDIA_EXTS) and not f.endswith(engine.PARTIAL_SUFFIXES):
                st = os.stat(os.path.join(root, f))
                count += 1
                size += st.st_size
                latest = max(latest, st.st_mtime)
    return count, size, latest


def _platform_of(path: Path):
    for archive in path.rglob(".downloaded*.txt"):
        try:
            first = archive.read_text().split(" ", 1)[0].strip()
        except OSError:
            continue
        if first in ("youtube", "facebook"):
            return first
    return None


@app.get("/api/library")
def api_library():
    root = Path(_output_dir())
    folders = []
    if root.exists():
        for p in root.iterdir():
            if not p.is_dir() or p.name.startswith("."):
                continue
            count, size, latest = _folder_stats(p)
            subs = [d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")]
            folders.append({"name": p.name, "path": str(p), "count": count, "size": size,
                            "updated": latest or p.stat().st_mtime, "platform": _platform_of(p), "subfolders": subs})
    folders.sort(key=lambda f: f["updated"], reverse=True)
    return {"root": str(root), "folders": folders}


def _check_allowed(path: str) -> Path:
    p = Path(os.path.expanduser(path)).resolve()
    roots = {Path(_output_dir()).resolve(), (PROJECT_DIR / "downloads").resolve()}
    m = get_manager()
    roots |= {Path(j.output_dir).resolve() for j in m.jobs.values() if j.output_dir}
    if not any(p == r or r in p.parents for r in roots):
        raise HTTPException(403, {"message": "Only folders inside your downloads can be opened."})
    return p


@app.get("/api/library/files")
def api_library_files(path: str):
    p = _check_allowed(path)
    if not p.is_dir():
        raise HTTPException(404, {"message": "Folder not found."})
    files = []
    for root, dirs, names in os.walk(p):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(names):
            if f.lower().endswith(MEDIA_EXTS) and not f.endswith(engine.PARTIAL_SUFFIXES):
                full = os.path.join(root, f)
                files.append({"name": os.path.relpath(full, p), "path": full, "size": os.path.getsize(full)})
    return {"path": str(p), "files": files}


def _open_path(p: Path, reveal=False):
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)] if reveal else ["open", str(p)])
    elif sys.platform.startswith("win"):
        if reveal:
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(p.parent if reveal else p)])


@app.post("/api/open")
def api_open(body: PathIn):
    p = _check_allowed(body.path)
    if not p.exists():
        if body.reveal:
            raise HTTPException(404, {"message": "That file isn't there anymore."})
        p.mkdir(parents=True, exist_ok=True)
    _open_path(p, body.reveal)
    return {"ok": True}


@app.post("/api/pick-folder")
def api_pick_folder():
    if sys.platform != "darwin":
        raise HTTPException(501, {"message": "Folder picker is only available on macOS — type the path instead."})
    script = 'POSIX path of (choose folder with prompt "Choose where downloads should be saved")'
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if res.returncode != 0:
        return {"path": None}
    return {"path": res.stdout.strip().rstrip("/")}


# --------------------------------------------------------------------------
# routes: system health, updates, facebook session

_latest_cache = {"t": 0.0, "v": None}


def _latest_ytdlp():
    if time.time() - _latest_cache["t"] < 3600:
        return _latest_cache["v"]
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=4) as r:
            _latest_cache["v"] = json.load(r)["info"]["version"]
    except Exception:
        pass
    _latest_cache["t"] = time.time()
    return _latest_cache["v"]


def _norm_ver(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


def _ffmpeg_version():
    if not shutil.which("ffmpeg"):
        return None
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
        return out.split("\n", 1)[0].split(" ")[2]
    except Exception:
        return "installed"


def _chromium_installed():
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    candidates = [base] if base else [
        os.path.expanduser("~/Library/Caches/ms-playwright"),
        os.path.expanduser("~/.cache/ms-playwright"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
    ]
    return any(glob.glob(os.path.join(c, "chromium*")) for c in candidates if c)


_fb_login = {"running": False, "message": ""}
_update = {"running": False, "log": "", "ok": None, "needs_restart": False}


@app.get("/api/system")
def api_system():
    from . import scraper

    current = yt_dlp.version.__version__
    latest = _latest_ytdlp()
    runtimes = list(engine._js_runtimes())
    return {
        "app_version": __version__,
        "python": platform_mod.python_version(),
        "os": f"{platform_mod.system()} {platform_mod.machine()}",
        "ytdlp": {"version": current, "latest": latest,
                  "outdated": bool(latest and _norm_ver(latest) > _norm_ver(current))},
        "ffmpeg": _ffmpeg_version(),
        "encoder": engine.h264_encoder() if shutil.which("ffmpeg") else None,
        "js_runtimes": runtimes,
        "chromium": _chromium_installed(),
        "facebook": {"logged_in": scraper.has_saved_session(), **_fb_login},
        "update": _update,
        "output_dir": _output_dir(),
    }


def _run_update(everything: bool):
    _update.update(running=True, log="", ok=None)
    cmds = [[sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"]]
    if everything:
        cmds = [
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
            [sys.executable, "-m", "pip", "install", "--upgrade", "-r", str(PROJECT_DIR / "requirements.txt")],
            [sys.executable, "-m", "playwright", "install", "chromium"],
        ]
    ok = True
    for cmd in cmds:
        _update["log"] += "$ " + " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd)) + "\n"
        res = subprocess.run(cmd, capture_output=True, text=True)
        _update["log"] += (res.stdout + res.stderr)[-4000:] + "\n"
        ok = ok and res.returncode == 0
    _latest_cache["t"] = 0
    _update.update(running=False, ok=ok, needs_restart=ok)


@app.post("/api/update")
def api_update(body: dict | None = None):
    if _update["running"]:
        return {"ok": False, "message": "An update is already running."}
    threading.Thread(target=_run_update, args=(bool((body or {}).get("everything")),), daemon=True).start()
    return {"ok": True}


@app.post("/api/restart")
def api_restart():
    m = get_manager()
    if m.current:
        raise HTTPException(409, {"message": "A download is running — wait for it or cancel it first."})

    def bye():
        time.sleep(0.4)
        m.save()
        os._exit(RESTART_EXIT_CODE)  # app.sh relaunches on this exit code

    threading.Thread(target=bye, daemon=True).start()
    return {"ok": True}


def _fb_login_thread():
    from . import scraper

    _fb_login.update(running=True, message="Opening a Facebook login window…")
    try:
        scraper.ensure_logged_in(on_status=lambda msg: _fb_login.update(message=msg))
        _fb_login["message"] = "Connected."
    except Exception as e:
        _fb_login["message"] = engine.clean_error(e)
    finally:
        _fb_login["running"] = False


@app.post("/api/facebook/login")
def api_fb_login():
    if not _fb_login["running"]:
        threading.Thread(target=_fb_login_thread, daemon=True).start()
    return {"ok": True}


@app.post("/api/facebook/logout")
def api_fb_logout():
    from . import scraper

    scraper.logout()
    _fb_login["message"] = "Disconnected."
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --------------------------------------------------------------------------
# entry point


def _port_free(host, port) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _is_our_app(host, port) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/system", timeout=1.5) as r:
            return "ytdlp" in json.load(r)
    except Exception:
        return False


def main(argv=None) -> int:
    import uvicorn

    settings = load_settings()
    parser = argparse.ArgumentParser(prog="fbreels-web", description="Run the downloader's web UI.")
    parser.add_argument("--port", type=int, default=settings.get("port", 8787))
    parser.add_argument("--host", default="127.0.0.1", help="Default 127.0.0.1 (only this computer).")
    parser.add_argument("--no-browser", action="store_true", help="Don't open the browser automatically.")
    args = parser.parse_args(argv)

    host, port = args.host, args.port
    if not _port_free(host, port):
        if _is_our_app(host, port):
            print(f"Already running at http://{host}:{port} — opening it.")
            if not args.no_browser:
                webbrowser.open(f"http://{host}:{port}")
            return 0
        while not _port_free(host, port):
            port += 1

    _allowed_hosts.update({f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"})
    if host not in ("127.0.0.1", "localhost", "::1"):
        _allowed_hosts.clear()  # explicit LAN mode: accept any Host header
        print("WARNING: listening beyond this computer — anyone on your network can use it.")

    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    print(f"\n  Video downloader is running at {url}\n  Press Ctrl+C to stop.\n")
    get_manager()
    if not args.no_browser and settings.get("open_browser", True):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
