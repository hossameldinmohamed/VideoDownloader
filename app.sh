#!/usr/bin/env bash
# Launch the web UI. Updates yt-dlp first (YouTube/Facebook change often and
# yt-dlp ships fixes within days), and relaunches when the app asks to restart.
#   ./app.sh               start normally
#   ./app.sh --no-update   skip the yt-dlp update check
#   ./app.sh --port 9000   use another port
set -uo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "First run — setting things up..."
  ./setup.sh || exit 1
fi
source .venv/bin/activate

UPDATE=1
ARGS=()
for a in "$@"; do
  if [ "$a" = "--no-update" ]; then UPDATE=0; else ARGS+=("$a"); fi
done

if [ "$UPDATE" = 1 ]; then
  echo "Checking for yt-dlp updates..."
  python -m pip install --quiet --disable-pip-version-check --upgrade "yt-dlp[default]" \
    || echo "(couldn't update yt-dlp — offline? continuing with the installed version)"
fi

while true; do
  python -m fbreels.web ${ARGS[@]+"${ARGS[@]}"}
  code=$?
  if [ "$code" -ne 3 ]; then exit "$code"; fi
  echo "Restarting..."
  ARGS+=("--no-browser")
done
