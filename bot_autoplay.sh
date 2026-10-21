#!/usr/bin/env bash
# перезапускает бота после каждого выхода, бесконечно.
# Остановить: Ctrl-C

DEATHS=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PY="python3"
if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
fi

cleanup() {
    echo ""
    echo "================================"
    echo "  Bot deaths: $DEATHS"
    echo "================================"
    exit 0
}

trap cleanup SIGINT

while true; do
    sleep 1
    "$PY" elite_autopilot.py
    # если бот завершился не по Ctrl-C (т.е. умер) — считаем
    if [ $? -ne 130 ]; then
        DEATHS=$((DEATHS + 1))
    fi
done
