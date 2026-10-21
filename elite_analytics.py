"""
elite_analytics.py — аналитика для порта «pyElite» (поверх elite_core).

Модуль добавляет к детерминированному ядру три сервиса:
  1. EventLogger    — SQLite-журнал событий игрока (elite_events.db);
  2. RouteFinder    — поиск маршрута по графу систем (BFS, рёбра <= 7 св. лет);
  3. ProfitAnalyzer — анализ прибыльности торговли.

Только stdlib (sqlite3, math, collections, datetime, typing, dataclasses).
Без `random`; все расчёты детерминированы и используют elite_core.

Ссылки на исходники (формулы):
  - Расстояние между системами: d = sqrt(dx^2 + (dy>>1)^2) * 4
    (src/code_6a00.asm:1631-1724, _TT111); расход топлива = младший byte
    расстояния (src/code_6a00.asm:2222-2230); порог прыжка 70 единиц =
    7.0 св. лет (src/save_data.asm:160, src/code_6a00.asm:1793-1799).
  - Цена топлива: 0.2 Cr/ед. (src/code_6a00.asm:2412-2416, 2725-2738),
    заправка всегда до полного бака (src/code_6a00.asm:2465-2466).
  - Цены товаров: TT151/_7365 (src/code_6a00.asm:1951-1977, 2131-2165),
    вместимость трюма (src/save_data.asm:169).
"""

from __future__ import annotations

import sqlite3
import sys
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from elite_core import (
    COMMODITIES,
    FUEL_PRICE_PER_UNIT_CR,
    FUEL_TANK_CAPACITY,
    GalaxyGenerator,
    GameState,
    JumpEngine,
    MarketEngine,
    MarketError,
    PRECIOUS_LIMIT,
    SHIP_HOLD,
)

# --------------------------------------------------------------------------
# EventLogger — SQLite event log (elite_events.db)
# --------------------------------------------------------------------------

TABLE_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,                  -- идентификатор партии (один запуск логгера)
  player_id INTEGER NOT NULL DEFAULT 0,
  timestamp TEXT NOT NULL,          -- ISO 8601, UTC
  galaxy INTEGER NOT NULL,
  system_index INTEGER NOT NULL,
  system_name TEXT NOT NULL,
  action TEXT NOT NULL,             -- buy|sell|refuel|jump|pirate_attack|escape|surrender|wait
  item TEXT,                        -- commodity name or NULL
  quantity INTEGER,                 -- quantity or NULL
  unit_price REAL,                  -- price per unit or NULL
  total_cost REAL,                  -- total deal amount or NULL
  fuel_before INTEGER,
  fuel_after INTEGER,
  credits_before REAL,
  credits_after REAL,
  cargo_weight_before INTEGER,
  cargo_weight_after INTEGER,
  target_system INTEGER,            -- (jump) индекс системы назначения
  distance_ly REAL,                 -- (jump) дистанция в св. годах
  details TEXT                      -- extra info (target system, damage etc.)
);
"""

# Индексы создаются ПОСЛЕ миграций колонок: в старой БД колонки
# session_id/target_system/distance_ly появляются только миграцией.
INDEX_SCHEMA: Final[str] = """
-- Быстрая фильтрация по типу события: WHERE action = 'buy' и т.д.
CREATE INDEX IF NOT EXISTS idx_transactions_action
  ON transactions (action, timestamp);
-- Фильтрация по версии бота/игрока: WHERE player_id = ?
CREATE INDEX IF NOT EXISTS idx_transactions_player
  ON transactions (player_id, id);
-- Выборка всех событий одной партии: WHERE session_id = ?
CREATE INDEX IF NOT EXISTS idx_transactions_session
  ON transactions (session_id, id);
