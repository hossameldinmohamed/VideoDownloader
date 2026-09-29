import argparse
import sys
import threading
from pathlib import Path

from . import engine
from .config import load_settings, normalize_options
from .resolver import ResolveError, resolve


class ConsoleReporter(engine.Reporter):
    """Prints one line per finished video instead of a progress bar per video."""

    def __init__(self):
        self.lock = threading.Lock()
        self.total = 0
        self.finished = 0

    def update(self, item, **fields):
        before = item.get("status")
        item.update(fields)
        status = item["status"]
        if status == before or status not in ("done", "failed"):
            return
        with self.lock:
            self.finished += 1
            label = f"#{item['index']}" if item.get("index") is not None else item["title"]
            if status == "done":
                print(f"[{self.finished}/{self.total}] {label} done")
            else:
                print(f"[{self.finished}/{self.total}] {label} FAILED: {item.get('error')}")


def main(argv=None) -> int:
    defaults = load_settings()
    parser = argparse.ArgumentParser(
        prog="fbreels",
        description=(
            "Download all reels from a Facebook page, or all videos from a "
            "YouTube channel, in the best available MP4 quality. "
            "Run ./app.sh for the web UI."
        ),
    )
    parser.add_argument(
        "page_url",
        help=(
            "A YouTube channel/playlist/video link or @handle, or a Facebook page — "
            "a slug (facebook.com/somepage), a profile.php?id=... link, or a "
            "facebook.com/share/... link. Quote it if it contains '?' or '&'."
        ),
    )
    parser.add_argument("-o", "--output", default=None, help=f"Output folder (default: {defaults['output_dir']})")
    parser.add_argument("-n", "--limit", type=int, default=None, help="Only grab the N most recent videos (default: all)")
    parser.add_argument("-w", "--workers", type=int, default=None, help="Parallel downloads (default: 3)")
    parser.add_argument("-p", "--platform", choices=["auto", "youtube", "facebook"], default="auto",
                        help="Which site a bare name refers to (default: auto — '@name' means YouTube)")
    parser.add_argument("-q", "--quality", choices=["best", "2160", "1440", "1080", "720", "480", "360"], default=None,
                        help="Max resolution (default: best)")
    parser.add_argument("-f", "--format", choices=["mp4", "original", "mp3", "m4a"], default=None,
                        help="mp4 = plays everywhere (default); original = keep VP9/AV1; mp3/m4a = audio only")
    parser.add_argument("--keep-original", action="store_true", help="Same as --format original")
    parser.add_argument("--tabs", default=None, help="YouTube channel sections, comma separated: videos,shorts,streams")
    parser.add_argument("--naming", choices=["number_title", "number", "title"], default=None,
                        help="File names: '001 - Title' (default), '001' or 'Title'")
    parser.add_argument("--subs", default=None, metavar="LANGS", help="Download & embed subtitles, e.g. 'en.*,ar'")
    parser.add_argument("--cookies-from-browser", default=None, metavar="BROWSER",
                        help="Use your browser's YouTube login (chrome, safari, firefox, edge, brave...)")
    parser.add_argument("--visible", action="store_true", help="Show the browser while scanning Facebook (debugging)")
    args = parser.parse_args(argv)

    overrides = {}
    if args.limit:
        overrides["limit"] = args.limit
    if args.workers:
        overrides["workers"] = args.workers
    if args.quality:
        overrides["quality"] = args.quality
    if args.format:
        overrides["format"] = args.format
    if args.keep_original:
        overrides["format"] = "original"
    if args.tabs:
        overrides["tabs"] = [t.strip() for t in args.tabs.split(",")]
    if args.naming:
        overrides["naming"] = args.naming
    if args.subs:
        overrides.update(subtitles=True, sub_langs=args.subs)
    if args.cookies_from_browser:
        overrides["cookies_browser"] = args.cookies_from_browser
    options = normalize_options(overrides)
    output_dir = str(Path(args.output or defaults["output_dir"]).expanduser())

    try:
        target = resolve(args.page_url, args.platform)
    except ResolveError as e:
        print(str(e) + (" Use --platform youtube or --platform facebook." if e.ambiguous else ""))
        return 1

    print(f"Scanning {target.url} ...")
    try:
        result = engine.scan(target, options, headless=not args.visible)
    except Exception as e:
        print(f"Couldn't read that: {engine.clean_error(e)}")
        return 1

    items = engine.prepare_items(result, options, output_dir)
    if not items:
        print("No videos found. The channel/page may have none, or the URL may be wrong.")
        return 1

    reporter = ConsoleReporter()
    skipped = sum(1 for i in items if i["status"] == "skipped")
    reporter.total = len(items) - skipped
    print(f"Found {len(items)} video(s) on '{result['title']}'. Downloading in best available quality...")
    if skipped:
        print(f"{skipped} already downloaded, skipping.")
    print()
    counts = engine.run_items(items, options, reporter)
    folder = Path(items[0]["out_dir"])
    print(f"\n{counts['done'] + counts['skipped']}/{counts['total']} ready in {folder}")
    return 0 if not counts["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
