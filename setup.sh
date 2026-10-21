#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Install Python 3.12+ first. See docs/SETUP-AGENT.md."; exit 1
fi
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else "Python 3.12+ required. Set PYTHON to a compatible interpreter.")'
if [ ! -d .venv ]; then "$PYTHON" -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; chmod 600 .env; fi
.venv/bin/python doctor.py
printf '\nNext: fill .env with your own keys, run bash start.command, then .venv/bin/python doctor.py --require-keys in another terminal\n'
