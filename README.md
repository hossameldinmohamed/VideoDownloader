# Vidstash

Download whole YouTube channels and Facebook pages as MP4 files that play everywhere, from a clean web app that runs on your own computer.

- **Paste anything:** a channel or page link, a playlist, a single video, an `@handle`, a page name, a channel ID or a Facebook profile ID. It works out which one it is.
- **Neatly organised:** every channel gets its own folder, and files are named `001 - Title.mp4`, `002 - Title.mp4`… in upload order. Numbers never change between runs.
- **Best quality, plays anywhere:** it downloads the highest resolution available (up to 4K/8K) and makes sure the result is a standard H.264 + AAC MP4. When YouTube only offers VP9/AV1, it converts on your Mac's hardware encoder.
- **Preview & pick:** see every video with thumbnails, filter by title, and download only the ones you want.
- **Re-run any time:** only new uploads are downloaded. Stop halfway and resume later.
- Shorts, Live streams, playlists, MP3/M4A audio, subtitles, cover art, metadata, speed limits, parallel downloads, and browser cookies for members-only or age-restricted videos.

## Quick start (macOS)

```bash
git clone <this repo> && cd <repo>
./app.sh
```

The first run installs everything it needs: a Python virtualenv, `yt-dlp`, a headless Chromium for Facebook, and `ffmpeg` via Homebrew. Your browser then opens at **http://127.0.0.1:8787**.

After that, start it with `./app.sh` or by double-clicking **Start Vidstash.command** in Finder. Stop it with Ctrl+C in the terminal.

## Using the app

1. **Paste** a link or name and press **Enter** (or **Find videos**). A chip shows what was detected, such as "YouTube channel". For a bare name like `mkbhd`, pick YouTube or Facebook.
2. **Pick what to download.** The channel opens with only the tabs it actually has: **Videos, Shorts, Live, Podcasts, Playlists, Releases, Courses**. Each tab loads when you open it. Podcasts, Playlists, Releases and Courses open into their own video lists.
   - **Downloaded videos:** anything you already have from this channel, in any of its folders, is marked **✓ Downloaded** and starts unticked. Tick it to download it again.
   - **Pre-ticked videos:** new videos in the first tab you open are ticked for you. Use **Select: New only / All / None**, the title filter and **Newest / Oldest first** to adjust.
   - **Selections across tabs:** you can tick videos in several tabs at once. The bar at the bottom shows the total and the breakdown ("Videos 20 · Shorts 4 · Mix 3"). Press **Download**.
   - **Live streams:** anything live right now or upcoming can't be selected.
   - **Folders:** Shorts go in `Channel/Shorts`, Live in `Channel/Live`, and a playlist in `Channel/Playlists/<name>`.
   - **Whole playlists:** in the Playlists, Podcasts or Releases tab, tick a playlist's circle to grab every new video in it without opening it, or use **Every playlist**. A `watch?v=…&list=…` link offers **Open the whole playlist**.
   - **Where it saves:** shown right in the picker (**📁 Saves to …**). **Change…** opens a folder picker, which can be any folder or external drive, and the ✓ Downloaded marks re-check against the new folder. A folder that can't be written to is refused.
   - **Several channels at once:** paste one link per line and the button becomes **Download all N**. That grabs each channel's Videos tab (or a page's Reels) in full and skips anything already downloaded.
3. **Options** (remembered between runs):

   | Option | What it does |
   |---|---|
   | Quality | Best available, or a cap: 4K / 1440p / 1080p / 720p / 480p / 360p |
   | Format | **MP4** plays everywhere (converts VP9/AV1 → H.264 when needed) · **MP4 original codec** (no conversion) · **MP3** / **M4A** audio only |
   | File names | `001 - Title` · `001` · `Title` |
   | Parallel downloads | 1–8 at a time (3 is the default) |
   | Subtitles | Download and embed them (languages like `en.*, ar`), optionally including auto-generated ones |
   | Extras | Embed the thumbnail as cover art; embed title, date, chapters and description |
   | Browser cookies | Use your browser's YouTube login for members-only or age-restricted videos, or "confirm you're not a bot" errors |
   | Speed limit | Cap bandwidth per download, e.g. `5M` |
   | Save to | Any folder. Each channel or page gets a sub-folder named after it |

