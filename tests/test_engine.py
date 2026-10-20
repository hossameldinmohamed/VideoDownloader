import json
import shutil
import subprocess

import pytest

from fbreels import engine
from fbreels.config import normalize_options


def fake_scan(n=5, platform="youtube", limit_from="end", single=False):
    items = [
        {"key": f"id{i}", "archive": f"{platform} id{i}", "url": f"https://example/{i}", "title": f"Video {i}",
         "thumbnail": None, "duration": 10}
        for i in range(1, n + 1)
    ]
    return {"platform": platform, "kind": "channel", "title": "Chan",
            "groups": [{"key": "videos", "label": "Videos", "folder": ["Chan"], "single": single,
                        "limit_from": limit_from, "items": items}]}


def test_numbering_is_stable_and_appends(tmp_path):
    m = tmp_path / ".manifest.json"
    assert engine.assign_indices(["a", "b", "c"], m) == {"a": 1, "b": 2, "c": 3}
    # new uploads get the next numbers, old ones keep theirs, order of input doesn't matter
    assert engine.assign_indices(["d", "c", "a", "b"], m) == {"a": 1, "b": 2, "c": 3, "d": 4}
    assert json.loads(m.read_text()) == ["a", "b", "c", "d"]


def test_preview_numbers_do_not_write(tmp_path):
    nums = engine.preview_numbers(fake_scan(3), str(tmp_path))
    assert nums["videos"] == {"id1": 1, "id2": 2, "id3": 3}
    assert not (tmp_path / "Chan").exists()


def test_prepare_items_limit_and_padding(tmp_path):
    opts = normalize_options({"limit": 2})
    items = engine.prepare_items(fake_scan(5), opts, str(tmp_path))
    # channel lists are oldest-first, so "newest 2" are the last two
    assert [i["index"] for i in items] == [4, 5]
    assert [i["prefix"] for i in items] == ["004", "005"]
    # but the whole channel is numbered
    assert json.loads((tmp_path / "Chan" / ".manifest.json").read_text()) == [f"id{i}" for i in range(1, 6)]


def test_prepare_items_facebook_limit_takes_first(tmp_path):
    opts = normalize_options({"limit": 2})
    items = engine.prepare_items(fake_scan(5, "facebook", "start"), opts, str(tmp_path))
    assert [i["index"] for i in items] == [1, 2]


def test_prepare_items_skips_archived_and_existing_files(tmp_path):
    folder = tmp_path / "Chan"
    folder.mkdir()
    (folder / ".downloaded.txt").write_text("youtube id1\n")
    (folder / "2.mp4").write_text("x")          # old unpadded Facebook-style name
    (folder / "003 - Video 3.mp4").write_text("x")
    (folder / "004 - Video 4.mp4.part").write_text("x")  # partial download doesn't count
    items = engine.prepare_items(fake_scan(4), normalize_options({}), str(tmp_path))
    assert [i["status"] for i in items] == ["skipped", "skipped", "skipped", "queued"]


def test_audio_uses_separate_archive(tmp_path):
    folder = tmp_path / "Chan"
    folder.mkdir()
    (folder / ".downloaded.txt").write_text("youtube id1\n")
    items = engine.prepare_items(fake_scan(1), normalize_options({"format": "mp3"}), str(tmp_path))
    assert items[0]["status"] == "queued"


def test_selected_subset(tmp_path):
    items = engine.prepare_items(fake_scan(5), normalize_options({}), str(tmp_path), selected=["id2", "id5"])
    assert [i["index"] for i in items] == [2, 5]


def test_single_video_has_no_number(tmp_path):
    items = engine.prepare_items(fake_scan(1, single=True), normalize_options({"naming": "number_title"}), str(tmp_path))
    assert items[0]["index"] is None
    assert engine._outtmpl(items[0], normalize_options({})).endswith("%(title).150B.%(ext)s")


@pytest.mark.parametrize("naming,expected", [
    ("number_title", "007 - %(title).150B.%(ext)s"),
    ("number", "007.%(ext)s"),
    ("title", "%(title).150B.%(ext)s"),
])
def test_outtmpl(naming, expected):
    item = {"index": 7, "prefix": "007", "out_dir": "/x"}
    assert engine._outtmpl(item, normalize_options({"naming": naming})) == f"/x/{expected}"


def test_format_opts():
    assert engine._format_opts(normalize_options({"format": "mp3"})) == {"format": "ba/b"}
    mp4 = engine._format_opts(normalize_options({"quality": "1080"}))
    assert mp4["format_sort"][0] == "res:1080"
    assert "vcodec:h264" in mp4["format_sort"]
    assert mp4["merge_output_format"] == "mp4"
    assert engine._format_opts(normalize_options({}))["format_sort"][0] == "res"


def test_normalize_options_clamps_garbage():
    o = normalize_options({"workers": "999", "limit": "-3", "tabs": ["bogus"], "quality": "8k", "format": "avi",
                           "cookies_browser": "netscape"})
    assert o["workers"] == 16 and o["limit"] is None and o["tabs"] == ["videos"]
    assert o["quality"] == "best" and o["format"] == "mp4" and o["cookies_browser"] == ""


