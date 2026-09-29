import pytest

from fbreels.resolver import ResolveError, resolve


@pytest.mark.parametrize(
    "text,platform,kind,url,tab",
    [
        ("https://www.youtube.com/@mkbhd", "youtube", "channel", "https://www.youtube.com/@mkbhd", ""),
        ("youtube.com/@mkbhd/videos", "youtube", "channel", "https://www.youtube.com/@mkbhd", "videos"),
        ("https://www.youtube.com/@NASA/shorts", "youtube", "channel", "https://www.youtube.com/@NASA", "shorts"),
        ("https://m.youtube.com/channel/UC4QobU6STFB0P71PMvOGN5A", "youtube", "channel",
         "https://www.youtube.com/channel/UC4QobU6STFB0P71PMvOGN5A", ""),
        ("https://www.youtube.com/c/Oldname/featured", "youtube", "channel", "https://www.youtube.com/c/Oldname", ""),
        ("https://www.youtube.com/user/legacy", "youtube", "channel", "https://www.youtube.com/user/legacy", ""),
        ("https://youtu.be/jNQXAC9IVRw?t=3", "youtube", "video", "https://www.youtube.com/watch?v=jNQXAC9IVRw", ""),
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PL123", "youtube", "video",
         "https://www.youtube.com/watch?v=jNQXAC9IVRw", ""),
        ("https://www.youtube.com/shorts/abcdefghijk", "youtube", "video", "https://www.youtube.com/watch?v=abcdefghijk", ""),
        ("https://www.youtube.com/playlist?list=PLxyz", "youtube", "playlist", "https://www.youtube.com/playlist?list=PLxyz", ""),
        ("@veritasium", "youtube", "channel", "https://www.youtube.com/@veritasium", ""),
        ("UC4QobU6STFB0P71PMvOGN5A", "youtube", "channel", "https://www.youtube.com/channel/UC4QobU6STFB0P71PMvOGN5A", ""),
        ("https://www.facebook.com/somepage", "facebook", "page", "https://www.facebook.com/somepage", ""),
        ("facebook.com/somepage/reels", "facebook", "page", "https://www.facebook.com/somepage", ""),
        ("https://www.facebook.com/somepage/videos", "facebook", "page", "https://www.facebook.com/somepage", ""),
        ("https://www.facebook.com/profile.php?id=61591194945375", "facebook", "page",
         "https://www.facebook.com/profile.php?id=61591194945375", ""),
        ("61591194945375", "facebook", "page", "https://www.facebook.com/profile.php?id=61591194945375", ""),
        ("https://www.facebook.com/reel/123456789", "facebook", "video", "https://www.facebook.com/reel/123456789", ""),
        ("https://www.facebook.com/somepage/videos/123456", "facebook", "video",
         "https://www.facebook.com/somepage/videos/123456", ""),
        ("https://fb.watch/abc123/", "facebook", "video", "https://fb.watch/abc123/", ""),
        ("https://www.facebook.com/share/16AN8MhwdSN/?mibextid=wwXIfr", "facebook", "page",
         "https://www.facebook.com/share/16AN8MhwdSN/?mibextid=wwXIfr", ""),
    ],
)
def test_resolve(text, platform, kind, url, tab):
    t = resolve(text)
    assert (t.platform, t.kind, t.url, t.tab) == (platform, kind, url, tab)


def test_bare_name_is_ambiguous_until_platform_chosen():
    with pytest.raises(ResolveError) as e:
        resolve("somename")
    assert e.value.ambiguous
    assert resolve("somename", "youtube").url == "https://www.youtube.com/@somename"
    assert resolve("somename", "facebook").url == "https://www.facebook.com/somename"
    assert resolve("@somename", "facebook").url == "https://www.facebook.com/somename"


@pytest.mark.parametrize("text", ["", "   ", "https://vimeo.com/123", "https://www.youtube.com/feed/trending", "hello world!"])
def test_rejects_unsupported(text):
    with pytest.raises(ResolveError):
        resolve(text)


@pytest.mark.parametrize("text,playlist", [
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PLabc123", "PLabc123"),
    ("https://youtu.be/jNQXAC9IVRw?list=PLabc123", "PLabc123"),
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=RDjNQXAC9IVRw", ""),  # auto Mix: endless, skip
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=WL", ""),              # Watch later: private
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw", ""),
])
def test_video_links_remember_their_playlist(text, playlist):
    t = resolve(text)
    assert t.kind == "video" and t.playlist == playlist