4. **Queue & history** shows live progress, speed, per-video status and errors. Use **Retry** or **Resume** to redo only what failed or stopped, and **Open folder** to jump to the files.
5. **Library** lists everything you've downloaded, with sizes and file lists.
6. **Settings** shows a health check (yt-dlp, ffmpeg, encoder, JS runtime, Chromium), has one-click updates, and connects your Facebook account.

### Facebook

Facebook only shows a page's full reel history to logged-in users. The first time you download a Facebook page (or when you click **Settings → Connect Facebook**), a browser window opens for you to log in once. The session is saved in `.fbreels/` on your computer and is never sent anywhere else.

## Terminal usage

Everything in the app also works from the terminal:

```bash
./fbreels.sh "https://www.youtube.com/@channel"
./fbreels.sh "@channel" -q 1080 -n 20             # newest 20, max 1080p
./fbreels.sh "@channel" --tabs videos,shorts
./fbreels.sh "https://www.youtube.com/playlist?list=PL..." -f mp3
./fbreels.sh "https://www.facebook.com/somepage"
./fbreels.sh somename --platform facebook
./fbreels.sh -h                                   # all options
```

Always wrap links in quotes, because `?` and `&` mean something to your shell.

## Staying up to date

YouTube and Facebook change their sites often, and `yt-dlp` usually ships a fix within days. So:

- **Every launch** of `./app.sh` updates `yt-dlp` first. Use `./app.sh --no-update` to skip it.
- **Settings → Update yt-dlp / Update everything** updates from inside the app, then **Restart now** reloads it.
- **On GitHub**, the workflows in `.github/` keep the project itself current:
  - **Dependabot** (`dependabot.yml`) opens pull requests for new releases of every Python dependency (checked daily, so yt-dlp fixes arrive fast) and every GitHub Action (weekly).
  - **CI** (`ci.yml`) runs lint, unit and API tests, plus an app-startup check, on Linux and macOS for every push and pull request.
  - **Auto-merge** (`dependabot-automerge.yml`) merges Dependabot pull requests automatically once CI passes. Major version bumps wait for you.
  - **Canary** (`canary.yml`) runs daily. It installs the newest release of everything, runs the tests plus a real YouTube download, and opens an issue if something broke.

  To enable auto-merge after pushing: **Settings → General → Allow auto-merge**, then add a branch protection rule on `main` that requires the CI checks.

## Development

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                     # unit + API tests
LIVE=1 pytest tests/test_live.py   # real YouTube download
ruff check fbreels tests
python -m fbreels.web --port 8787  # run the server directly
```

| Path | What's there |
|---|---|
| `fbreels/resolver.py` | Turns links, handles and names into a target |
| `fbreels/engine.py` | Scanning, numbering, yt-dlp options, MP4 conversion, parallel downloads |
| `fbreels/scraper.py` | Facebook Reels scanning with Playwright |
| `fbreels/jobs.py` | Background job queue, history, cancel and retry |
| `fbreels/web.py` | FastAPI server and API |
| `fbreels/static/` | The web UI (plain HTML/CSS/JS, no build step) |
| `fbreels/cli.py` | Terminal interface |

The server listens on `127.0.0.1` only. It rejects requests addressed to any other host name, which blocks DNS rebinding, and every write request needs a custom header, which blocks other websites from triggering downloads.

## Why not Vercel?

Vercel runs code as short-lived serverless functions. They time out after minutes, have no ffmpeg or persistent disk, and can't open the browser window the Facebook login needs. Worse, YouTube blocks downloads from cloud-server IP addresses. Vidstash is built to run on your own machine, where downloads are fast, stay private, and don't get blocked.

## Legal

Only download content you have the right to: your own channels and pages, or with the owner's permission. Respect YouTube's and Facebook's terms of service and copyright law.