def test_sanitize_folder():
    assert engine.sanitize_folder('A/B: "C" | Facebook') == "A_B_ _C_"
    assert engine.sanitize_folder("") == "Untitled"
    assert engine.sanitize_folder("قناة عربية") == "قناة عربية"


def test_clean_error_adds_hints():
    msg = engine.clean_error(Exception("ERROR: [youtube] x: Sign in to confirm you’re not a bot"))
    assert "Browser cookies" in msg and not msg.startswith("ERROR")


def _ffmpeg_has(encoder):
    if not shutil.which("ffmpeg"):
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return encoder in out


@pytest.mark.skipif(not (_ffmpeg_has("libvpx-vp9") and _ffmpeg_has("libopus")), reason="needs ffmpeg with vp9/opus")
def test_ensure_playable_mp4_converts_vp9_opus(tmp_path):
    src = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=1",
         "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "libvpx-vp9", "-c:a", "libopus", "-shortest", str(src)],
        check=True,
    )
    assert engine.probe(str(src))["video"] == "vp9"
    progress = []
    assert engine.ensure_playable_mp4(str(src), progress.append) is True
    info = engine.probe(str(src))
    assert (info["video"], info["audio"]) == ("h264", "aac")
    assert not (tmp_path / "clip.mp4.converting.mp4").exists()
    # already playable → untouched
    assert engine.ensure_playable_mp4(str(src)) is False


def test_per_group_selection_and_forced_redownload(tmp_path):
    folder = tmp_path / "Chan"
    folder.mkdir()
    (folder / ".downloaded.txt").write_text("youtube id1\n")
    scan = fake_scan(3)
    # hand-picked → attempted even though id1 is in the archive (maybe the file was deleted)
    items = engine.prepare_items(scan, normalize_options({}), str(tmp_path), selected={"videos": ["id1", "id3"]})
    assert [(i["key"], i["status"]) for i in items] == [("id1", "queued"), ("id3", "queued")]
    # no selection for this group → nothing from it
    assert engine.prepare_items(scan, normalize_options({}), str(tmp_path), selected={"shorts": ["x"]}) == []


def test_unavailable_items_are_never_downloaded(tmp_path):
    scan = fake_scan(3)
    scan["groups"][0]["items"][1]["unavailable"] = "Live now"
    items = engine.prepare_items(scan, normalize_options({}), str(tmp_path))
    assert [i["key"] for i in items] == ["id1", "id3"]
    picked = engine.prepare_items(scan, normalize_options({}), str(tmp_path), selected={"videos": ["id2"]})
    assert picked == []


def test_annotate_detects_downloads_anywhere_in_channel(tmp_path):
    (tmp_path / "Chan" / "Shorts").mkdir(parents=True)
    (tmp_path / "Chan" / "Shorts" / ".downloaded.txt").write_text("youtube id2\n")
    group = {**fake_scan(3)["groups"][0], "folder": ["Chan", "Playlists", "Mix"], "limit_from": "start"}
    a = engine.annotate_group(group, normalize_options({}), str(tmp_path))
    assert [i["downloaded"] for i in a["items"]] == [False, True, False]
    assert [i["number"] for i in a["items"]] == [1, 2, 3]
    assert a["folder"].endswith("Chan/Playlists/Mix")
    # audio downloads are tracked separately from video
    a = engine.annotate_group(group, normalize_options({"format": "mp3"}), str(tmp_path))
    assert not any(i["downloaded"] for i in a["items"])


def test_collections_are_not_downloadable(tmp_path):
    scan = {"platform": "youtube", "kind": "channel", "title": "Chan",
            "groups": [{"key": "playlists", "label": "Playlists", "type": "collections",
                        "items": [{"key": "PL1", "title": "Mix"}]}]}
    assert engine.prepare_items(scan, normalize_options({}), str(tmp_path)) == []


def test_yt_entries_marks_live_and_upcoming():
    info = {"entries": [
        {"id": "a" * 11, "title": "Old stream", "live_status": "was_live"},
        {"id": "b" * 11, "title": "On air", "live_status": "is_live"},
        {"id": "c" * 11, "title": "Soon", "live_status": "is_upcoming"},
        {"id": "d" * 11, "title": "[Private video]"},
    ]}
    got = [(e["title"], e["unavailable"]) for e in engine._yt_entries(info)]
    assert got == [("Old stream", None), ("On air", "Live now"), ("Soon", "Upcoming")]


def test_entry_date():
    assert engine._entry_date({"timestamp": 1700000000.0}) == 1700000000
    assert engine._entry_date({"upload_date": "20240102"}) == 1704153600
    assert engine._entry_date({"release_timestamp": 5}) == 5
    assert engine._entry_date({"upload_date": "bad"}) is None
    assert engine._entry_date({}) is None
