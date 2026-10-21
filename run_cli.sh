#!/usr/bin/env bash
#
# run_cli.sh — запуск CLI-версии «pyElite» (текстовый интерактив).
#
# По умолчанию стартует интерактивный цикл команд (GameLoop.run()):
#   ./run_cli.sh
#
# Опции:
#   --demo       запустить демо-сценарий (game_loop.py __main__) и выйти
#   -h | --help  показать эту справку
#
# Использует .venv/bin/python, если виртуальное окружение есть рядом,
# иначе системный python3. Логи: log/game_log.csv и elite_events.db.
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

case "${1:-}" in
    --demo)
        exec "$PY" game_loop.py
        ;;
    -h|--help)
        sed -n '2,11p' "${BASH_SOURCE[0]}"
        exit 0
        ;;
    *)
        # интерактивный цикл: ввод команд до quit / Ctrl-D / Ctrl-C
        exec "$PY" -c "from game_loop import GameLoop; GameLoop().run()"
        ;;
esac