"""
pyElite — детерминированный генератор галактик (обратная совместимость).

ВНИМАНИЕ: этот модуль больше НЕ содержит реализации. Полная логика
генерации галактик (регистр «Twins», LFSR, get_system_info/TT24, имена
систем, карта 256 систем) живёт в `elite_core.GalaxyGenerator`
(см. модуль elite_core.py и его docstring со ссылками на src/):

- src/code_6a00.asm:133-2784 (randomize_once, galactic_chart/TT22,
  get_system_info/TT24, _76e9 — имена систем);
- src/elite.inc:119, src/save_data.asm:158 (ELITE_SEED);
- src/text/text_pairs.asm:126-157 (32 пары букв);
- src/code_6a00.asm:1831 (_71e8 — поворот seed при переходе в галактику).

Модуль оставлен как тонкая обёртка для обратной совместимости внешних
импортов (`from elite_galaxy_generator import EliteGalaxyGenerator`).
Все таблицы данных определены ТОЛЬКО в elite_core.py.
"""

from __future__ import annotations

from elite_core import (
    ECONOMIES,
    GOVERNMENTS,
    NAME_PAIRS,
    SEED_GALAXY_0,
    GalaxyGenerator,
)

# Состояние генератора: 6 байт, порядок как в zero-page ($7F..$84):
#   [0]=W0_LO, [1]=W0_HI, [2]=W1_LO, [3]=W1_HI, [4]=W2_LO, [5]=W2_HI
Seed = list[int]

# Полная реализация — elite_core.GalaxyGenerator (единственный источник
# логики и таблиц данных). Имя сохранено для обратной совместимости.
EliteGalaxyGenerator = GalaxyGenerator

__all__ = [
    "EliteGalaxyGenerator",
    "Seed",
    "SEED_GALAXY_0",
    "NAME_PAIRS",
    "ECONOMIES",
    "GOVERNMENTS",
]