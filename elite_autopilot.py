"""
elite_autopilot.py — автоматический бот-игрок для pyElite.

Бот играет напрямую через API ядра (elite_core.GameState) — без парсинга
CLI-вывода, без эмуляции клавиатуры, без `random` (всё детерминировано).

Стратегия:
  1. Продажа: если груз в трюме и текущая цена >= 90% от лучшей среди
     ближайших достижимых систем — продать (но не там, где куплено).
  2. Покупка: пустой трюм + прибыльный маршрут -> купить товар и позже
     прыгнуть к рынку сбыта. net_profit = profit_per_ton * max_qty - fuel_cost.
     Маршруты ниже MIN_PROFIT_PER_TON/MIN_NET_PROFIT отбрасываются; опасные
     целевые системы (Anarchy/Feudal) получают штраф к ожидаемой прибыли.
  3. Груз в трюме и текущая цена не лучшая -> прыжок к лучшему рынку сбыта.
  4. Топливо: держится резерв (зависит от risk_tolerance); заправка — перед
     прыжком, когда топлива не хватает.
  5. Бой: с памятью самообучения решение принимает Монте-Карло симуляция
      боя (_simulate_combat); без памяти — правила по щитам/правительству
      и risk_tolerance (low — всегда flee, high — fight с исключением для
      Anarchy при слабых щитах).
   6. Анти-застревание: система, посещённая 3+ раз подряд без прибыли,
      заменяется на исследовательский прыжок.
   7. Умный бот (1): перед прыжком в рискованную систему (P(атаки) >=
      DANGER_GUARD_P_ATTACK) — заправка до полного бака: вероятность
      успешного побега = min(255, fuel*3)/256, при 70 ед. это 210/256.
   8. Умный бот (2): оценка риска рейса И выбор боевого действия —
      Монте-Карло симуляция боя (_simulate_combat: точные вероятности
      смерти/потери груза/кредитов из CombatEngine.resolve, включая
      топливо ПОСЛЕ прыжка). Q-таблица боя и UCB1 маршрутов УДАЛЕНЫ
      (умный бот (5)): выученные приближения уступают точной модели.
   9. Умный бот (3): двухколенные торговые цепочки (_plan_chain: купить
      здесь -> продать в B -> купить в B -> продать в C). Рынки
      детерминированы, продолжение вычисляется точно; первое колено
      выбирается по прибыли на единицу топлива всей цепочки (_best_plan),
      что отдаёт предпочтение коленам, ведущим в богатые продолжением
      рынки, даже при скромной первой сделке.

Прогрессивная стратегия:
  * ранняя игра (credits < 500): только Food, Textiles, Minerals; прыжки до 5 ly;
  * средняя (500..2000): + Liquor/Wines, Computers, Machinery; прыжки до 6.5 ly;
  * поздняя (>= 2000): все товары, включая драгметаллы (с учётом PRECIOUS_LIMIT).

Замечание об импортах: спецификация задачи упоминала RouteFinder в списке
импортов из elite_core, но в ядре такого класса нет (RouteFinder живёт в
elite_analytics.py и не нужен боту) — модуль импортирует только существующие
символы elite_core. JumpEngine/GalaxyGenerator используются в аннотациях типов
и вспомогательных методах.

Лицензия: GPL v3.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from typing import Final

from elite_core import (
    COMMODITIES,
    FUEL_TANK_CAPACITY,
    PRECIOUS_LIMIT,
    SHIP_HOLD,
    CombatResult,
    DeterministicRNG,
    GalaxyGenerator,
    GameState,
    JumpEngine,
    MarketEngine,
    ShipDefense,
)

# --------------------------------------------------------------------------
# Константы
# --------------------------------------------------------------------------

# Цена топлива: 0.2 Cr/единица (elite_core.FUEL_PRICE_PER_UNIT_CR). Вынесена
# отдельно, чтобы не расширять список импортов из elite_core.
FUEL_PRICE_CR_PER_UNIT: Final[float] = 0.2

# Пороги прогрессивной стратегии (кредиты).
EARLY_GAME_CREDITS: Final[float] = 500.0
MID_GAME_CREDITS: Final[float] = 2000.0

# Порог цены продажи: продаём здесь, если текущая цена >= 90% от лучшей.
SELL_PRICE_THRESHOLD: Final[float] = 0.9

# Анти-застревание: система, посещённая столько раз подряд без прибыли,
# запускает исследовательский прыжок.
EXPLORE_VISIT_LIMIT: Final[int] = 3

# Сколько подряд раундов без прогресса (wait) — остановка бота.
# 10 = предохранитель для нетипичных случаев (истинные тупики
# детектируются отдельно через action "dead_end" → immediate exit).
# 0 = не останавливаться (НЕ рекомендуется).
STALL_LIMIT: Final[int] = 10

# Максимум маршрутов, возвращаемых _find_best_routes.
MAX_ROUTES: Final[int] = 10

# Умное планирование (3): двухколенная торговая цепочка (купить здесь ->
# продать в B -> купить в B -> продать в C). Рынки детерминированы, поэтому
# продолжение из B вычисляется точно. Первое колено выбирается по прибыли
# на единицу топлива ВСЕЙ цепочки, а не только её первого отрезка — это
# отдаёт предпочтение коленам, ведущим в богатые продолжением системы.
CHAIN_FIRST_LEGS: Final[int] = 8   # сколько лучших первых колен рассматривать

# Лимит кеша рынков целевых систем (при превышении — сброс: цены/доступность
# детерминированы, пересчитываются без потерь).
MARKET_CACHE_LIMIT: Final[int] = 64

# Доля груза, теряемая при бое без гибели (surrender/fight loss теряют 25%
# груза — elite_core.CombatEngine._lose_fraction(cargo, 0.25)). Полная
# стоимость груза теряется только при смерти (уже учтена через P(survive)
# в _expected_value), поэтому риск-вычет масштабируется этой долей.
LOSE_CARGO_FRACTION: Final[float] = 0.25

# Доля кредитов, теряемая при surrender (эмпирически из логов: 14-17 Cr
# при 10-100 Cr — примерно 15%). Учёт в _expected_value: штраф за потерю
# кредитов делает опасные маршруты отрицательными даже при большом объёме
# груза (когда LOSE_CARGO_FRACTION * cargo_value мал).
SURRENDER_CREDIT_FRACTION: Final[float] = 0.15

# Умный бот (1): перед прыжком в систему, где P(атаки) >= этого порога,
# бот дозаправляется до полного бака. Вероятность успешного побега =
# min(255, fuel*3)/256 (elite_core.CombatEngine.resolve "escape"): при
# полном баке (70 ед.) это 210/256 ~= 0.82, при 20 ед. — всего 60/256.
DANGER_GUARD_P_ATTACK: Final[float] = 0.10

# Умный бот (2): Монте-Карло оценка боя вместо грубых Q->вероятность
# конверсий (см. Autopilot._simulate_combat).
COMBAT_SIM_ROUNDS: Final[int] = 24        # прогонов resolve() на действие
COMBAT_SIM_CACHE_LIMIT: Final[int] = 512  # лимит кеша симуляций

# Минимальные кредиты для продолжения exploration. Если нет прибыльного
# маршрута и кредиты ниже этого порога — dead_end (рестарт с 100 Cr лучше,
# чем медленная смерть от заправок и пиратских атак).
CREDIT_FLOOR: Final[float] = 50.0

# Минимальный запас топлива (единиц), при котором разрешены прыжки.
# 5 единиц = 0.5 ly — позволяет 2 коротких прыжка (3.2 ly каждый) без
# заправки: 70 -> 38 -> 6. С reserve=10 бот заправляется после КАЖДОГО
# прыжка 3+ ly (70 -> 38, 38-32=6 < 10 -> refuel), удваивая затраты на
# топливо. Reserve=5 позволяет цепочку прыжков без заправки.
MIN_FUEL_RESERVE: Final[int] = 5

# Идентификатор версии бота. Новая версия = новый PLAYER_ID — данные
# в БД не смешиваются, файлы БД не удаляются. Старые данные остаются
# с player_id=0, новая версия учится с чистого листа.
PLAYER_ID: Final[int] = 2

# Категории товаров по стадиям игры (индексы COMMODITIES):
#   0 Food, 1 Textiles, 12 Minerals — дешёвые (ранняя игра);
#   4 Liquor/Wines, 7 Computers, 8 Machinery — средняя игра.
_CHEAP_COMMODITIES: Final[tuple[int, ...]] = (0, 1, 12)
_MID_COMMODITIES: Final[tuple[int, ...]] = (4, 7, 8)

# Минимальные пороги прибыли: ниже не торгуем.
MIN_PROFIT_PER_TON: Final[float] = 2.0   # Cr/ton — минимальная маржа за тонну
MIN_NET_PROFIT: Final[float] = 5.0       # Cr — минимум чистой прибыли за рейс
# Ранняя игра (до EARLY_GAME_CREDITS): в стартовых системах (Agricultural)
# маржа по Food/Textiles ~1.2 Cr/ton — порог 2.0 сделал бы торговлю
# невозможной. 1.0 Cr/ton отсекает копеечные маржи (0.40), но допускает
# нормальные ранние сделки.
EARLY_MIN_PROFIT_PER_TON: Final[float] = 1.0

# Опасные правительства (индексы elite_core; чем выше риск пиратов, тем
# дороже бой):
#   0=Anarchy, 1=Feudal, 2=Multi-Government — flee всегда;
#   3=Dictatorship, 4=Communist — fight только при полных щитах;
#   5=Confederacy, 6=Democracy, 7=Corporate — можно fight.
DANGEROUS_GOV: Final[frozenset[int]] = frozenset({0, 1, 2})
MODERATE_GOV: Final[frozenset[int]] = frozenset({3, 4})

# --------------------------------------------------------------------------
# Умный бот (4): автооптимизация констант (координатный спуск по прогонам).
# Ядро детерминировано -> качество набора констант измеряется точно:
# средняя прибыль на прогоне. Константы читаются ботом через Autopilot.
# _tuned() (переопределение экземпляра), ниже — дефолты и сетки значений.
# --------------------------------------------------------------------------

_TUNABLE_DEFAULTS: Final[dict[str, float]] = {
    "SELL_PRICE_THRESHOLD": SELL_PRICE_THRESHOLD,
    "MIN_PROFIT_PER_TON": MIN_PROFIT_PER_TON,
    "MIN_NET_PROFIT": MIN_NET_PROFIT,
    "EARLY_MIN_PROFIT_PER_TON": EARLY_MIN_PROFIT_PER_TON,
    "MIN_FUEL_RESERVE": float(MIN_FUEL_RESERVE),
    "DANGER_GUARD_P_ATTACK": DANGER_GUARD_P_ATTACK,
    "EXPLORE_VISIT_LIMIT": float(EXPLORE_VISIT_LIMIT),
}

# Сетки значений координатного спуска (абсолютные значения).
_TUNABLE_GRID: Final[dict[str, tuple[float, ...]]] = {
    "SELL_PRICE_THRESHOLD": (0.75, 0.8, 0.85, 0.9, 0.95, 1.0),
    "MIN_PROFIT_PER_TON": (1.0, 1.5, 2.0, 3.0, 4.0),
    "MIN_NET_PROFIT": (2.0, 5.0, 10.0, 20.0, 40.0),
    "EARLY_MIN_PROFIT_PER_TON": (0.5, 0.75, 1.0, 1.5, 2.0),
    "MIN_FUEL_RESERVE": (2.0, 5.0, 10.0, 15.0, 20.0),
    "DANGER_GUARD_P_ATTACK": (0.05, 0.1, 0.2, 0.3, 0.5),
    "EXPLORE_VISIT_LIMIT": (1.0, 2.0, 3.0, 4.0, 6.0),
}


# --------------------------------------------------------------------------
# Dataclass'ы результата
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeRoute:
    """Прибыльный торговый маршрут: купить здесь, продать там."""

    from_index: int
    to_index: int
    commodity_index: int
    commodity_name: str
    buy_price: float
    sell_price: float
    profit_per_ton: float
    fuel_cost: int            # единиц топлива (0.1 ly каждая)
    distance_ly: float
    max_qty: int
    net_profit: float         # profit_per_ton * max_qty - fuel_cost*price
    chain_fuel: int = 0       # суммарное топливо цепочки (0 = одно колено)


@dataclass(frozen=True)
class BotDecision:
    """Решение бота на один ход (action: buy/sell/jump/refuel/flee/fight/
    surrender/wait/dead_end)."""

    action: str
    details: dict[str, object] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class CombatSimStats:
    """Агрегат Монте-Карло симуляции боя (Autopilot._simulate_combat)."""

    action: str          # лучшее действие по средней награде (_combat_reward)
    p_death: float       # доля симуляций с уничтожением корабля
    cargo_frac: float    # средняя доля потерянного груза (выжившие исходы)
    credit_frac: float   # средняя доля потерянных кредитов (выжившие исходы)


@dataclass(frozen=True)
class TuneResult:
    """Результат автооптимизации констант (optimize_constants)."""

    best: dict[str, float]   # оптимизированный набор констант
    score: float             # средняя прибыль на прогон, Cr
    history: list[tuple[str, float, float]] = field(default_factory=list)
    # history: (параметр, значение, score) — только улучшения
    log_lines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BotResult:
    """Итоговый отчёт бота после run()."""

    rounds_played: int
    final_credits: float
    starting_credits: float
    profit: float
    roi_pct: float
    jumps_made: int
    combats_encountered: int
    combats_won: int
    combats_fled: int
    log_lines: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# BotMemory — персистентная Bayesian-память систем (SQLite)
# --------------------------------------------------------------------------


class BotMemory:
    """Персистентная память бота (SQLite, только stdlib).

    Умный бот (5): после перехода боя на Монте-Карло симуляцию
    (_simulate_combat — точные вероятности из ядра) и маршрутов на
    детерминированный EV из памяти УБРАНЫ Q-таблица боя и UCB1-статистика
    маршрутов — выученные приближения стали избыточны и лишь замедляли
    адаптацию (Q-состояние не включало топливо, UCB1 форсировал прыжки в
    заведомо слабые системы). Оставлена ТОЛЬКО Bayesian-статистика систем
    (Beta-распределение по фактическим атакам с prior по правительству) —
    для количественной валидации модели: предсказанная частота атак
    (_attack_probability) сравнивается с наблюдаемой.

    Старые БД (таблицы combat_q/route_stats/meta) игнорируются: не
    читаются и не пишутся, но и не удаляются.

    Fallback: если BotMemory не передан в Autopilot (memory_db=None) —
    бот играет по прежним правилам.
    """

    def __init__(self, db_path: str = "bot_memory.db", player_id: int = 0) -> None:
        self._conn: sqlite3.Connection = sqlite3.connect(db_path)
        self.player_id: int = int(player_id)
        self._init_tables()
        self._migrate_player_id()

    # ------------------------------------------------------------- schema

    def _init_tables(self) -> None:
        """Таблица system_stats (Bayesian-статистика визитов/атак)."""
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS system_stats ("
            "  player_id INTEGER NOT NULL DEFAULT 0,"
            "  system_index INTEGER NOT NULL,"
            "  visits INTEGER NOT NULL DEFAULT 0,"
            "  attacks INTEGER NOT NULL DEFAULT 0,"
            "  PRIMARY KEY (player_id, system_index))")
        self._conn.commit()

    def _migrate_player_id(self) -> None:
        """Миграция старых БД: player_id в PK system_stats.

        Старые таблицы combat_q/route_stats/meta (если есть) игнорируются:
        Q-learning и UCB1 удалены из бота (умный бот (5)).

        ВАЖНО: ALTER TABLE ADD COLUMN не меняет PRIMARY KEY, поэтому для
        старой таблицы (PK без player_id) простого ALTER недостаточно —
        INSERT ... ON CONFLICT(player_id, ...) не нашёл бы подходящего
        уникального индекса. Таблица пересоздаётся с новым PK и переносом
        данных: все строки старой БД получают player_id=0.
        """
        create_sql = (
            "CREATE TABLE system_stats ("
            "  player_id INTEGER NOT NULL DEFAULT 0,"
            "  system_index INTEGER NOT NULL,"
            "  visits INTEGER NOT NULL DEFAULT 0,"
            "  attacks INTEGER NOT NULL DEFAULT 0,"
            "  PRIMARY KEY (player_id, system_index))")
        copy_sql = (
            "INSERT INTO system_stats "
            "(player_id, system_index, visits, attacks) "
            "SELECT 0, system_index, visits, attacks FROM system_stats_old")
        try:
            cols = [r[1] for r in self._conn.execute(
                'PRAGMA table_info(system_stats)').fetchall()]
        except sqlite3.OperationalError:
            return  # таблицы нет — _init_tables создаст её с новой схемой
        if 'player_id' in cols:
            return  # схема уже новая — ничего делать не нужно
        # Старая таблица (PK без player_id): пересоздаём с переносом.
        self._conn.execute('ALTER TABLE system_stats RENAME TO system_stats_old')
        self._conn.execute(create_sql)
        self._conn.execute(copy_sql)
        self._conn.execute('DROP TABLE system_stats_old')
        self._conn.commit()

    # ------------------------------------------------------------- helpers

    def _get_system_stats(self, system_index: int) -> dict[str, int]:
        row = self._conn.execute(
            "SELECT visits, attacks FROM system_stats "
            "WHERE player_id = ? AND system_index = ?",
            (self.player_id, system_index)).fetchone()
        if row is None:
            return {"visits": 0, "attacks": 0}
        return {"visits": int(row[0]), "attacks": int(row[1])}

    def _save_system_stats(
        self, system_index: int, stats: dict[str, int]
    ) -> None:
        self._conn.execute(
            "INSERT INTO system_stats "
            "(player_id, system_index, visits, attacks) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(player_id, system_index) DO UPDATE SET "
            "visits = excluded.visits, attacks = excluded.attacks",
            (self.player_id, system_index, stats["visits"], stats["attacks"]))
        self._conn.commit()

    # -------------------------------------------------- Bayesian (systems)

    def danger_score(self, system_index: int, government: int = 7) -> float:
        """Байесова вероятность атаки: Beta(alpha, beta).

        Без фактических данных используется prior по правительству
        (Anarchy/Feudal опаснее Democracy/Corporate); с опытом оценка
        смещается в сторону реальной частоты атак.
        """
        stats = self._get_system_stats(system_index)
        if stats["visits"] == 0:
            if government <= 2:
                stats = {"visits": 10, "attacks": 5}
            elif government <= 4:
                stats = {"visits": 10, "attacks": 2}
            else:
                stats = {"visits": 20, "attacks": 1}
        alpha = stats["attacks"] + 1
        beta = stats["visits"] - stats["attacks"] + 1
        return alpha / (alpha + beta)

    def record_visit(self, system_index: int, attacked: bool) -> None:
        """Зафиксировать визит в систему (при атаке — и счётчик атак)."""
        stats = self._get_system_stats(system_index)
        stats["visits"] += 1
        if attacked:
            stats["attacks"] += 1
        self._save_system_stats(system_index, stats)

    def record_attack(self, system_index: int) -> None:
        """Увеличить счётчик атак (без нового визита)."""
        stats = self._get_system_stats(system_index)
        stats["attacks"] += 1
        self._save_system_stats(system_index, stats)

    # ------------------------------------------------------------- lifecycle

    def close(self) -> None:
        """Закрыть соединение с БД (ошибки игнорируются)."""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


# --------------------------------------------------------------------------
# Autopilot
# --------------------------------------------------------------------------


class Autopilot:
    """Автономный бот: принимает решения через API GameState.

    Параметры:
        game_state: состояние игры (elite_core.GameState);
        max_rounds: лимит ходов; 0 = бесконечный режим (остановка только
            по Ctrl-C);
        risk_tolerance: "low" | "medium" | "high" —
            low — всегда flee, прыжки до 5 ly, строгий топливный резерв;
            medium — умный бой по правительству системы: в Anarchy/Feudal
                flee, в Dictatorship/Communist fight только при полных
                щитах, в безопасных — fight при energy >= 50% и FSH >= 100;
                прыжки до 6.5 ly;
            high — fight (в Anarchy при слабых щитах — flee), прыжки до
                предела движка, малый резерв;
        log_file: путь для персистентного лога (None — только в память);
        memory_db: путь к SQLite-памяти BotMemory (None — отключить;
            Bayesian-статистика систем, см. BotMemory);
        player_id: идентификатор версии бота — данные разных версий в БД
            не смешиваются (см. PLAYER_ID; старые данные остаются с 0);
        verbose: печатать лог в stdout.
    """

    def __init__(
        self,
        game_state: GameState,
        max_rounds: int = 0,
        risk_tolerance: str = "medium",
        log_file: str | None = None,
        memory_db: str | None = "bot_memory.db",
        player_id: int = 0,
        verbose: bool = True,
        tunables: dict[str, float] | None = None,
    ) -> None:
        if risk_tolerance.lower() not in ("low", "medium", "high"):
            raise ValueError(
                f"risk_tolerance must be 'low'|'medium'|'high', got {risk_tolerance!r}"
            )
        self.state: GameState = game_state
        # 0 = бесконечный режим (только Ctrl-C); положительное значение —
        # жёсткий лимит раундов (обратная совместимость).
        self.max_rounds: int = int(max_rounds) if int(max_rounds) > 0 else 0
        self.risk_tolerance: str = risk_tolerance.lower()
        self.log_file: str | None = log_file
        self.verbose: bool = verbose
        # Умный бот (4): переопределение констант (optimize_constants);
        # пустой dict — значения по умолчанию (_TUNABLE_DEFAULTS).
        self._tunables: dict[str, float] = dict(tunables) if tunables else {}
        # Bayesian-память систем (частота атак); None — без статистики.
        self._memory: BotMemory | None = (
            BotMemory(memory_db, player_id) if memory_db else None)

        self._log_lines: list[str] = []
        # Где куплен каждый товар (commodity_index -> system_index).
        self._bought_at: dict[int, int] = {}
        # Цена покупки каждого товара (commodity_index -> Cr/unit) — для
        # отладки/логирования.
        self._bought_price: dict[int, float] = {}
        # Счётчик посещений системы подряд без прибыли (анти-застревание).
        self._visits: dict[int, int] = {}
        # Кеш рынков целевых систем (read-only; доступность не коммитится).
        self._market_cache: dict[int, MarketEngine] = {}
        # Ожидающая продажа (из _plan_sell -> в _execute_sell).
        self._pending_sell: dict[str, int | float] | None = None
        # Атака пиратов проверяется в ходу, следующем за прыжком (как в
        # оригинале: встреча происходит при прибытии в систему).
        self._just_jumped: bool = False
        # Кеш Монте-Карло симуляций боя (ключ: gov + бакеты щитов/энергии +
        # бакет топлива + tech_level; см. _simulate_combat).
        self._combat_sim_cache: dict[
            tuple[int, int, int, int, int, int], CombatSimStats
        ] = {}

        self._jumps_made: int = 0
        self._combats_encountered: int = 0
        self._combats_won: int = 0
        self._combats_fled: int = 0

    def _tuned(self, name: str) -> float:
        """Умный бот (4): настраиваемая константа — значение оптимизатора
        (self._tunables) или дефолт модуля (_TUNABLE_DEFAULTS)."""
        return self._tunables.get(name, _TUNABLE_DEFAULTS[name])

    # ------------------------------------------------------------- logging

    def _log(self, msg: str, level: str = "info") -> None:
        """Записать строку в лог (память + опционально файл и stdout)."""
        line = f"[{level.upper()}] {msg}" if level != "info" else msg
        self._log_lines.append(line)
        if self.verbose:
            print(line)
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

    # ------------------------------------------------------------- helpers

    def _market_of(self, system_index: int) -> MarketEngine:
        """Рынок системы (кешируется; для текущей — живой state.market).

        ВАЖНО: инстансы целевых систем используются только для чтения цен;
        commit_buy для них никогда не выполняется.
        """
        if system_index == self.state.system_index:
            return self.state.market
        cached = self._market_cache.get(system_index)
        if cached is None:
            cached = MarketEngine(
                self.state.generator, system_index, self.state.galaxy
            )
            # Ограничение кеша: при превышении MARKET_CACHE_LIMIT записей
            # сбрасываем его (рынки детерминированы — пересчёт бесплатен).
            if len(self._market_cache) > MARKET_CACHE_LIMIT:
                self._market_cache.clear()
            self._market_cache[system_index] = cached
        return cached

    def _jump_engine(self) -> JumpEngine:
        """Гипердрайв текущей галактики (эквивалент state.jump_engine)."""
        return self.state.jump_engine

    def _generator(self) -> GalaxyGenerator:
        """Детерминированный генератор галактик (state.generator)."""
        return self.state.generator

    def _cargo_space(self) -> int:
        """Свободные тонны трюма (драгметаллы тонны не занимают)."""
        return max(SHIP_HOLD - self.state.cargo_weight, 0)

    def _has_cargo(self) -> bool:
        """Есть ли что-нибудь в трюме (включая драгметаллы)."""
        st = self.state
        return st.cargo_weight > 0 or any(st.cargo[13:16])

    def _max_jump_ly(self) -> float:
        """Максимальная дальность прыжка по risk_tolerance и стадии игры."""
        if self.risk_tolerance == "low":
            return 5.0
        if self.risk_tolerance == "high":
            return 7.0
        # medium: ранняя игра осторожнее
        return 5.0 if self.state.credits < EARLY_GAME_CREDITS else 6.5

    def _fuel_reserve_units(self, fuel_cost: int) -> int:
        """Топливный резерв после прыжка (единиц; 10 ед. = 1 св. год).

        ВАЖНО: резерв должен быть МАЛЫМ у medium/high. Резерв вида
        fuel_cost//2 требовал бы fuel >= 1.5*cost и физически ограничивал
        дальность прыжка 4.6 ly даже с полным баком (70 ед.) — вопреки
        _max_jump_ly() (5.0-6.5 ly) и комментарию к MIN_FUEL_RESERVE.
        Заправка до полного бака дешева (<= 14 Cr) и выполняется на месте
        (в т.ч. guard'ом _pre_jump_refuel перед рискованным прыжком),
        поэтому таскать «топливо на обратный путь» не нужно.
        """
        if self.risk_tolerance == "low":
            return fuel_cost          # полный возврат (осторожный режим)
        return int(self._tuned("MIN_FUEL_RESERVE"))  # medium/high

    def _enough_fuel_with_reserve(
        self, target: int, fuel_cost: int | None = None
    ) -> bool:
        """Хватит ли топлива на прыжок с учётом резерва."""
        st = self.state
        if fuel_cost is None:
            fuel_cost = st.jump_engine.calculate_fuel_cost(
                st.system_index, target
            )
        fuel_after: int = int(round(st.fuel)) - fuel_cost
        return fuel_after >= self._fuel_reserve_units(fuel_cost)

    def _can_refuel(self) -> bool:
        """Достаточно ли денег на заправку до полного бака."""
        fuel = int(round(self.state.fuel))
        if fuel >= FUEL_TANK_CAPACITY:
            return False
        cost: float = (FUEL_TANK_CAPACITY - fuel) * FUEL_PRICE_CR_PER_UNIT
        return self.state.credits >= cost

    # ------------------------------------------------------------- risk

    def _attack_probability(self, target: int) -> float:
        """Вероятность пиратской атаки в target (DRY для фильтров и EV)."""
        target_gov = int(self._market_of(target).system["government"])
        if self._memory is not None:
            return self._memory.danger_score(target, target_gov)
        if target_gov in DANGEROUS_GOV:
            return 0.5
        if target_gov in MODERATE_GOV:
            return 0.25
        return 0.05

    @staticmethod
    def _shield_bucket(value: int) -> int:
        """Бакет щита/энергии для ключа кеша симуляций (0-4)."""
        if value < 64:
            return 0
        if value < 128:
            return 1
        if value < 192:
            return 2
        if value < 255:
            return 3
        return 4

    @staticmethod
    def _fuel_bucket(fuel_units: int) -> int:
        """Бакет топлива для ключа кеша симуляций (0-4).

        Вероятность побега min(255, fuel*3)/256 линейна по fuel, поэтому
        достаточно грубых бакетов.
        """
        if fuel_units <= 10:
            return 0
        if fuel_units <= 25:
            return 1
        if fuel_units <= 45:
            return 2
        if fuel_units <= 60:
            return 3
        return 4

    def _simulate_combat(
        self, gov: int, fuel_units: int, tech_level: int
    ) -> CombatSimStats:
        """Монте-Карло симуляция боя (детерминированная, без `random`).

        Для каждого действия (fight/flee/surrender) прогоняется
        COMBAT_SIM_ROUNDS вызовов CombatEngine.resolve() на КОПИИ защиты
        корабля и DeterministicRNG с фиксированными seed'ами (детерминизм:
        одинаковый вход -> одинаковый результат, state.rng не тратится).
        Выбирается действие с максимальной средней наградой (_combat_reward)
        — EV оценивает рейс, на котором бот играет оптимально.

        Аргументы: gov — правительство системы БОЯ (целевой системы),
        fuel_units — топливо к моменту боя (после прыжка), tech_level —
        техуровень целевой системы (влияет на шанс победы в fight).

        Результат кешируется по (gov, бакеты щитов/энергии, бакет топлива,
        tech_level). Доли потерь — относительные величины: синтетический
        груз [40]*17 даёт точную долю (int(40*0.75)=30 -> ровно 25% при
        f=0.25 и 34/40=15% при f=0.15).
        """
        d = self.state.defense
        key = (
            int(gov) & 0x07,
            self._shield_bucket(int(d.forward_shield)),
            self._shield_bucket(int(d.aft_shield)),
            self._shield_bucket(int(d.energy)),
            self._fuel_bucket(max(0, int(fuel_units))),
            int(tech_level) & 0x0F,
        )
        cached = self._combat_sim_cache.get(key)
        if cached is not None:
            return cached
        if len(self._combat_sim_cache) >= COMBAT_SIM_CACHE_LIMIT:
            self._combat_sim_cache.clear()

        credits_base: float = max(self.state.credits, 1.0)
        cargo_template: list[int] = [40] * len(COMMODITIES)
        cargo_total: float = float(sum(cargo_template))

        best: tuple[float, CombatSimStats] | None = None
        for action in ("fight", "flee", "surrender"):
            # Ядро принимает "escape", а не "flee" (семантическое имя бота).
            core_action = "escape" if action == "flee" else action
            reward_sum = 0.0
            deaths = 0
            survivors = 0
            cargo_frac_sum = 0.0
            credit_frac_sum = 0.0
            for i in range(COMBAT_SIM_ROUNDS):
                rng = DeterministicRNG((
                    1009 + 7919 * i, 1013 + 104729 * i,
                    101 + 1299709 * i, 7 + 15485863 * i,
                ))
                defense = ShipDefense(
                    forward_shield=int(d.forward_shield),
                    aft_shield=int(d.aft_shield),
                    energy=int(d.energy),
                )
                outcome: CombatResult = self.state.combat_engine.resolve(
                    core_action, rng,
                    fuel=float(max(0, fuel_units)),
                    credits=credits_base,
                    cargo=list(cargo_template),
                    tech_level=int(tech_level) & 0xFF,
                    defense=defense,
                )
                reward_sum += self._combat_reward(action, outcome)
                if outcome.destroyed:
                    deaths += 1
                    continue
                survivors += 1
                cargo_frac_sum += (
                    sum(outcome.cargo_lost) / cargo_total)
                credit_frac_sum += outcome.credits_lost / credits_base
            stats = CombatSimStats(
                action=action,
                p_death=deaths / COMBAT_SIM_ROUNDS,
                cargo_frac=(
                    cargo_frac_sum / survivors if survivors else 0.0),
                credit_frac=(
                    credit_frac_sum / survivors if survivors else 0.0),
            )
            avg_reward = reward_sum / COMBAT_SIM_ROUNDS
            if best is None or avg_reward > best[0]:
                best = (avg_reward, stats)
        assert best is not None
        self._combat_sim_cache[key] = best[1]
        return best[1]

    def _expected_value(
        self, target: int, gross_profit: float, cargo_value: float = 0.0
    ) -> float:
        """Risk-adjusted expected value рейса в target.

        expected = gross_profit * P(survive)
                   - cargo_value * P(attack) * P(lose_cargo)
                   - credits * P(attack) * P(lose_credits)

        Вероятности берутся из точных моделей ядра (не из грубых констант):
        - P(attack) — Bayesian danger_score (BotMemory) или prior по
          правительству (0.5 Anarchy/Feudal, 0.25 moderate, 0.09 safe);
        - P(death) / P(lose_cargo) / P(lose_credits) — Монте-Карло симуляция
          боя (_simulate_combat): лучшее действие по средней награде,
          побег учитывает фактическое топливо ПОСЛЕ прыжка (успех =
          rng.next_byte() < min(255, fuel*3)).

        При cargo_value = 0 (пустой трюм, exploration) учитывается только
        выживание и потери кредитов. Если результат <= 0 — рейс невыгоден
        (риск превышает прибыль).
        """
        target_system = self._market_of(target).system
        target_gov = int(target_system["government"])
        p_attack: float = self._attack_probability(target)

        # Бой происходит ПОСЛЕ прыжка: топливо к моменту боя уменьшено
        # на расход прыжка (это сильно влияет на вероятность побега).
        fuel_after: int = max(
            0,
            int(round(self.state.fuel))
            - self.state.jump_engine.calculate_fuel_cost(
                self.state.system_index, target),
        )
        sim = self._simulate_combat(
            target_gov, fuel_after, int(target_system["tech_level"]))

        p_survive = 1.0 - p_attack * sim.p_death
        expected = (
            gross_profit * p_survive
            - cargo_value * p_attack * sim.cargo_frac
            - self.state.credits * p_attack * sim.credit_frac
        )
        return expected

    def _allowed_commodities(self) -> list[int]:
        """Товары, доступные на текущей стадии игры (индексы COMMODITIES)."""
        credits = self.state.credits
        allowed: list[int] = list(_CHEAP_COMMODITIES)
        if credits >= EARLY_GAME_CREDITS:
            allowed.extend(_MID_COMMODITIES)
        if credits >= MID_GAME_CREDITS:
            allowed = list(range(16))  # все, кроме Alien Items (16)
        return allowed

    # ------------------------------------------------------------- market

    def _analyze_market(self, system_index: int) -> dict[str, object]:
        """Снимок рынка системы: цены, доступность, лучшие сделки.

        Возвращает dict с ключами: system_index, name, economy, government,
        rows (17 строк), best_sell (товар с самой высокой ценой),
        best_buy (самый дешёвый товар), total_available.
        """
        market = self._market_of(system_index)
        rows = market.get_market()
        priced = [
            (i, float(row["price_buy_cr"]), int(row["available"]))
            for i, row in enumerate(rows)
        ]
        available = [(i, p, a) for i, p, a in priced if a > 0]
        best_sell = max(available, key=lambda t: t[1], default=(0, 0.0, 0))
        best_buy = min(priced, key=lambda t: t[1], default=(0, 0.0, 0))
        return {
            "system_index": system_index,
            "name": str(market.system["name"]),
            "economy": str(market.system["economy_name"]),
            "government": int(market.system["government"]),
            "rows": rows,
            "best_sell": best_sell,
            "best_buy": best_buy,
            "total_available": sum(a for _, _, a in available),
        }

    # ------------------------------------------------------------- routes

    def _raw_routes(self) -> list[TradeRoute]:
        """Одноколенные маршруты без UCB1-перезаписи (все колена, без топ-10).

        Для каждой пары (товар, достижимая система): buy_price здесь,
        sell_price там (через отдельный MarketEngine — только чтение!),
        profit_per_ton, max_qty = min(available, место, деньги), net_profit =
        profit_per_ton * max_qty - fuel_cost. Фильтры: маржа >=
        MIN_PROFIT_PER_TON, чистая прибыль >= MIN_NET_PROFIT, прыжок в
        пределах max_jump_ly и топливного резерва. Риск цели учитывается
        risk-adjusted EV (_expected_value).
        """
        st = self.state
        here = st.system_index
        cargo_space = self._cargo_space()
        routes: list[TradeRoute] = []

        # Достижимые системы с фильтром дальности.
        near: list[tuple[int, str, int, int]] = []
        for index, name, dist_units, cost in st.near_systems():
            if dist_units / 10.0 > self._max_jump_ly():
                continue
            if not self._enough_fuel_with_reserve(index, cost):
                continue
            near.append((index, name, dist_units, cost))
        if not near:
            return routes

        allowed = self._allowed_commodities()
        for ci in allowed:
            avail = st.market.available(ci)
            if avail <= 0:
                continue
            buy_price = st.market.price_cr(ci)
            if buy_price <= 0:
                continue
            # Порог маржи: ранняя игра мягче (см. EARLY_MIN_PROFIT_PER_TON).
            min_profit_per_ton = (
                min(self._tuned("MIN_PROFIT_PER_TON"),
                    self._tuned("EARLY_MIN_PROFIT_PER_TON"))
                if st.credits < EARLY_GAME_CREDITS
                else self._tuned("MIN_PROFIT_PER_TON")
            )
            for target, _name, dist_units, fuel_units in near:
                sell_price = self._market_of(target).price_cr(ci)
                profit_per_ton = sell_price - buy_price
                if profit_per_ton < min_profit_per_ton:
                    continue
                # Стоимость топлива для прыжка = долив до нужного уровня
                # (если бак уже полон — топливо бесплатно).
                fuel_needed = max(0, fuel_units - int(round(st.fuel)))
                fuel_cost_cr = fuel_needed * FUEL_PRICE_CR_PER_UNIT
                # Бюджет: из кредитов резервируем стоимость долива топлива,
                # чтобы после покупки остались деньги на перелёт.
                budget = st.credits - fuel_cost_cr
                if budget <= 0:
                    continue
                # Вместимость: тонны (<=12) — трюм; драгметаллы — PRECIOUS_LIMIT.
                if ci <= 12:
                    max_qty = min(avail, cargo_space)
                else:
                    max_qty = min(avail, PRECIOUS_LIMIT)
                max_qty = min(max_qty, int(budget // buy_price))
                if max_qty <= 0:
                    continue
                net_profit = profit_per_ton * max_qty - fuel_cost_cr
                # Risk-adjusted expected value: единая оценка риска рейса
                # (вероятность атаки x смерть/потерю груза) для всех систем.
                cargo_value = buy_price * max_qty   # стоимость груза
                net_profit = self._expected_value(
                    target, net_profit, cargo_value)
                if net_profit < self._tuned("MIN_NET_PROFIT"):
                    continue
                routes.append(TradeRoute(
                    from_index=here,
                    to_index=target,
                    commodity_index=ci,
                    commodity_name=COMMODITIES[ci],
                    buy_price=buy_price,
                    sell_price=sell_price,
                    profit_per_ton=profit_per_ton,
                    fuel_cost=fuel_units,
                    distance_ly=dist_units / 10.0,
                    max_qty=max_qty,
                    net_profit=net_profit,
                ))

        return routes

    def _find_best_routes(self) -> list[TradeRoute]:
        """Лучшие торговые маршруты из текущей системы (топ-10 по net_profit).

        Умный бот (5): UCB1-перезапись удалена — рынок детерминирован,
        точный EV (_raw_routes) не оставляет explore/exploit-компромисса.
        Для ВЫБОРА покупки в _plan_turn используется _best_plan (EV +
        двухколенные цепочки).
        """
        routes = self._raw_routes()
        routes.sort(key=lambda r: r.net_profit, reverse=True)
        return routes[:MAX_ROUTES]

    def _neighbors(self, system_index: int, max_ly: float) -> list[tuple[int, int]]:
        """Соседи произвольной системы: [(target, расход топлива)], сортировка
        по расходу. Отличается от state.near_systems() тем, что не зависит
        от текущей позиции бота (нужно для продолжения цепочки из B)."""
        jump = self.state.jump_engine
        max_units = int(max_ly * 10)
        result: list[tuple[int, int]] = []
        for i in range(256):
            if i == system_index:
                continue
            if not jump.can_jump(system_index, i, FUEL_TANK_CAPACITY):
                continue
            dist = jump.distance_units(system_index, i)
            if dist > max_units:
                continue
            result.append((i, dist & 0xFF))
        result.sort(key=lambda t: t[1])
        return result

    def _continuation_profit(self, at_index: int, credits: float) -> tuple[float, int]:
        """Лучшее второе колено из at_index: (EV-прибыль, расход топлива).

        Чистое вычисление на детерминированном рынке at_index (состояние
        не изменяется). Предполагается: к моменту продажи в at_index трюм
        пуст (всё продано), кредиты = credits, топливо долито до полного
        бака (дёшево, guard _pre_jump_refuel). Риск цели — risk-adjusted EV;
        топливо для симуляции берётся приближённо (от текущей позиции) —
        консервативная оценка побега.
        """
        max_ly = self._max_jump_ly()
        best_profit, best_fuel = 0.0, 0
        for target, cost in self._neighbors(at_index, max_ly):
            target_market = self._market_of(target)
            for ci in self._allowed_commodities():
                avail = self._market_of(at_index).available(ci)
                if avail <= 0:
                    continue
                buy_price = self._market_of(at_index).price_cr(ci)
                if buy_price <= 0:
                    continue
                margin = target_market.price_cr(ci) - buy_price
                if margin < self._tuned("MIN_PROFIT_PER_TON"):
                    continue
                if ci <= 12:
                    max_qty = min(avail, SHIP_HOLD)
                else:
                    max_qty = min(avail, PRECIOUS_LIMIT)
                qty = min(max_qty, int(credits // buy_price))
                if qty <= 0:
                    continue
                gross = margin * qty
                fuel_cost_cr = cost * FUEL_PRICE_CR_PER_UNIT
                net = gross - fuel_cost_cr
                if net <= 0:
                    continue
                ev = self._expected_value(target, net, buy_price * qty)
                if ev > best_profit:
                    best_profit = ev
                    best_fuel = cost
        return best_profit, best_fuel

    def _plan_chain(
        self, first_legs: list[TradeRoute]
    ) -> TradeRoute | None:
        """Умное планирование (3): первое колено лучшей двухколенной цепочки.

        Цепочка: купить товар здесь -> продать в B; в B купить снова ->
        продать в C. Первое колено выбирается по критерию
        (прибыль первого колена + EV-прибыль продолжения) / (топливо обоих
        колен) — это отдаёт предпочтение коленам, ведущим в системы с
        богатыми рынками продолжения, даже если само первое колено скромнее
        лучшего одноколенного маршрута.

        Аргумент: first_legs — кандидаты первого колена (топ _raw_routes).
        Возвращает TradeRoute первого колена (net_profit = суммарная прибыль
        цепочки, chain_fuel = суммарное топливо) или None.
        """
        st = self.state
        best: TradeRoute | None = None
        best_score = 0.0
        for leg in first_legs:
            proceeds = leg.sell_price * leg.max_qty
            spent = leg.buy_price * leg.max_qty
            credits_at_b = st.credits - spent + proceeds
            if credits_at_b <= 0:
                continue
            cont_profit, cont_fuel = self._continuation_profit(
                leg.to_index, credits_at_b)
            if cont_profit <= 0:
                continue   # продолжения нет — колено уже покрыто одноколенными
            total = leg.net_profit + cont_profit
            total_fuel = leg.fuel_cost + cont_fuel
            score = total / max(total_fuel, 1)
            if score > best_score:
                best_score = score
                best = replace(leg, net_profit=total, chain_fuel=total_fuel)
        return best

    def _best_plan(self) -> TradeRoute | None:
        """План покупки: одноколенный маршрут или первое колено цепочки.

        Оба варианта сравниваются по чистой прибыли на единицу топлива
        (одноколенный: net_profit/fuel_cost; цепочка: суммарная прибыль /
        суммарное топливо). Одноколенные берутся точным EV, без UCB1-
        перезаписи: рынок детерминирован, +inf-исследование forcing прыжки
        в заведомо слабые системы — цепочки с ним несравнимы.
        """
        raw = self._raw_routes()
        single = max(
            raw,
            key=lambda r: r.net_profit / max(r.fuel_cost, 1),
            default=None,
        )
        chain = self._plan_chain(
            sorted(raw, key=lambda r: r.net_profit, reverse=True)
            [:CHAIN_FIRST_LEGS]
        )
        if chain is None:
            return single
        if single is None:
            return chain
        single_score = single.net_profit / max(single.fuel_cost, 1)
        chain_score = chain.net_profit / max(chain.chain_fuel, 1)
        return chain if chain_score > single_score else single

    # ------------------------------------------------------------- selling

    def _plan_sell(self) -> BotDecision | None:
        """Продать товар здесь, если цена >= 90% от лучшей в радиусе.

        Сравнение идёт с 2-3 ближайшими достижимыми системами. Товары,
        купленные в текущей системе, пропускаются (спред съедает прибыль).
        Возвращает None, если продавать нечего или невыгодно.
        """
        st = self.state
        items = [(i, q) for i, q in enumerate(st.cargo) if q > 0]
        if not items:
            return None
        probe = st.near_systems()[:3]
        candidates: list[tuple[float, int, int, float, float]] = []
        for ci, qty in items:
            if self._bought_at.get(ci) == st.system_index:
                continue
            cur = st.market.price_cr(ci)
            best = cur
            for target, _name, _dist, _cost in probe:
                price = self._market_of(target).price_cr(ci)
                if price > best:
                    best = price
            if best > 0 and cur >= self._tuned("SELL_PRICE_THRESHOLD") * best:
                candidates.append((cur * qty, ci, qty, cur, best))
        if not candidates:
            return None
        _score, ci, qty, cur, best = max(candidates, key=lambda c: c[0])
        details: dict[str, object] = {
            "commodity_index": ci,
            "quantity": qty,
            "price": cur,
        }
        self._pending_sell = {
            "commodity_index": ci,
            "quantity": qty,
            "price": cur,
        }
        reason = (
            f"Best sell price for {COMMODITIES[ci]} "
            f"({cur:.2f} Cr vs {best:.2f} Cr in reachable range)"
        )
        return BotDecision("sell", details, reason)

    def _best_sell_target(self) -> tuple[int, int, float] | None:
        """Лучший рынок сбыта для текущего груза: (target, commodity, price).

        Ищет достижимую систему с максимальной ценой продажи для любого
        товара в трюме (кроме купленных в текущей системе).
        """
        st = self.state
        best: tuple[float, int, int, float] | None = None
        for ci, qty in enumerate(st.cargo):
            if qty <= 0:
                continue
            # ВАЖНО: товар, купленный в текущей системе, продавать ЗДЕСЬ
            # нельзя (спред съедает прибыль), но лететь с ним в другую
            # систему — основная цель торговли. near_systems() уже
            # исключает текущую систему, поэтому проверка не нужна.
            cur = st.market.price_cr(ci)
            for target, _name, dist_units, cost in st.near_systems():
                if dist_units / 10.0 > self._max_jump_ly():
                    continue
                if not self._enough_fuel_with_reserve(target, cost):
                    continue
                # Риск учитывается через EV (ниже): жёсткий фильтр здесь
                # рассогласован с _find_best_routes (маршрут EV > 0 мог быть
                # куплен, а рынок сбыта — отфильтрован) -> груз застревал.
                price = self._market_of(target).price_cr(ci)
                # Risk-adjusted: ожидаемая прибыль с учётом потерь от атаки
                # (cargo_value = стоимость всего груза — он может пропасть).
                score = self._expected_value(target, price * qty, price * qty)
                if score <= 0:
                    continue   # риск превышает прибыль
                if price > cur and (best is None or score > best[0]):
                    best = (score, target, ci, price)
        if best is None:
            return None
        return best[1], best[2], best[3]

    def _plan_sell_stuck(self) -> BotDecision | None:
        """Застрявший груз: продать по лучшей цене, даже с убытком.

        Срабатывает, когда груз есть, но ни один достижимый рынок не лучше
        текущего (включая товары, купленные здесь). Освобождает трюм.
        """
        st = self.state
        for ci, qty in enumerate(st.cargo):
            if qty <= 0:
                continue
            # Товар, купленный в текущей системе, продавать ЗДЕСЬ бессмысленно:
            # цена покупки == цене продажи (нулевой оборот) — это вырожденный
            # цикл buy->sell->buy без прибыли. Ждём прыжка к рынку сбыта.
            if self._bought_at.get(ci) == st.system_index:
                continue
            price = st.market.price_cr(ci)
            details: dict[str, object] = {
                "commodity_index": ci,
                "quantity": qty,
                "price": price,
            }
            self._pending_sell = {
                "commodity_index": ci,
                "quantity": qty,
                "price": price,
            }
            return BotDecision(
                "sell",
                details,
                f"Cargo stuck: selling {COMMODITIES[ci]} at the best "
                f"available price ({price:.2f} Cr) to free the hold",
            )
        return None

    def _explore_target(self) -> int | None:
        """Цель исследовательского прыжка: самая безопасная система.

        Детерминированный выбор без `random`: БЕЗ hard-фильтра по опасности
        — пороговый фильтр (по prior или наблюдениям) загонял бота в угол,
        откуда не было выхода (все соседи опасны -> explore None -> WAIT ->
        stall). Все достижимые системы участвуют, а EV-сортировка (gross=1)
        ставит наименее опасные первыми; риск количественно учтён в EV,
        Bayesian-статистика собирается визитами. С безопасностью помогает
        и guard _pre_jump_refuel (полный бак -> побег 210/256).
        """
        st = self.state
        candidates: list[tuple[int, str, int, int]] = []
        for index, name, dist_units, cost in st.near_systems():
            if dist_units / 10.0 > self._max_jump_ly():
                continue
            if not self._enough_fuel_with_reserve(index, cost):
                continue
            candidates.append((index, name, dist_units, cost))
        if not candidates:
            return None

        def key(n: tuple[int, str, int, int]) -> tuple[float, int, int]:
            # Сначала — безопасность (expected_value с gross=1.0, cargo=0),
            # затем стоимость топлива, затем расстояние.
            ev = self._expected_value(n[0], 1.0, 0.0)
            fuel_cost_cr = n[3] * FUEL_PRICE_CR_PER_UNIT
            return (-ev, fuel_cost_cr, n[2])

        return min(candidates, key=key)[0]

    def _desperate_jump_target(self) -> int | None:
        """Цель прыжка при банкротстве: самая безопасная достижимая система.

        Выбирает систему с максимальным risk-adjusted EV (безопасность
        важнее дальности), при равенстве EV — ближайшую по расходу топлива.
        Резерв топлива игнорируется (цель — выжить, а не вернуться).
        Возвращает индекс системы или None, если ни одна не достижима.
        """
        st = self.state
        fuel = int(round(st.fuel))
        best: tuple[float, int, int] | None = None   # (ev, cost, index)
        for index, _name, _dist_units, cost in st.near_systems():
            if cost > fuel:
                continue
            # Без hard-фильтра: приоритет — максимальный risk-adjusted EV
            # (самая безопасная достижимая система), prior-риск учтён в EV.
            ev = self._expected_value(index, 1.0, 0.0)
            # При банкротстве выбираем самую безопасную достижимую систему
            # (ev выше = безопаснее), при равенстве — ближайшую.
            if best is None or ev > best[0] or (
                    ev == best[0] and cost < best[1]):
                best = (ev, cost, index)
        return best[2] if best is not None else None

    def _pre_jump_refuel(self, target: int) -> BotDecision | None:
        """Умный бот (1): заправка перед прыжком в рискованную систему.

        Вероятность успешного побега от пиратов = min(255, fuel*3)/256
        (elite_core.CombatEngine.resolve "escape"): при полном баке (70 ед.)
        это 210/256 ~= 0.82, при половине бака — 105/256 ~= 0.41, при 20 ед.
        — 60/256 ~= 0.23. Провал побега стоит 15% груза.

        Если цель достаточно опасна (P(атаки) >= DANGER_GUARD_P_ATTACK),
        топлива меньше полного и деньги на заправку есть — сначала
        заправляемся. Возвращает BotDecision("refuel") или None.
        """
        p_attack = self._attack_probability(target)
        if p_attack < self._tuned("DANGER_GUARD_P_ATTACK"):
            return None
        fuel = int(round(self.state.fuel))
        if fuel >= FUEL_TANK_CAPACITY:
            return None
        if not self._can_refuel():
            return None
        return BotDecision(
            "refuel", {},
            f"Risky target #{target} (P(attack)={p_attack:.2f}) — "
            f"refuelling to full: escape success {min(255, fuel * 3)}/256 "
            f"-> {min(255, FUEL_TANK_CAPACITY * 3)}/256",
        )

    # ------------------------------------------------------------- planning

    def _plan_turn(self) -> BotDecision:
        """Спланировать один ход: вернуть решение (без исполнения).

        Приоритеты (по убыванию):
          1) продать груз по хорошей цене здесь;
          2) груз есть — прыжок к лучшему рынку сбыта (или убыточная
             распродажа застрявшего груза);
          3) анти-застревание: 3+ визита без прибыли -> исследование;
          4) купить товар по лучшему маршруту (с топливным резервом),
             иначе заправиться;
          5) мало топлива -> заправка;
          6) исследовательский прыжок в новую систему;
          7) wait — нет прибыльных действий.
        """
        st = self.state
        fuel = int(round(st.fuel))

        # 1. Продажа по хорошей цене.
        sell = self._plan_sell()
        if sell is not None:
            return sell

        # 2. Груз есть — летим к рынку сбыта; застрявший груз распродаём.
        #    Умный бот (1): перед прыжком в рискованную систему — заправка
        #    до полного бака (вероятность успешного побега 210/256).
        if self._has_cargo():
            target_info = self._best_sell_target()
            if target_info is not None:
                target, ci, price = target_info
                guard = self._pre_jump_refuel(target)
                if guard is not None:
                    return guard
                return BotDecision(
                    "jump",
                    {"target_index": target},
                    f"Best sell market for {COMMODITIES[ci]} @ {price:.2f} Cr",
                )
            stuck = self._plan_sell_stuck()
            if stuck is not None:
                return stuck

        # 3. Анти-застревание: система посещена 3+ раз без прибыли.
        #    Умный бот (1): перед прыжком в рискованную систему — заправка.
        visit_limit = int(self._tuned("EXPLORE_VISIT_LIMIT"))
        if self._visits.get(st.system_index, 0) >= visit_limit:
            target = self._explore_target()
            if target is not None:
                guard = self._pre_jump_refuel(target)
                if guard is not None:
                    return guard
                return BotDecision(
                    "jump",
                    {"target_index": target},
                    f"Visited #{st.system_index} {visit_limit}+ times "
                    f"without profit — exploring",
                )

        # 4. Покупка по лучшему плану: одноколенный маршрут или первое
        #    колено двухколенной цепочки (умное планирование (3)) — по
        #    чистой прибыли на единицу топлива.
        route = self._best_plan()
        if route is not None and self._cargo_space() > 0:
            if self._enough_fuel_with_reserve(route.to_index, route.fuel_cost):
                gross = route.profit_per_ton * route.max_qty
                fuel_cr = route.fuel_cost * FUEL_PRICE_CR_PER_UNIT
                reason = (
                    f"Route #{route.from_index} -> #{route.to_index}: "
                    f"profit {route.profit_per_ton:.2f} Cr/ton x "
                    f"{route.max_qty}t = {gross:.2f} Cr, fuel {route.fuel_cost}u "
                    f"({fuel_cr:.2f} Cr)"
                )
                if route.chain_fuel:
                    reason += (
                        f"; CHAIN: net {route.net_profit:.2f} Cr "
                        f"for {route.chain_fuel}u fuel "
                        f"({route.net_profit / max(route.chain_fuel, 1):.2f} Cr/u)"
                    )
                else:
                    reason += f", net {route.net_profit:.2f} Cr"
                return BotDecision(
                    "buy", {"route": route}, reason
                )
            if self._can_refuel():
                return BotDecision(
                    "refuel",
                    {},
                    f"Not enough fuel for route #{route.to_index} "
                    f"(need {route.fuel_cost} units with reserve)",
                )

        # 5. Топлива не хватает даже на минимальный прыжок -> заправка.
        if fuel < int(self._tuned("MIN_FUEL_RESERVE")) and self._can_refuel():
            return BotDecision(
                "refuel", {}, "Low fuel — refuelling before the next jump"
            )

        # 6. Исследовательский прыжок (обновить рынок).
        # Кредитный пол: если кредитов мало и нет прибыльного маршрута —
        # лучше рестарт, чем сжигать топливо на exploration.
        if st.credits < CREDIT_FLOOR:
            return BotDecision(
                "dead_end", {},
                f"Credit floor: {st.credits:.2f} Cr < {CREDIT_FLOOR:.0f} Cr "
                f"and no profitable route — restart"
            )
        target = self._explore_target()
        if target is not None:
            guard = self._pre_jump_refuel(target)
            if guard is not None:
                return guard
            return BotDecision(
                "jump", {"target_index": target}, "Exploring new markets"
            )

        # 6.5. Отчаянный прыжок: бот банкрот (нет денег на товар и заправку),
        #      но топливо ещё есть — прыгаем без резерва в любую достижимую
        #      систему, чтобы сменить рынок (иначе бесконечный WAIT).
        if (not self._can_refuel()
                and self.state.credits < self._tuned("MIN_NET_PROFIT")):
            target = self._desperate_jump_target()
            if target is not None:
                return BotDecision(
                    "jump",
                    {"target_index": target},
                    "Bankrupt — desperate jump to change market (no fuel reserve)",
                )

        # 7. Прыгать нечем (ни один прыжок не проходит по резерву) —
        #    дозаправка, если есть деньги.
        if self._can_refuel():
            return BotDecision(
                "refuel",
                {},
                "No reachable system within fuel reserve — refuelling",
            )

        # 8. Истинный тупик: бак НЕ полон, денег на заправку нет, прыгать
        #    нечем (_desperate_jump_target() = None). ВАЖНО: _can_refuel()
        #    возвращает False и при ПОЛНОМ баке — это НЕ тупик: топливо
        #    есть, переходим к wait (STALL_LIMIT остановит, если ждать
        #    бессмысленно), а не к фальшивому рестарту.
        if not self._can_refuel() and int(round(st.fuel)) < FUEL_TANK_CAPACITY:
            return BotDecision(
                "dead_end", {},
                "Dead-end: no fuel, no credits, no reachable systems"
            )

        # 9. Ничего не можем (но заправка возможна — странный случай).
        return BotDecision(
            "wait", {}, "No profitable action available (no fuel, no credits)"
        )

    # ------------------------------------------------------------- execute

    def _execute_buy(self, route: TradeRoute) -> bool:
        """Купить товар по маршруту; True при успехе.

        Числа операции (количество, цена, стоимость) уже выведены в строке
        "Action: BUY ..." в run() — здесь только применяется сделка.
        """
        st = self.state
        try:
            st.buy(route.commodity_name, route.max_qty)
        except ValueError:
            return False
        self._bought_at[route.commodity_index] = st.system_index
        self._bought_price[route.commodity_index] = route.buy_price
        return True

    def _execute_sell(self) -> bool:
        """Продать товар, запланированный _plan_sell/_plan_sell_stuck.

        Числа операции выведены в строке "Action: SELL ..." в run().
        """
        st = self.state
        pending = self._pending_sell
        if not pending:
            return False
        ci = int(pending["commodity_index"])
        qty = int(pending["quantity"])
        try:
            st.sell(COMMODITIES[ci], qty)
        except ValueError:
            return False
        self._pending_sell = None
        self._bought_at.pop(ci, None)
        self._bought_price.pop(ci, None)
        self._visits.clear()          # продажа = прибыль -> сброс застревания
        return True

    def _execute_jump(self, target_index: int) -> bool:
        """Гиперпрыжок в систему; True при успехе."""
        st = self.state
        origin = st.system_index
        result = st.jump(target_index)
        if not result:
            self._log(f"  Jump failed: {result.error_reason}")
            return False
        self._jumps_made += 1
        self._just_jumped = True   # встреча возможна в начале следующего хода
        # Самообучение (Bayesian): фиксируем визит в новую систему.
        if self._memory is not None:
            self._memory.record_visit(st.system_index, attacked=False)
        before_fuel = result.new_fuel + result.fuel_cost
        self._log(
            f"  Jump {origin} -> {target_index} "
            f"({result.distance_ly:.1f} ly, fuel: {before_fuel}->{result.new_fuel})"
        )
        return True

    def _execute_refuel(self) -> bool:
        """Заправка до полного бака; True при успехе."""
        result = self.state.refuel()
        if not result:
            self._log(f"  Refuel failed: {result.error_reason}")
            return False
        self._log(
            f"  REFUEL to full (cost: {result.cost:.2f} Cr, fuel: "
            f"{int(round(self.state.fuel))}/{FUEL_TANK_CAPACITY})"
        )
        return True

    # ------------------------------------------------------------- combat

    @staticmethod
    def _combat_reward(action: str, outcome: CombatResult) -> float:
        """Награда за исход боя (критерий выбора действия в симуляции).

        Ключевое: выжил, но проиграл — НЕ смерть. Только
        outcome.destroyed даёт -10.0 (смерть несопоставимо дороже любой
        потери груза/кредитов).
        """
        if outcome.destroyed:
            return -10.0
        if action == "fight":
            if outcome.status == "fight_win":
                return 1.0
            # Проиграл бой, но выжил — плохо, но не смерть
            return -2.0
        if action == "flee":
            if outcome.status == "escape_success":
                return 0.2
            # Побег не удался, но выжил — потеря груза/щитов
            return -1.0
        # surrender: выжил, но потерял груз и часть кредитов
        return -0.5

    def _handle_combat(self) -> BotDecision:
        """Решение в бою: Монте-Карло симуляция (с памятью) или правила.

        С BotMemory действие выбирает _simulate_combat: точная модель
        учитывает топливо (побег = min(255, fuel*3)/256), щиты и
        техуровень. Без памяти — правила по щитам, правительству и
        risk_tolerance.

        Ключевое правило (fallback): в опасных системах (Anarchy/Feudal/
        Multi-Government) бот уходит, а не дерётся — даже при полных
        щитах риск потерять весь груз выше прибыли от победы.

        medium:
          * DANGEROUS_GOV -> flee (пираты сильные);
          * MODERATE_GOV -> fight только при energy >= 200 и FSH >= 200,
            surrender при energy < 64, иначе flee;
          * безопасные -> surrender при energy < 64, flee при energy < 128
            или FSH < 100, иначе fight.
        high — fight, но в DANGEROUS_GOV при слабых щитах — flee.
        low — всегда flee.
        """
        # --- Умный бот (2): решение из Монте-Карло симуляции ---
        if self._memory is not None:
            sim = self._simulate_combat(
                int(self.state.system["government"]),
                int(round(self.state.fuel)),
                int(self.state.system["tech_level"]),
            )
            action = sim.action
            return BotDecision(
                action, {},
                f"MC-sim: {action} (p_death={sim.p_death:.2f}, "
                f"p_cargo_loss={sim.cargo_frac:.2f})")

        d = self.state.defense
        gov = int(self.state.system["government"])

        if self.risk_tolerance == "high":
            # Даже high не дерётся в Anarchy с малыми щитами.
            if gov in DANGEROUS_GOV and (d.energy < 128 or d.forward_shield < 100):
                action = "flee"
            else:
                action = "fight"
        elif self.risk_tolerance == "low":
            action = "flee"
        else:
            # medium — умное решение по контексту.
            if gov in DANGEROUS_GOV:
                # Anarchy/Feudal — пираты сильные, flee.
                action = "flee"
            elif gov in MODERATE_GOV:
                # Dictatorship/Communist — fight только при полных щитах.
                if d.energy >= 200 and d.forward_shield >= 200:
                    action = "fight"
                elif d.energy < 64:
                    action = "surrender"
                else:
                    action = "flee"
            else:
                # Democracy/Corporate — относительно безопасно.
                if d.energy < 64:
                    action = "surrender"
                elif d.energy < 128 or d.forward_shield < 100:
                    action = "flee"
                else:
                    action = "fight"

        reason = (
            f"Energy {d.energy}, FSH {d.forward_shield}, ASH {d.aft_shield}, "
            f"gov {gov}, risk {self.risk_tolerance}"
        )
        return BotDecision(action, {}, reason)

    def _maybe_combat(self) -> bool:
        """Пиратская атака в начале хода; True — корабль уничтожен."""
        if not self.state.check_pirate_attack():
            return False
        self._combats_encountered += 1
        decision = self._handle_combat()
        self._log(f"  COMBAT: pirates attack -> {decision.action.upper()}")
        # Ядро принимает "escape", а не "flee" (в BotDecision используется
        # "flee" — семантическое имя решения бота).
        core_action = "escape" if decision.action == "flee" else decision.action
        outcome: CombatResult = self.state.resolve_combat_action(core_action)
        self._log(f"    {outcome.message}")
        # Bayesian: система, где произошла атака (валидация модели риска).
        if self._memory is not None:
            self._memory.record_attack(self.state.system_index)
        if decision.action == "fight" and outcome.status == "fight_win":
            self._combats_won += 1
        if decision.action == "flee":
            self._combats_fled += 1
        if outcome.destroyed:
            self._log("  Ship destroyed — autopilot run over.")
            return True
        return False

    # ------------------------------------------------------------- runner

    def _execute(self, decision: BotDecision) -> str:
        """Исполнить решение; возвращает 'ok' | 'exit' | 'stall'."""
        action = decision.action
        if action == "buy":
            route = decision.details.get("route")
            if isinstance(route, TradeRoute):
                return "ok" if self._execute_buy(route) else "stall"
            return "stall"
        if action == "sell":
            return "ok" if self._execute_sell() else "stall"
        if action == "jump":
            target = decision.details.get("target_index")
            if isinstance(target, int):
                return "ok" if self._execute_jump(target) else "stall"
            return "stall"
        if action == "refuel":
            return "ok" if self._execute_refuel() else "stall"
        if action == "dead_end":
            return "exit"
        if action == "wait":
            return "stall"
        # fight/flee/surrender обрабатываются в _maybe_combat.
        return "stall"

    def run(self) -> BotResult:
        """Главный цикл: регенерация щитов -> бой -> план -> исполнение.

        Останавливается при: уничтожении корабля, исчерпании раундов или
        STALL_LIMIT подряд идущих раундов без прогресса.
        """
        st = self.state
        starting = st.credits
        self._log(
            f"Autopilot start: galaxy {st.galaxy}, system #{st.system_index} "
            f"{st.system['name']}, credits {st.credits:.2f} Cr, "
            f"risk={self.risk_tolerance}, rounds={self.max_rounds}"
        )

        round_no = 0
        stall = 0
        try:
            while self.max_rounds == 0 or round_no < self.max_rounds:
                round_no += 1
                self._visits[st.system_index] = self._visits.get(
                    st.system_index, 0) + 1
                # Самообучение (Bayesian): стартовая система — тоже визит.
                if self._memory is not None and round_no == 1:
                    self._memory.record_visit(st.system_index, attacked=False)
                self._log(
                    f"[Round {round_no}] System #{st.system_index} "
                    f"{st.system['name']} ({st.system['economy_name']}) | "
                    f"Credits: {st.credits:.2f} Cr | Fuel: "
                    f"{int(round(st.fuel))}/{FUEL_TANK_CAPACITY} | "
                    f"Cargo: {st.cargo_weight}/{SHIP_HOLD} t"
                )

                # 0. Регенерация щитов: 1 ед. за раунд (между боями в одной
                #    системе). Полный reset() бывает только при прыжке
                #    (load_system -> defense.reset()).
                self.state.defense.recharge(1)

                # 1. Бой — только в ходу после прыжка (встреча при прибытии,
                #    как в оригинале; иначе пираты атаковали бы каждый ход).
                if self._just_jumped:
                    self._just_jumped = False
                    if self._maybe_combat():
                        break

                # 2. План и исполнение.
                decision = self._plan_turn()
                self._log(f"  {self._action_line(decision)}")
                self._log(f"  Reason: {decision.reason}")

                outcome = self._execute(decision)
                if outcome == "exit":
                    self._log("  Dead-end — stopping for restart.")
                    break
                if outcome == "stall":
                    stall += 1
                    if STALL_LIMIT > 0 and stall >= STALL_LIMIT:
                        self._log(
                            f"  Stall: no progress for {STALL_LIMIT} turns "
                            f"— stopping."
                        )
                        break
                else:
                    stall = 0
        except KeyboardInterrupt:
            self._log("\n  Interrupted by user (Ctrl-C).")

        final = st.credits
        profit = final - starting
        roi = (profit / starting * 100.0) if starting > 0 else 0.0
        # Закрыть память самообучения (опыт персистится в SQLite между
        # запусками; повторный run() на том же Autopilot невозможен).
        if self._memory is not None:
            self._memory.close()
        return BotResult(
            rounds_played=round_no,
            final_credits=final,
            starting_credits=starting,
            profit=profit,
            roi_pct=roi,
            jumps_made=self._jumps_made,
            combats_encountered=self._combats_encountered,
            combats_won=self._combats_won,
            combats_fled=self._combats_fled,
            log_lines=list(self._log_lines),
        )

    @staticmethod
    def _action_line(decision: BotDecision) -> str:
        """Строка "Action: ..." с расчётными числами (cost/income)."""
        details = decision.details
        if decision.action == "buy":
            route = details.get("route")
            if isinstance(route, TradeRoute):
                cost = route.buy_price * route.max_qty
                return (
                    f"Action: BUY {route.max_qty} {route.commodity_name} "
                    f"@ {route.buy_price:.2f} Cr (cost: {cost:.2f} Cr)"
                )
        if decision.action == "sell":
            ci = details.get("commodity_index")
            qty = details.get("quantity")
            price = details.get("price")
            if (
                isinstance(ci, int)
                and isinstance(qty, int)
                and isinstance(price, (int, float))
            ):
                return (
                    f"Action: SELL {qty} {COMMODITIES[ci]} @ {price:.2f} Cr "
                    f"(income: {price * qty:.2f} Cr)"
                )
        if decision.action == "jump":
            target = details.get("target_index")
            if isinstance(target, int):
                return f"Action: JUMP to #{target}"
        if decision.action == "refuel":
            return "Action: REFUEL"
        if decision.action == "wait":
            return "Action: WAIT"
        return f"Action: {decision.action.upper()}"


# --------------------------------------------------------------------------
# Умный бот (4): автооптимизация констант
# --------------------------------------------------------------------------


def optimize_constants(
    *,
    galaxies: tuple[int, ...] = (0,),
    rounds: int = 300,
    seeds: int = 3,
    passes: int = 2,
    params: tuple[str, ...] | None = None,
    grid: dict[str, tuple[float, ...]] | None = None,
    verbose: bool = True,
) -> TuneResult:
    """Координатный спуск по константам бота (детерминированные прогоны).

    Качество набора констант измеряется точно: средняя прибыль за `rounds`
    раундов по `seeds` прогонам (разные rng_seed -> разные бои) на каждой
    галактике из `galaxies`. Один проход (`passes`) перебирает все параметры
    из сетки `_TUNABLE_GRID` (или переданной `grid`); значение меняется,
    только если улучшает score. Память самообучения отключена
    (memory_db=None): оптимизируется «чистая» логика без накопленного опыта.

    ВНИМАНИЕ: полный запуск (7 параметров x ~4 значения x seeds x passes x
    rounds) занимает минуты — это офлайн-инструмент, не часть игрового цикла.
    Найденный набор передаётся в Autopilot через аргумент `tunables`.
    """
    grid_map = grid if grid is not None else _TUNABLE_GRID
    names = tuple(params) if params else tuple(grid_map)
    current: dict[str, float] = {name: _TUNABLE_DEFAULTS[name] for name in names}
    history: list[tuple[str, float, float]] = []
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        if verbose:
            print(msg)

    def evaluate(tunables: dict[str, float]) -> float:
        total = 0.0
        n = 0
        for galaxy in galaxies:
            for s in range(seeds):
                seed = (1000 + 137 * s, 7919 + 13 * s, 31 + 97 * s, 13 + 7 * s)
                st = GameState(
                    galaxy=galaxy, system_index=0,
                    rng_seed=seed, credits=100.0,
                )
                st.load_system()
                bot = Autopilot(
                    st, max_rounds=rounds, risk_tolerance="medium",
                    log_file=None, memory_db=None, verbose=False,
                    tunables=tunables,
                )
                total += bot.run().profit
                n += 1
        return total / max(n, 1)

    best_score = evaluate(current)
    log(f"[optimize] baseline = {best_score:.2f} Cr/run | {current}")
    for p in range(passes):
        log(f"[optimize] pass {p + 1}/{passes}")
        for name in names:
            for value in grid_map.get(name, ()):
                if value == current[name]:
                    continue
                trial = dict(current)
                trial[name] = value
                score = evaluate(trial)
                if score > best_score:
                    current[name] = value
                    best_score = score
                    history.append((name, value, score))
                    log(f"[optimize] {name} = {value} -> {score:.2f} Cr/run")
            log(f"[optimize] {name}: kept {current[name]} "
                f"(best {best_score:.2f} Cr/run)")
    return TuneResult(
        best=current, score=best_score, history=history, log_lines=lines)


# --------------------------------------------------------------------------
# CLI точка входа
# --------------------------------------------------------------------------


def main() -> int:
    """Запустить бота: галактика 0, система 0, 100 Cr, бесконечно (Ctrl-C).

    Один EventLogger (elite_events.db) создаётся на всё время работы бота и
    передаётся в GameState через event_logger — события (buy/sell/jump/
    refuel/combat) пишутся автоматически самим ядром. При гибели корабля
    партия перезапускается с новым GameState, но тем же логгером.
    Если Ctrl-C нажат раньше, чем цикл run() успел стартовать (результата
    нет) — завершаемся с кодом 0 без отчёта, чтобы не упасть с
    UnboundLocalError.
    """
    import sys as _sys

    from elite_analytics import EventLogger

    if "--optimize" in _sys.argv:
        result = optimize_constants(verbose=True)
        print("\n=== Optimized constants ===")
        for name, value in sorted(result.best.items()):
            print(f"{name} = {value}")
        print(f"score: {result.score:.2f} Cr average profit per run")
        return 0

    logger = EventLogger("elite_events.db", player_id=PLAYER_ID)
    try:
        while True:
            state = GameState(galaxy=0, system_index=0, event_logger=logger)
            state.load_system()
            state.fuel = FUEL_TANK_CAPACITY
            state.credits = 100.0

            autopilot = Autopilot(
                state,
                max_rounds=0,           # бесконечно
                risk_tolerance="medium",
                log_file=None,          # только в память
                memory_db="bot_memory.db",  # память самообучения (SQLite)
                player_id=PLAYER_ID,
                verbose=True,
            )
            # run() сам перехватывает KeyboardInterrupt и возвращает
            # BotResult; выход по Ctrl-C обрабатывает проверка destroyed ниже.
            result = autopilot.run()

            print("\n=== pyElite — Autopilot Report ===")
            print(f"Rounds played:    {result.rounds_played}")
            print(f"Starting credits: {result.starting_credits:.2f} Cr")
            print(f"Final credits:    {result.final_credits:.2f} Cr")
            print(f"Profit:           {result.profit:.2f} Cr")
            print(f"ROI:              {result.roi_pct:.0f}%")
            print(f"Jumps made:       {result.jumps_made}")
            print(f"Combats:          {result.combats_encountered} "
                  f"(won: {result.combats_won}, fled: {result.combats_fled}, "
                  f"surrendered: {max(result.combats_encountered - result.combats_won - result.combats_fled, 0)})")
            print("=== End Report ===")

            if not state.defense.destroyed:
                break   # штатный выход (или Ctrl-C внутри run) — не перезапуск
    finally:
        logger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "TradeRoute",
    "BotDecision",
    "BotResult",
    "CombatSimStats",
    "TuneResult",
    "BotMemory",
    "Autopilot",
    "optimize_constants",
    "main",
]
