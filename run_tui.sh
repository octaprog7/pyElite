#!/usr/bin/env bash
#
# run_tui.sh — запуск TUI-версии «pyElite» (Textual) из текущей папки.
#
# Требования: пакет textual (  pip install textual  или  pip install -e ".[tui]" ).
#
# Использует .venv/bin/python, если виртуальное окружение есть рядом,
# иначе системный python3.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    echo "Ошибка: python3 не найден (установите Python 3.10+)" >&2
    exit 1
fi

# Все аргументы (например, --lang en) передаются в elite_tui.py.
exec "$PY" elite_tui.py "$@"