#!/usr/bin/env bash
# Patchbook - start on macOS or Linux:   ./start.sh      (or: bash start.sh)
# Uses the Python on this computer (3.10 or newer), installs Flask if it is
# missing, makes sure the iTailor library copy is present, and starts Patchbook.
set -e
cd "$(dirname "$0")"

PY=""
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi
if [ -z "$PY" ] && command -v python3 >/dev/null 2>&1; then PY="python3"; fi
if [ -z "$PY" ] && command -v python >/dev/null 2>&1; then PY="python"; fi
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer was not found. Install it (https://www.python.org/downloads/ or your package manager) and run this again."
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Patchbook needs Python 3.10 or newer; found: $("$PY" --version)"
  exit 1
fi
if ! "$PY" -c 'import flask' 2>/dev/null; then
  echo "Installing Flask, the only package Patchbook needs..."
  "$PY" -m pip install --user -q -r requirements.txt || "$PY" -m pip install -q -r requirements.txt
fi
if [ ! -f "itailor/__init__.py" ]; then
  echo "The iTailor library copy is missing; copying it from ../itailor ..."
  "$PY" sync_itailor.py
fi
echo
echo "Starting Patchbook. Keep this window open while you use it; press Ctrl+C to stop."
echo
exec "$PY" app.py
