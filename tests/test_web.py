import os
import time

import pytest
from fastapi.testclient import TestClient

from fbreels import engine, web

H = {"X-Fbreels": "1"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "manager", None)
    monkeypatch.setattr(web, "_latest_ytdlp", lambda: None)
    with TestClient(web.app) as c:
        yield c


def test_index_and_static(client):
    r = client.get("/")
    assert r.status_code == 200 and "Vidstash" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_writes_require_custom_header(client):
    assert client.post("/api/resolve", json={"input": "@xy"}).status_code == 403
    assert client.post("/api/resolve", json={"input": "@xy"}, headers=H).status_code == 200


def test_host_check_blocks_dns_rebinding(client, monkeypatch):
    monkeypatch.setattr(web, "_allowed_hosts", {"127.0.0.1:8787"})
    assert client.get("/api/settings", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/api/settings", headers={"host": "127.0.0.1:8787"}).status_code == 200


def test_resolve_ambiguous(client):
    r = client.post("/api/resolve", json={"input": "somename"}, headers=H)
    assert r.status_code == 400 and r.json()["detail"]["ambiguous"] is True


def test_settings_roundtrip(client, tmp_path):
    r = client.put("/api/settings", json={"options": {"quality": "1080", "workers": 5}, "output_dir": str(tmp_path / "o")}, headers=H)
    assert r.status_code == 200
    s = client.get("/api/settings").json()
    assert s["options"]["quality"] == "1080" and s["options"]["workers"] == 5
    assert s["output_dir"].endswith("/o")


def test_system(client):
    s = client.get("/api/system").json()
    assert "ytdlp" in s and "version" in s["ytdlp"] and "facebook" in s


def test_open_outside_downloads_is_forbidden(client):
    assert client.post("/api/open", json={"path": "/etc"}, headers=H).status_code == 403


def test_job_lifecycle(client, monkeypatch, isolated_state):
    def fake_scan(target, options, reporter=None, headless=True):
        return {"platform": "youtube", "kind": "channel", "title": "Chan", "avatar": None,
                "groups": [{"key": "videos", "label": "Videos", "folder": ["Chan"], "single": False, "limit_from": "end",
                            "items": [{"key": f"v{i}", "archive": f"youtube v{i}", "url": f"u{i}", "title": f"T{i}",
                                       "thumbnail": None, "duration": 1} for i in range(3)]}]}

    def fake_download(item, options, reporter, cookiefile):
        if item["key"] == "v1":
            reporter.update(item, status="failed", error="boom")
            return False
        reporter.update(item, status="done", progress=1.0, file=f"{item['prefix']} - {item['title']}.mp4")
        return True

    monkeypatch.setattr(engine, "scan", fake_scan)
    monkeypatch.setattr(engine, "_download_one", fake_download)

    r = client.post("/api/jobs", json={"inputs": ["@chan"], "options": {}}, headers=H)
    assert r.status_code == 200
    job_id = r.json()["jobs"][0]["id"]

    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "scanning", "downloading"):
            break
        time.sleep(0.05)
    assert job["status"] == "partial"
    assert job["counts"]["done"] == 2 and job["counts"]["failed"] == 1
    assert [i["index"] for i in job["items"]] == [1, 2, 3]

    # retry only re-runs the failed one
    monkeypatch.setattr(engine, "_download_one", lambda item, *a: (item.update(status="done", progress=1.0), True)[1])
    assert client.post(f"/api/jobs/{job_id}/retry", headers=H).json()["ok"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "done":
            break
        time.sleep(0.05)
    assert job["status"] == "done" and job["counts"]["done"] == 3

    assert client.delete(f"/api/jobs/{job_id}", headers=H).json()["ok"]
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_create_job_needs_input(client):
    assert client.post("/api/jobs", json={"inputs": []}, headers=H).status_code == 400


def test_lookup_pick_and_download(client, monkeypatch):
    def fake_lookup(target, options, reporter=None):
        return {"platform": "youtube", "kind": "channel", "url": target.url, "title": "Chan", "avatar": None,
                "subtitle": None, "subscribers": 1200, "folder": ["Chan"], "groups": {},
                "tabs": [{"key": "videos", "label": "Videos", "type": "videos"},
                         {"key": "shorts", "label": "Shorts", "type": "videos"}],
                "default_tab": "videos", "target": target.to_dict()}

    def fake_load(lk, key, options, reporter=None, headless=True):
        if key not in ("videos", "shorts"):
            raise KeyError(key)
        folder = ["Chan"] + ([] if key == "videos" else ["Shorts"])
        g = {"key": key, "label": key.title(), "type": "videos", "folder": folder, "single": False,
             "limit_from": "end", "chrono": "oldest_first",
             "items": [{"key": f"{key}{i}", "archive": f"youtube {key}{i}", "url": f"u{i}", "title": f"{key} {i}",
                        "thumbnail": None, "duration": 5, "views": None, "unavailable": None} for i in range(3)]}
        lk["groups"][key] = g
        return g

    ran = []

    def fake_download(item, options, reporter, cookiefile):
        ran.append((item["group"], item["key"], item["out_dir"].split("/")[-1]))
        reporter.update(item, status="done", progress=1.0)
        return True

    monkeypatch.setattr(engine, "lookup", fake_lookup)
    monkeypatch.setattr(engine, "load_group", fake_load)
    monkeypatch.setattr(engine, "_download_one", fake_download)

    lk = client.post("/api/lookup", json={"input": "@chan"}, headers=H).json()
    assert [t["key"] for t in lk["tabs"]] == ["videos", "shorts"] and lk["subscribers"] == 1200
    lid = lk["lookup_id"]

    g = client.post(f"/api/lookup/{lid}/group", json={"key": "shorts"}, headers=H).json()["group"]
    assert g["folder"].endswith("Chan/Shorts") and all("downloaded" in i for i in g["items"])
    client.post(f"/api/lookup/{lid}/group", json={"key": "videos"}, headers=H)
    assert client.post(f"/api/lookup/{lid}/group", json={"key": "nope"}, headers=H).status_code == 404

    assert client.post("/api/jobs", json={"lookup_id": lid, "selections": {}}, headers=H).status_code == 400
    r = client.post("/api/jobs", json={"lookup_id": lid, "selections": {"videos": ["videos2"], "shorts": ["shorts0", "shorts1"]}},
                    headers=H)
    job_id = r.json()["jobs"][0]["id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "done":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert sorted(ran) == [("shorts", "shorts0", "Shorts"), ("shorts", "shorts1", "Shorts"), ("videos", "videos2", "Chan")]
    assert job["folder"].endswith("/Chan")

    assert client.post("/api/lookup/doesnotexist/group", json={"key": "videos"}, headers=H).status_code == 410


def test_output_dir_must_be_writable(client, tmp_path):
    ok = client.put("/api/settings", json={"output_dir": str(tmp_path / "new" / "folder")}, headers=H)
    assert ok.status_code == 200 and (tmp_path / "new" / "folder").is_dir()
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        bad = client.put("/api/settings", json={"output_dir": str(locked / "sub")}, headers=H)
        assert bad.status_code == 400 and "Can't save" in bad.json()["detail"]["message"]
    finally:
        locked.chmod(0o700)


def test_job_file_streams_finished_videos_only(client, monkeypatch):
    def fake_scan(target, options, reporter=None, headless=True):
        return {"platform": "youtube", "kind": "channel", "title": "Chan", "avatar": None,
                "groups": [{"key": "videos", "label": "Videos", "folder": ["Chan"], "single": False, "limit_from": "end",
                            "items": [{"key": f"v{i}", "archive": f"youtube v{i}", "url": f"u{i}", "title": f"T{i}",
                                       "thumbnail": None, "duration": 1} for i in range(2)]}]}

    def fake_download(item, options, reporter, cookiefile):
        if item["key"] == "v1":
            reporter.update(item, status="failed", error="boom")
            return False
        name = f"{item['prefix']} - {item['title']}.mp4"
        os.makedirs(item["out_dir"], exist_ok=True)
        with open(os.path.join(item["out_dir"], name), "wb") as f:
            f.write(b"video-bytes")
        reporter.update(item, status="done", progress=1.0, file=name)
        return True

    monkeypatch.setattr(engine, "scan", fake_scan)
    monkeypatch.setattr(engine, "_download_one", fake_download)
    job_id = client.post("/api/jobs", json={"inputs": ["@chan"], "options": {}}, headers=H).json()["jobs"][0]["id"]
    for _ in range(100):
        if client.get(f"/api/jobs/{job_id}").json()["status"] not in ("queued", "scanning", "downloading"):
            break
        time.sleep(0.05)

    r = client.get(f"/api/jobs/{job_id}/file", params={"key": "v0"})
    assert r.status_code == 200 and r.content == b"video-bytes"
    assert "attachment" in r.headers["content-disposition"]
    assert client.get(f"/api/jobs/{job_id}/file", params={"key": "v1"}).status_code == 404
    assert client.get(f"/api/jobs/{job_id}/file", params={"key": "nope"}).status_code == 404
    assert client.get("/api/jobs/missing/file", params={"key": "v0"}).status_code == 404