"""

# Совместимость: старое имя SCHEMA = таблица + индексы.
SCHEMA: Final[str] = TABLE_SCHEMA + INDEX_SCHEMA

# Допустимые типы событий (защита от опечаток в log_*-методах).
ALLOWED_ACTIONS: Final[frozenset[str]] = frozenset({
    "buy", "sell", "refuel", "jump",
    "pirate_attack", "escape", "surrender", "wait",
})


@dataclass(frozen=True)
class LogPoint:
    """Snapshot of the player state (for the before/after log columns)."""

    fuel: int
    credits: float
    cargo_weight: int
    galaxy: int
    system_index: int
    system_name: str


class EventLogger:
    """
    Event logger into SQLite. Each record is a separate COMMIT; DB errors
    are written to stderr and do not crash the game.

    Shortcut methods take the game_state AFTER the action; the "before"
    values are restored from the operation parameters (the effect of the
    deal is exactly known), and for combat the last snapshot taken by the
    `capture` method is used.
    """

    def __init__(
        self, db_path: str | Path = "elite_events.db", player_id: int = 0,
        session_id: str | None = None,
    ) -> None:
        self.db_path: Path = Path(db_path)
        self.player_id: int = int(player_id)
        # Одна партия = один session_id (uuid). Явный session_id полезен
        # для восстановления истории после перезапуска приложения.
        self.session_id: str = (
            session_id if session_id is not None else uuid.uuid4().hex)
        # timeout: ждать освобождения блокировки (TUI + бот могут писать
        # в одну БД одновременно) вместо мгновенной потери события.
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self.db_path), timeout=5)
        # executescript: таблица содержит один statement, идемпотентно.
        self._conn.executescript(TABLE_SCHEMA)
        self._conn.commit()
        # Миграции старых БД: добавляем колонки по одной (если их нет).
        self._migrate_column(
            'ALTER TABLE transactions ADD COLUMN player_id '
            'INTEGER NOT NULL DEFAULT 0')
        self._migrate_column(
            'ALTER TABLE transactions ADD COLUMN session_id TEXT')
        self._migrate_column(
            'ALTER TABLE transactions ADD COLUMN target_system INTEGER')
        self._migrate_column(
            'ALTER TABLE transactions ADD COLUMN distance_ly REAL')
        # Индексы — после миграций (ссылаются на новые колонки).
        self._conn.executescript(INDEX_SCHEMA)
        self._conn.commit()
        self._last_point: LogPoint | None = None  # last capture()

    def _migrate_column(self, ddl: str) -> None:
        """Добавить колонку, если её ещё нет (идемпотентная миграция)."""
        try:
            self._conn.execute(ddl)
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # колонка уже существует

    # ------------------------------------------------------------- helpers

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def new_session(self, session_id: str | None = None) -> str:
        """Начать новую партию: последующие записи получают новый session_id.

        Возвращает (новый) идентификатор партии. Вызывается при рестарте
        игры (например, GameOverScreen -> новая игра)."""
        self.session_id = (
            session_id if session_id is not None else uuid.uuid4().hex)
        return self.session_id

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @classmethod
    def _point(cls, gs: GameState) -> LogPoint:
        """Snapshot of the current game_state (duck-typed: any object with
        fuel/credits/cargo_weight/system_index/galaxy/system['name'])."""
        return LogPoint(
            fuel=int(round(gs.fuel)),
            credits=float(gs.credits),
            cargo_weight=int(gs.cargo_weight),
            galaxy=int(gs.galaxy),
            system_index=int(gs.system_index),
            system_name=str(gs.system["name"]),
        )

    def capture(self, gs: GameState) -> None:
        """Remember a state snapshot (call BEFORE an action whose effect
        cannot be derived from parameters — e.g. combat)."""
        self._last_point = self._point(gs)

    # ---------------------------------------------------------- insertion

    def log_transaction(self, **fields: object) -> None:
        """Insert one row into the transactions table (one COMMIT).

        Неизвестный action -> сообщение в stderr, запись пропускается
        (защита от опечаток в log_*-методах).
        DB error -> message to stderr, the game continues."""
        action: object = fields.get("action")
        if action not in ALLOWED_ACTIONS:
            print(f"[elite_analytics] unknown action {action!r} skipped",
                  file=sys.stderr)
            return
        row: dict[str, object] = {
            "session_id": self.session_id,
            "player_id": self.player_id,
            "timestamp": self._now(),
            "galaxy": fields.get("galaxy"),
            "system_index": fields.get("system_index"),
            "system_name": fields.get("system_name"),
            "action": fields.get("action"),
            "item": fields.get("item"),
            "quantity": fields.get("quantity"),
            "unit_price": fields.get("unit_price"),
            "total_cost": fields.get("total_cost"),
            "fuel_before": fields.get("fuel_before"),
            "fuel_after": fields.get("fuel_after"),
            "credits_before": fields.get("credits_before"),
            "credits_after": fields.get("credits_after"),
            "cargo_weight_before": fields.get("cargo_weight_before"),
            "cargo_weight_after": fields.get("cargo_weight_after"),
            "target_system": fields.get("target_system"),
            "distance_ly": fields.get("distance_ly"),
            "details": fields.get("details"),
        }
        cols: list[str] = [k for k, v in row.items() if v is not None]
        try:
            sql = f"INSERT INTO transactions ({', '.join(cols)}) " \
                  f"VALUES ({', '.join('?' for _ in cols)})"
            self._conn.execute(sql, [row[c] for c in cols])
            self._conn.commit()
        except sqlite3.Error as exc:
            print(f"[elite_analytics] DB write error: {exc}", file=sys.stderr)

    # --------------------------------------------------------- shortcuts

    def log_buy(self, gs: GameState, item: str, qty: int,
                unit_price: float, total_cost: float) -> None:
        """Buy: before is restored from the deal amount."""
        after = self._point(gs)
        tonnage: int = qty if 0 <= self._item_index(item) <= 12 else 0
        before = LogPoint(
            after.fuel, after.credits + total_cost, after.cargo_weight - tonnage,
            after.galaxy, after.system_index, after.system_name)
        self.log_transaction(
            galaxy=after.galaxy, system_index=after.system_index,
            system_name=after.system_name, action="buy", item=item,
            quantity=qty, unit_price=unit_price, total_cost=total_cost,
            fuel_before=before.fuel, fuel_after=after.fuel,
            credits_before=before.credits, credits_after=after.credits,
            cargo_weight_before=before.cargo_weight,
            cargo_weight_after=after.cargo_weight,
            details=f"bought {qty} {item} for {total_cost:.2f} Cr")

    def log_sell(self, gs: GameState, item: str, qty: int,
                 unit_price: float, total_cost: float) -> None:
        """Sell: before is restored from the deal amount."""
        after = self._point(gs)
        tonnage: int = qty if 0 <= self._item_index(item) <= 12 else 0
        before = LogPoint(
            after.fuel, after.credits - total_cost, after.cargo_weight + tonnage,
            after.galaxy, after.system_index, after.system_name)
        self.log_transaction(
            galaxy=after.galaxy, system_index=after.system_index,
            system_name=after.system_name, action="sell", item=item,
            quantity=qty, unit_price=unit_price, total_cost=total_cost,
            fuel_before=before.fuel, fuel_after=after.fuel,
            credits_before=before.credits, credits_after=after.credits,
            cargo_weight_before=before.cargo_weight,
            cargo_weight_after=after.cargo_weight,
            details=f"sold {qty} {item} for {total_cost:.2f} Cr")

    def log_refuel(self, gs: GameState, cost: float, new_fuel: float) -> None:
        """Refuel to full: before = 70 - cost/0.2 (price 0.2 Cr/unit,
        src/code_6a00.asm:2412-2416)."""
        after = self._point(gs)
        filled: int = int(round(cost / FUEL_PRICE_PER_UNIT_CR))
        before = LogPoint(
            max(after.fuel - filled, 0), after.credits + cost, after.cargo_weight,
            after.galaxy, after.system_index, after.system_name)
        self.log_transaction(
            galaxy=after.galaxy, system_index=after.system_index,
            system_name=after.system_name, action="refuel",
            item=None, quantity=filled, unit_price=FUEL_PRICE_PER_UNIT_CR,
            total_cost=cost,
            fuel_before=before.fuel, fuel_after=after.fuel,
            credits_before=before.credits, credits_after=after.credits,
            cargo_weight_before=before.cargo_weight,
            cargo_weight_after=after.cargo_weight,
            details=f"refuelled {filled} units to full tank for {cost:.2f} Cr")

    def log_jump(self, gs: GameState, target_index: int, target_name: str,
                 distance_ly: float, fuel_cost: int) -> None:
        """Jump: before = after + fuel_cost (cost = low byte of the distance,
        src/code_6a00.asm:2222-2230)."""
        after = self._point(gs)
        before = LogPoint(
            after.fuel + fuel_cost, after.credits, after.cargo_weight,
            after.galaxy, after.system_index, after.system_name)
        self.log_transaction(
            galaxy=after.galaxy, system_index=after.system_index,
            system_name=after.system_name, action="jump",
            item=None, quantity=None, unit_price=None, total_cost=None,
            fuel_before=before.fuel, fuel_after=after.fuel,
            credits_before=before.credits, credits_after=after.credits,
            cargo_weight_before=before.cargo_weight,
            cargo_weight_after=after.cargo_weight,
            target_system=int(target_index), distance_ly=float(distance_ly),
            details=f"jump to #{target_index} {target_name}, "
                    f"{distance_ly:.1f} ly, fuel cost {fuel_cost} units")

    def log_combat(self, gs: GameState, action: str, details: str) -> None:
        """Combat: before = last capture() snapshot, after = current state.

        Снапшот одноразовый: после чтения сбрасывается, чтобы устаревший
        before не «протёк» в следующий бой. Если capture() не вызывался,
        before = after (fallback помечается в details)."""
        after = self._point(gs)
        before: LogPoint = self._last_point if self._last_point is not None else after
        fallback: bool = self._last_point is None
        self._last_point = None
        if fallback:
            details = f"{details}; no capture() snapshot (before=after)"
        self.log_transaction(
            galaxy=after.galaxy, system_index=after.system_index,
            system_name=after.system_name, action=action,
            item=None, quantity=None, unit_price=None, total_cost=None,
            fuel_before=before.fuel, fuel_after=after.fuel,
            credits_before=before.credits, credits_after=after.credits,
            cargo_weight_before=before.cargo_weight,
            cargo_weight_after=after.cargo_weight,
            details=details)

    def log_wait(self, gs: GameState, details: str) -> None:
        """Wait one turn: no resource changes (recharge only)."""
        after = self._point(gs)
        self.log_transaction(
            galaxy=after.galaxy, system_index=after.system_index,
            system_name=after.system_name, action="wait",
            item=None, quantity=None, unit_price=None, total_cost=None,
            fuel_before=after.fuel, fuel_after=after.fuel,
            credits_before=after.credits, credits_after=after.credits,
            cargo_weight_before=after.cargo_weight,
            cargo_weight_after=after.cargo_weight,
            details=details)

    # --------------------------------------------------------------- utils

    @staticmethod
    def _item_index(item: str) -> int:
        """Commodity index by name (for the tonnage accounting 0..12)."""
        key = str(item).strip().lower()
        for i, name in enumerate(COMMODITIES):
            if name.lower() == key or name.lower().startswith(key):
                return i
        return -1

    def all_rows(self) -> list[sqlite3.Row]:
        """All transaction records (for tests/output)."""
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute(
            "SELECT id, session_id, player_id, timestamp, galaxy, "
            "system_index, system_name, action, item, quantity, unit_price, "
            "total_cost, fuel_before, fuel_after, credits_before, "
            "credits_after, cargo_weight_before, cargo_weight_after, "
            "target_system, distance_ly, details "
            "FROM transactions ORDER BY id")
        return list(cur.fetchall())


# --------------------------------------------------------------------------
# RouteFinder — system graph and routes (BFS)
# --------------------------------------------------------------------------


class RouteFinder:
    """
    The galaxy graph is built on the fly: nodes are systems 0..255; there is
    an edge when the distance <= 70 units (7.0 ly, src/save_data.asm:160).
    Distance — formula _TT111 (src/code_6a00.asm:1631-1724):
        d = sqrt(|dX|^2 + (|dY|>>1)^2) * 4   (units, 1 unit = 0.1 ly).
    """

    def __init__(self, generator: GalaxyGenerator, galaxy_number: int = 0) -> None:
        self._galaxy: int = galaxy_number & 0x07
        self._generator: GalaxyGenerator = generator
        self._jump: JumpEngine = JumpEngine(generator, self._galaxy)
        self._systems: list[dict[str, int | str]] = generator.generate_galaxy(
            self._galaxy)
        self._graph: list[list[int]] | None = None  # lazy construction

    # ------------------------------------------------------------- graph

    @property
    def graph(self) -> list[list[int]]:
        """Adjacency list: for each system — those reachable in one jump."""
        if self._graph is None:
            graph: list[list[int]] = [[] for _ in range(256)]
            for i in range(256):
                for j in range(256):
                    if i != j and self._jump.distance_units(i, j) <= FUEL_TANK_CAPACITY:
                        graph[i].append(j)
            self._graph = graph
        return self._graph

    def neighbors(self, system_index: int) -> list[int]:
        """Systems reachable in one jump from `system_index`."""
        self._validate(system_index)
        return self.graph[system_index]

    def system_name(self, system_index: int) -> str:
        self._validate(system_index)
        return str(self._systems[system_index]["name"])

    @staticmethod
    def _validate(system_index: int) -> None:
        if not isinstance(system_index, int) or not 0 <= system_index < 256:
            raise ValueError(
                f"system {system_index!r} does not exist (valid range 0-255)")

    # ------------------------------------------------------- shortest route

    def find_route(self, start_index: int, target_index: int) -> list[int] | None:
        """Shortest route (BFS): list of system indexes including the start
        and the target; None if the target is unreachable."""
        self._validate(start_index)
        self._validate(target_index)
        if start_index == target_index:
            return [start_index]

        prev: dict[int, int | None] = {start_index: None}
        queue: deque[int] = deque([start_index])
        found: bool = False
        while queue and not found:
            current: int = queue.popleft()
            for nxt in self.graph[current]:
                if nxt not in prev:
                    prev[nxt] = current
                    if nxt == target_index:
                        found = True
                        break
                    queue.append(nxt)

        if not found:
            return None
        path: list[int] = []
        node: int | None = target_index
        while node is not None:
            path.append(node)
            node = prev[node]
        path.reverse()
        return path

    def find_reachable(self, start_index: int, max_jumps: int) -> list[tuple[int, int]]:
        """Systems within <= max_jumps jumps: [(index, depth)]."""
        self._validate(start_index)
        depth: dict[int, int] = {start_index: 0}
        queue: deque[int] = deque([start_index])
        reachable: list[tuple[int, int]] = []
        while queue:
            current = queue.popleft()
            d = depth[current]
            if d >= max_jumps:
                continue
            for nxt in self.graph[current]:
                if nxt not in depth:
                    depth[nxt] = d + 1
                    queue.append(nxt)
                    reachable.append((nxt, d + 1))
        return reachable

    def find_route_with_fuel(
        self, start_index: int, target_index: int, current_fuel: int
    ) -> list[dict[str, int | float | str | bool]] | None:
        """
        Route with fuel accounting. For each jump:
          {system_index, system_name, distance_ly, fuel_cost, fuel_after,
           refuel_needed, refuel_cost}.
        If the fuel is insufficient for the next system, a refuel to full
        tank is performed before the jump (0.2 Cr/unit, always to full,
        src/code_6a00.asm:2412-2416, 2465-2466).
        """
        path: list[int] | None = self.find_route(start_index, target_index)
        if path is None:
            return None

        fuel: float = float(current_fuel)
        legs: list[dict[str, int | float | str | bool]] = []
        for a, b in zip(path, path[1:]):
            dist: int = self._jump.distance_units(a, b)
            cost: int = dist & 0xFF               # TSYSTEM_DISTANCE_LO (2222-2230)
            refuel_needed: bool = fuel < cost
            refuel_cost: float = 0.0
            if refuel_needed:
                refuel_cost = round(
                    (FUEL_TANK_CAPACITY - fuel) * FUEL_PRICE_PER_UNIT_CR, 2)
                fuel = float(FUEL_TANK_CAPACITY)
            fuel -= cost
            legs.append({
                "system_index": b,
                "system_name": self.system_name(b),
                "distance_ly": dist / 10.0,
                "fuel_cost": cost,
                "fuel_after": int(round(fuel)),
                "refuel_needed": refuel_needed,
                "refuel_cost": refuel_cost,
            })
        return legs


# --------------------------------------------------------------------------
# ProfitAnalyzer — trade profitability
# --------------------------------------------------------------------------


class ProfitAnalyzer:
    """
    Trade profitability analysis within a radius of `max_jumps` jumps.

    Deal fields:
      item_name, origin_name, target_index, target_name, route,
      buy_price, sell_price, profit_per_unit, quantity, profit_total,
      fuel_used (units), fuel_cost_total (Cr = usage * 0.2), refuel_cost_total (Cr),
      net_profit = profit_total - fuel_cost_total - refuel_cost_total.
    Fuel price — 0.2 Cr/unit (src/code_6a00.asm:2412-2416).
    Cargo capacity — SHIP_HOLD (src/save_data.asm:169).
    """

    def __init__(self, route_finder: RouteFinder) -> None:
        self.routes: RouteFinder = route_finder

    # ------------------------------------------------------------ deals

    def find_best_deals(
        self, game_state: GameState, item_name: str, max_jumps: int = 1
    ) -> list[dict[str, int | float | str | list[int]]]:
        """
        All deals on `item_name` for systems within max_jumps, sorted by
        net_profit (descending).
        """
        idx: int = game_state.market.index(item_name)
        start: int = game_state.system_index
        origin_name: str = str(game_state.system["name"])

        buy_price: float = game_state.market.price_cr(idx)
        available: int = game_state.market.available(idx)
        if idx <= 12:                                # Food..Minerals — tonnes
            capacity: int = SHIP_HOLD - game_state.cargo_weight
        else:                                        # Gold+ — up to 200 units/kg
            capacity = PRECIOUS_LIMIT - game_state.cargo[idx]
        quantity: int = min(available, capacity)
        if quantity <= 0:
            return []

        current_fuel: int = int(round(game_state.fuel))
        deals: list[dict[str, int | float | str | list[int]]] = []
        for target, _depth in self.routes.find_reachable(start, max_jumps):
            if target == start:
                continue
            legs = self.routes.find_route_with_fuel(start, target, current_fuel)
            if legs is None:
                continue
            market_target: MarketEngine = MarketEngine(
                game_state.generator, target, game_state.galaxy)
            sell_price: float = market_target.price_cr(idx)

            profit_per_unit: float = sell_price - buy_price
            profit_total: float = round(profit_per_unit * quantity, 2)
            fuel_used: int = sum(int(l["fuel_cost"]) for l in legs)
            refuel_cost: float = round(
                sum(float(l["refuel_cost"]) for l in legs), 2)
            fuel_cost_cr: float = round(fuel_used * FUEL_PRICE_PER_UNIT_CR, 2)
            net_profit: float = round(
                profit_total - fuel_cost_cr - refuel_cost, 2)

            deals.append({
                "item_name": COMMODITIES[idx],
                "origin_name": origin_name,
                "target_index": target,
                "target_name": self.routes.system_name(target),
                "route": self.routes.find_route(start, target) or [],
                "buy_price": round(buy_price, 2),
                "sell_price": round(sell_price, 2),
                "profit_per_unit": round(profit_per_unit, 2),
                "quantity": quantity,
                "profit_total": profit_total,
                "fuel_used": fuel_used,
                "fuel_cost_total": fuel_cost_cr,
                "refuel_cost_total": refuel_cost,
                "net_profit": net_profit,
            })

        deals.sort(key=lambda d: float(d["net_profit"]), reverse=True)
        return deals

    def find_best_deals_all_items(
        self, game_state: GameState, max_jumps: int = 1, top_n: int = 10
    ) -> list[dict[str, int | float | str | list[int]]]:
        """Top-N deals across all commodities (except Alien Items, which are
        unavailable on the market, src/code_6a00.asm:2094)."""
        all_deals: list[dict[str, int | float | str | list[int]]] = []
        for i, name in enumerate(COMMODITIES):
            if i == 16:                     # Alien Items
                continue
            try:
                all_deals.extend(self.find_best_deals(game_state, name, max_jumps))
            except MarketError:
                continue
        all_deals.sort(key=lambda d: float(d["net_profit"]), reverse=True)
        return all_deals[:top_n]


# --------------------------------------------------------------------------
# Module test (no CLI)
# --------------------------------------------------------------------------

if __name__ == "__main__":
    # Initialisation: galaxy 0, TIBEDI, fuel 70, credits 100
    gs = GameState(galaxy=0, system_index=0, fuel=70.0, credits=100.0)
    gs.load_system()
    logger = EventLogger("elite_events.db")
    routes = RouteFinder(gs.generator, gs.galaxy)
    analyzer = ProfitAnalyzer(routes)

    print(f"=== Status: #{gs.system_index} {gs.system['name']} "
          f"({gs.system['economy_name']}), fuel {gs.fuel:.0f}/70, "
          f"credits {gs.credits:.2f} Cr ===\n")

    print("=== Route TIBEDI -> AZAQUA (#19) ===")
    route = routes.find_route(0, 19)
    print(f"  shortest route: {route}")
    for leg in routes.find_route_with_fuel(0, 19, int(round(gs.fuel))) or []:
        print(f"  #{leg['system_index']:>3} {leg['system_name']:<10} "
              f"{leg['distance_ly']:>4.1f} ly  fuel cost {leg['fuel_cost']:>3} "
              f"refuel: {'yes' if leg['refuel_needed'] else 'no'}")

    print("\n=== Best Food deals (top-3) ===")
    food_deals = analyzer.find_best_deals(gs, "Food", max_jumps=1)[:3]
    for d in food_deals:
        print(f"  {d['target_name']:<10} buy {d['buy_price']:.2f} -> "
              f"sell {d['sell_price']:.2f} Cr  profit/unit {d['profit_per_unit']:+.2f} "
              f"total {d['profit_total']:+.2f}  fuel {d['fuel_used']} units "
              f"refuel {d['refuel_cost_total']:.2f}  NET {d['net_profit']:+.2f} Cr")

    print("\n=== Trading loop (logged into SQLite) ===")
    logger.capture(gs)
    cost = gs.buy("Food", 10)                       # 10 x 9.6 = 96.00 Cr
    logger.log_buy(gs, "Food", 10, cost / 10, cost)
    print(f"  buy Food 10: {cost:.2f} Cr, credits {gs.credits:.2f} Cr")

    logger.capture(gs)
    res = gs.jump(71)                                # EDINSOIN, 1.6 ly, 16 units
    logger.log_jump(gs, 71, str(gs.system["name"]),
                    float(res.distance_ly), int(res.fuel_cost))
    print(f"  jump -> #{71} {gs.system['name']}: {res.distance_ly:.1f} ly, "
          f"fuel cost {res.fuel_cost} units, fuel {gs.fuel:.0f}")

    logger.capture(gs)
    income = gs.sell("Food", 10)
    logger.log_sell(gs, "Food", 10, income / 10, income)
    print(f"  sell Food 10: {income:.2f} Cr, credits {gs.credits:.2f} Cr")

    print("\n=== Database contents (SELECT * FROM transactions) ===")
    for row in logger.all_rows():
        print(f"  #{row['id']:>2} {row['timestamp']} | {row['action']:<7} "
              f"{row['system_name']:<8} item={row['item']} "
              f"qty={row['quantity']} fuel {row['fuel_before']}->{row['fuel_after']} "
              f"cr {row['credits_before']:.2f}->{row['credits_after']:.2f} "
              f"w {row['cargo_weight_before']}->{row['cargo_weight_after']}")
    logger.close()