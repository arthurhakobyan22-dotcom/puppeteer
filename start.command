#!/usr/bin/env bash
# Double-click to start Puppeteer: makes the virtualenv and installs the requirements the first time, then runs launch.py
# (the app on http://127.0.0.1:${PORT:-8770}; the callback tunnel only when Enhancor needs it). On an error the window stays open.
set -uo pipefail
cd "$(dirname "$0")" || { echo "Could not open the Puppeteer folder."; read -r -p "Press Return to close."; exit 1; }
pause() { echo; echo "$1"; echo "Fix the problem above, then double-click start.command again (or run: bash setup.sh)."; read -r -p "Press Return to close." _; exit 1; }
if [ ! -x .venv/bin/python ]; then
  PYTHON="${PYTHON:-python3}"
  command -v "$PYTHON" >/dev/null 2>&1 || pause "Python 3.12 or newer is not installed. Install it from python.org (or: brew install python), then start again."
  "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' || pause "Python 3.12 or newer is required; found $("$PYTHON" --version 2>&1)."
  echo "First start: creating the Python environment in .venv (one-time, about a minute)…"
  "$PYTHON" -m venv .venv || pause "The virtual environment could not be created."
  echo "Installing the requirements from requirements.txt…"
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt || pause "The requirements could not be installed."
  if [ ! -f .env ] && [ -f .env.example ]; then cp .env.example .env; chmod 600 .env; echo "Made .env from .env.example; add your keys there when you want to generate (preparing, editing and exporting work without them)."; fi
  echo "Done. Starting Puppeteer…"
fi
echo "Puppeteer · http://127.0.0.1:${PORT:-8770}  (Ctrl+C stops it)"
.venv/bin/python launch.py
status=$?
if [ "$status" -ne 0 ]; then echo; echo "Puppeteer stopped with an error (exit code $status). Read the lines above for the reason."; read -r -p "Press Return to close." _; fi
exit "$status"
