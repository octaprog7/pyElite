"""
pyElite — гиперпрыжки (обратная совместимость).

ВНИМАНИЕ: этот модуль больше НЕ содержит реализации. Полная логика
расчёта расстояния (_TT111), проверки прыжка (RANGE?) и расхода топлива
живёт в `elite_core.JumpEngine` (см. модуль elite_core.py и его docstring
со ссылками на src/):

- src/code_6a00.asm:1631-1724 (_TT111 — расстояние между системами);
- src/math/math_square.asm:203-247 (целочисленный квадратный корень);
- src/code_6a00.asm:1793-1799 (проверка прыжка RANGE?);
- src/code_6a00.asm:2222-2230 (_73dd — списание топлива);
- src/save_data.asm:160 (PLAYER_FUEL: 70 единиц = 7.0 св. лет).

Модуль оставлен как тонкая обёртка для обратной совместимости внешних
импортов (`from elite_jumps import Hyperdrive`). Результат execute_jump —
frozen dataclass `elite_core.JumpResult` (наследник ResultBase).
"""

from __future__ import annotations

from elite_core import (
    ENGINE_MAX_RANGE_UNITS,
    FUEL_TANK_CAPACITY,
    JumpEngine,
    JumpResult,
)

# Полная реализация — elite_core.JumpEngine. Имя сохранено для обратной
# совместимости (game_loop.py использует `Hyperdrive`).
Hyperdrive = JumpEngine

__all__ = [
    "Hyperdrive",
    "JumpResult",
    "FUEL_TANK_CAPACITY",
    "ENGINE_MAX_RANGE_UNITS",
]