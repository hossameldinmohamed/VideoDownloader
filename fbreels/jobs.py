"""Background job queue for the web app: one job (a channel, page, playlist
or video) runs at a time, with its videos downloading in parallel."""

import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path

from . import engine
from .config import JOBS_FILE, STATE_DIR
from .resolver import Target

ACTIVE = {"queued", "scanning", "downloading"}
MAX_HISTORY = 60
DIRECT_IDLE = 15 * 60  # a "this device only" job waits this long for the device to come back
ITEM_FIELDS_SAVED = ("key", "archive", "url", "title", "thumbnail", "duration", "group", "platform", "index",
                     "prefix", "out_dir", "archive_path", "status", "progress", "error", "file", "size",
                     "user_cancelled")


class Job:
    def __init__(self, input_text, target: Target, options, output_dir, scan=None, selected=None):
        self.id = uuid.uuid4().hex[:12]
        self.input = input_text
        self.target = target.to_dict()
        self.options = options
        self.output_dir = output_dir
        self.scan = scan
        self.selected = selected
        self.status = "queued"
        self.message = "Waiting in queue…"
        self.title = target.label
        self.avatar = None
        self.kind = target.kind
        self.platform = target.platform
        self.folder = None
        self.items = []
        self.created = time.time()
        self.started = None
        self.finished = None
        self.cancel_event = threading.Event()
        self.touched = time.time()  # last time the device pulled a video ("this device only")

    @property
    def direct(self):
        """Videos go straight to the device that asked for them, nothing is kept here."""
        return bool(self.options.get("direct"))

    # -- serialization
    def to_dict(self, items="none"):
        counts = engine.summarize(self.items)
        progress = (sum(i["progress"] or 0 for i in self.items) / len(self.items)) if self.items else 0.0
        speed = sum(i.get("speed") or 0 for i in self.items if i["status"] == "downloading")
        d = {
            "id": self.id, "input": self.input, "target": self.target, "options": self.options,
            "output_dir": self.output_dir, "status": self.status, "message": self.message,
            "title": self.title, "avatar": self.avatar, "kind": self.kind, "platform": self.platform,
            "folder": self.folder, "counts": counts, "progress": progress, "speed": speed,
            "created": self.created, "started": self.started, "finished": self.finished,
        }
        if items == "all":
            d["items"] = self.items
        elif items == "active":
            d["items"] = [i for i in self.items if i["status"] in ("downloading", "processing")]
        return d

    def persisted(self):
        d = self.to_dict()
        d["items"] = [{k: i.get(k) for k in ITEM_FIELDS_SAVED} for i in self.items]
        return d

    @classmethod
    def restore(cls, d):
        job = cls.__new__(cls)
        job.__dict__.update({k: d.get(k) for k in (
            "id", "input", "target", "options", "output_dir", "status", "message", "title",
            "avatar", "kind", "platform", "folder", "created", "started", "finished")})
        job.scan = None
        job.selected = None
        job.items = [{**i, "speed": None, "eta": None, "phase": ""} for i in d.get("items") or []]
        job.cancel_event = threading.Event()
        job.touched = time.time()
        if job.status in ACTIVE:
            job.status = "interrupted"
            job.message = "The app was closed while this was running — press Resume to continue."
        for i in job.items:
            if i["status"] in ("downloading", "processing", "queued"):
                i["status"] = "cancelled" if job.status == "interrupted" else i["status"]
        return job


class JobReporter(engine.Reporter):
    def __init__(self, manager, job):
        self.manager = manager
        self.job = job

    def status(self, message):
        self.job.message = message

    def update(self, item, **fields):
        with self.manager.lock:
            if "status" in fields and fields["status"] != item.get("status"):
                self.manager.dirty = True
            item.update(fields)

    def cancelled(self, item=None):
        return self.job.cancel_event.is_set() or super().cancelled(item)


class JobManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}
        self.queue: queue.Queue[str] = queue.Queue()
        self.current: str | None = None
        self.dirty = False
        self._load()
        threading.Thread(target=self._worker, daemon=True, name="job-worker").start()
        threading.Thread(target=self._saver, daemon=True, name="job-saver").start()

    # -- persistence
    def _load(self):
        if not JOBS_FILE.exists():
            return
        try:
            data = json.loads(JOBS_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for d in data:
            try:
                job = Job.restore(d)
                self.jobs[job.id] = job
            except Exception:
                continue

    def save(self):
        with self.lock:
            jobs = list(self.jobs.values())[-MAX_HISTORY:]
            data = [j.persisted() for j in jobs]
            self.dirty = False
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = JOBS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(JOBS_FILE)

    def _saver(self):
        while True:
            time.sleep(2)
            if self.dirty:
                try:
                    self.save()
                except Exception:
                    pass

    # -- public API
    def create(self, input_text, target, options, output_dir, scan=None, selected=None) -> Job:
        job = Job(input_text, target, options, output_dir, scan, selected)
        with self.lock:
            self.jobs[job.id] = job
            # Keep history bounded: drop the oldest finished jobs.
            finished = [j for j in self.jobs.values() if j.status not in ACTIVE]
            for old in finished[: max(0, len(self.jobs) - MAX_HISTORY)]:
                self.jobs.pop(old.id, None)
            self.dirty = True
        self._start(job)
        return job

    def _start(self, job):
        if job.direct:  # mostly waits on the device, so it mustn't hold up the queue
            threading.Thread(target=self._run_job, args=(job,), daemon=True, name=f"direct-{job.id}").start()
        else:
            self.queue.put(job.id)

    def claim_direct(self, job, key):
        """Hand one waiting video of a "this device only" job to the device that asked for it."""
        with self.lock:
            item = next((i for i in job.items if i["key"] == key), None)
            if not job.direct or job.status != "downloading" or not item or item["status"] != "queued":
                return None
            item.update(status="downloading", phase="Sending to this device", progress=0.0, error=None)
            job.touched = time.time()
            self.dirty = True
            return item

    def direct_queue(self, job, watch=(), limit=8):
        with self.lock:
            return {
                "next": [{"key": i["key"], "title": i["title"], "name": engine.direct_name(i, job.options),
                          "sub": os.path.relpath(i["out_dir"], job.output_dir)}
                         for i in job.items if i["status"] == "queued" and i["key"] not in watch][:limit],
                "status": {i["key"]: i["status"] for i in job.items if i["key"] in watch},
            }

    def get(self, job_id) -> Job | None:
        return self.jobs.get(job_id)

    def list(self):
        with self.lock:
            return [j.to_dict(items="active") for j in reversed(list(self.jobs.values()))]

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.status not in ACTIVE:
            return False
        job.cancel_event.set()
        if job.status == "queued":
            job.status = "cancelled"
            job.message = "Cancelled."
            job.finished = time.time()
        self.dirty = True
        return True

    def cancel_item(self, job_id, key):
        """Stop one video and leave the rest of the job running."""
        job = self.jobs.get(job_id)
        if not job or job.status not in ACTIVE:
            return False
        with self.lock:
            item = next((i for i in job.items if i["key"] == key), None)
            if not item or item["status"] not in ("queued", "downloading", "processing"):
                return False
            item["user_cancelled"] = True
            if item["status"] == "queued":
                item.update(status="cancelled", progress=0.0)
            self.dirty = True
        return True

    def retry(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.status in ACTIVE:
            return False
        job.cancel_event = threading.Event()
        job.status = "queued"
        job.message = "Waiting in queue…"
        job.finished = None
        with self.lock:
            for i in job.items:
                if i["status"] in ("failed", "cancelled", "downloading", "processing") and not i.get("user_cancelled"):
                    i.update(status="queued", progress=0.0, error=None)
        self.dirty = True
        self._start(job)
        return True

    def remove(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job.status in ACTIVE:
            self.cancel(job_id)
        with self.lock:
            self.jobs.pop(job_id, None)
            self.dirty = True
        return True

    def clear_finished(self):
        with self.lock:
            for jid in [j.id for j in self.jobs.values() if j.status not in ACTIVE]:
                self.jobs.pop(jid)
            self.dirty = True

    # -- worker
    def _worker(self):
        while True:
            job_id = self.queue.get()
            job = self.jobs.get(job_id)
            if not job or job.cancel_event.is_set() or job.status != "queued":
                continue
            self.current = job.id
            try:
                self._run_job(job)
            finally:
                self.current = None

    def _run_job(self, job):
        try:
            self._run(job)
        except engine.Cancelled:
            job.status, job.message = "cancelled", "Cancelled."
        except Exception as e:
            job.status, job.message = "failed", engine.clean_error(e)
        finally:
            job.finished = time.time()
            self.dirty = True

    def _wait_for_device(self, job) -> bool:
        """The device pulls each video itself (see /api/jobs/{id}/stream); wait until it has them all."""
        with self.lock:
            for i in job.items:
                if i["status"] in ("failed", "cancelled") and not i.get("user_cancelled"):
                    i.update(status="queued", progress=0.0, error=None)
        job.touched = time.time()
        while True:
            with self.lock:
                waiting = [i for i in job.items if i["status"] == "queued"]
                busy = any(i["status"] in ("downloading", "processing") for i in job.items)
                if job.cancel_event.is_set() and not busy:
                    for i in waiting:
                        i["status"] = "cancelled"
                    return True
                if not waiting and not busy:
                    return True
                if not busy and time.time() - job.touched > DIRECT_IDLE:
                    job.status = "interrupted"
                    job.message = "Paused — open Vidstash on your device and press Resume to get the rest."
                    return False
            time.sleep(0.5)

    def _run(self, job: Job):
        reporter = JobReporter(self, job)
        job.started = job.started or time.time()
        target = Target(**job.target)

        if not job.items:
            job.status = "scanning"
            job.message = "Looking up videos…"
            scan = job.scan or engine.scan(target, job.options, reporter)
            job.scan = None  # don't keep the whole listing in memory
            job.title = scan.get("title") or job.title
            job.avatar = scan.get("avatar")
            job.kind = scan.get("kind") or job.kind
            job.items = engine.prepare_items(scan, job.options, job.output_dir, job.selected)
            if scan["groups"]:
                job.folder = str(Path(job.output_dir) / scan["groups"][0]["folder"][0])
            self.dirty = True
            if not job.items:
                job.status, job.message = "failed", "No videos found there."
                return

        if job.cancel_event.is_set():
            raise engine.Cancelled()

        job.status = "downloading"
        counts = engine.summarize(job.items)
        todo = counts["queued"] + counts["failed"] + counts["cancelled"]
        job.message = f"Downloading {todo} video(s)…" if todo else "Everything is already downloaded."
        if job.direct:
            if todo:
                job.message = f"Sending {todo} video(s) straight to your device…"
            if not self._wait_for_device(job):
                return
            counts = engine.summarize(job.items)
        else:
            counts = engine.run_items(job.items, job.options, reporter)

        if job.cancel_event.is_set():
            job.status, job.message = "cancelled", "Cancelled — press Resume to continue where it stopped."
        elif counts["failed"]:
            ok = counts["done"] + counts["skipped"]
            job.status = "partial" if ok else "failed"
            job.message = f"{counts['failed']} video(s) failed — press Retry to try them again."
        else:
            job.status = "done"
            job.message = f"{counts['done']} downloaded, {counts['skipped']} already there."
            if counts["cancelled"]:
                job.message += f" {counts['cancelled']} cancelled by you."
