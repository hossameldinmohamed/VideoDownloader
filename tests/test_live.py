"""Real downloads against YouTube. Off by default (network + YouTube may block
CI runners); run with:  LIVE=1 pytest tests/test_live.py"""

import os

import pytest

from fbreels import engine
from fbreels.config import normalize_options
from fbreels.resolver import resolve

pytestmark = pytest.mark.skipif(os.environ.get("LIVE") != "1", reason="set LIVE=1 to run live tests")


def test_youtube_channel_to_playable_mp4(tmp_path):
    options = normalize_options({"workers": 1})
    result = engine.scan(resolve("https://www.youtube.com/@jawed"), options)
    assert result["title"] == "jawed"
    items = engine.prepare_items(result, options, str(tmp_path))
    assert items and items[0]["index"] == 1
    counts = engine.run_items(items[:1], options)
    error = items[0].get("error") or ""
    if "not a bot" in error:
        # YouTube challenges datacenter IPs (e.g. GitHub runners); that is not
        # a breakage in our code or in yt-dlp, so don't report it as one.
        pytest.skip("YouTube bot check blocked this IP")
    assert counts["done"] == 1, error
    path = os.path.join(items[0]["out_dir"], items[0]["file"])
    assert items[0]["file"].startswith("001 - ") and path.endswith(".mp4")
    info = engine.probe(path)
    assert info["video"] == "h264" and info["audio"] in ("aac", "mp3")
