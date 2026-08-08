#!/bin/bash
# Sotuvchi AI - Start Script

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "========================================"
echo "🚀 Sotuvchi AI Serveri Ishga Tushmoqda..."
echo "📍 Veb-Sayt Manzili: http://127.0.0.1:8080"
echo "========================================"

export PYTHONPATH="$DIR/.venv/lib/python3.9/site-packages:$PYTHONPATH"
python3 main.py
