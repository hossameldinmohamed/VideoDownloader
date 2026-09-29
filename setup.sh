#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
  echo "python3 is required. Install it with 'brew install python' or from python.org." >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null; then
  echo "ffmpeg not found (needed to merge best video+audio into mp4)."
  if command -v brew >/dev/null; then
    echo "Installing ffmpeg via Homebrew..."
    brew install ffmpeg
  else
    echo "Install Homebrew (https://brew.sh) then run: brew install ffmpeg" >&2
    exit 1
  fi
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt
python -m playwright install chromium

echo ""
echo "Setup complete."
echo "  Web app:  ./app.sh   (or double-click 'Start Vidstash.command')"
echo "  Terminal: ./fbreels.sh \"https://www.youtube.com/@channel\""
