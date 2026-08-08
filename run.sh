#!/bin/bash
# Sotuvchi AI - Start Script

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "========================================"
echo "🚀 Sotuvchi AI Serveri Ishga Tushmoqda..."
echo "📍 Veb-Sayt Manzili: http://127.0.0.1:8080"
echo "========================================"

# Clean up port 8080 if previously occupied
lsof -ti:8080 | xargs kill -9 2>/dev/null || true
sleep 1

export PYTHONPATH="$DIR/.venv/lib/python3.9/site-packages:$PYTHONPATH"
python3 main.py
