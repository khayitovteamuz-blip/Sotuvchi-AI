#!/bin/bash
# Sotuvchi AI — local development server.
#
# Production runs the container's CMD (uvicorn with workers); this script is
# only for a developer machine.
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

VENV_PY="$DIR/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
    echo "❌ .venv topilmadi. Avval yarating:"
    echo "   uv venv --python 3.12 .venv"
    echo "   uv pip install --python .venv/bin/python -r requirements.txt"
    exit 1
fi

echo "========================================"
echo "🚀 Sotuvchi AI ishga tushmoqda..."
echo "========================================"

# Free the port if a previous run is still holding it. Local convenience only —
# it used to live in main.py, where it would have run inside the container too.
lsof -ti:${PORT:-8080} | xargs kill -9 2>/dev/null || true
sleep 1

# Run the venv's own interpreter. Never mix the system python3 with the venv's
# site-packages via PYTHONPATH — that pairs one Python's compiled modules with
# another's, which surfaces as baffling "module has no attribute X" errors.
exec "$VENV_PY" main.py
