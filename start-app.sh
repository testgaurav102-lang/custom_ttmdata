#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "[setup] Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "[setup] Installing dependencies..."
pip install -q -r requirements.txt

if [ ! -f .env ]; then
    echo "[setup] Creating .env from .env.example..."
    cp .env.example .env
fi

echo "[start] Launching Sales Intel Agent..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1
