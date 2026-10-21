#!/usr/bin/env python3
"""
analyze_endings.py — анализ причин окончания игр ботов из elite_events.db.

Использование:
    python analyze_endings.py [elite_events.db] [--player-id N]

Если путь не указан — используется elite_events.db в текущей директории.
--player-id N — анализировать только записи указанной версии бота
(по умолчанию — все версии).
"""

import argparse
import sys
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DB_PATH: str = "elite_events.db"   # переопределяется в main() из аргументов


@dataclass
class GameSegment:
    """Один запуск бота (от 100 Cr до конца)."""
    game_id: int
    start_idx: int
    end_idx: int
    events: list = field(default_factory=list)
    cause: str = ""
    cause_detail: str = ""

    @property
    def rounds(self) -> int:
        return len(self.events)

    @property
    def first_event(self) -> dict:
        return self.events[0] if self.events else {}

    @property
    def last_event(self) -> dict:
        return self.events[-1] if self.events else {}

    @property
    def final_credits(self) -> float:
        return (self.events[-1]["credits_after"] or 0.0) if self.events else 0.0

    @property
    def final_fuel(self) -> int:
        return (self.events[-1]["fuel_after"] or 0) if self.events else 0


def load_events(db_path: str, player_id: int | None = None) -> list[dict]:
    """Загрузить события из БД, отсортированные по id.

    player_id=None — все версии бота; иначе только записи указанного
    player_id (колонка добавлена миграцией; старые записи имеют 0).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM transactions"
    params: list[int] = []
    if player_id is not None:
        query += " WHERE player_id = ?"
        params.append(player_id)
    query += " ORDER BY id ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def segment_games(events: list[dict]) -> list[GameSegment]:
    """Разбить события на отдельные игры (запуски бота).

    Критерии начала новой игры:
      1. credits_before ≈ 100 после предыдущей игры с низкими кредитами (< 50)
      2. Большой разрыв по timestamp (> 120 секунд между событиями)
    """
    if not events:
        return []

    games: list[GameSegment] = []
    current = GameSegment(game_id=0, start_idx=events[0]["id"], end_idx=0)
    prev_credits_after = 0.0

    for ev in events:
        is_new_game = False

        if current.events and ev["credits_before"] is not None:
            cb = ev["credits_before"]
            if abs(cb - 100.0) < 10.0 and prev_credits_after < 50.0:
                is_new_game = True

        # Таймстемп-разрыв
        if current.events:
            try:
                t_prev = datetime.fromisoformat(
                    current.events[-1]["timestamp"].replace("Z", "+00:00"))
                t_curr = datetime.fromisoformat(
                    ev["timestamp"].replace("Z", "+00:00"))
                if (t_curr - t_prev).total_seconds() > 120:
                    is_new_game = True
            except (ValueError, AttributeError):
                pass

        if is_new_game:
            current.end_idx = current.events[-1]["id"]
            games.append(current)
            current = GameSegment(game_id=len(games), start_idx=ev["id"], end_idx=0)

        current.events.append(ev)
        prev_credits_after = ev["credits_after"] or 0.0

    if current.events:
        current.end_idx = current.events[-1]["id"]
        games.append(current)

    return games


def determine_cause(game: GameSegment) -> None:
    """Определить причину окончания игры.

    Категории:
      destroyed      — корабль уничтожен в бою
      bankrupt      — кредиты истощены (< 5 Cr), без боя в конце
      dead_end      — нет топлива, нет денег, нет достижимых систем
      piracy_drain  — систематические потери от пиратов (много surrender)
      user_stop     — игра остановлена пользователем (кредиты > 50)
      stall         — бот застрял (последние события — без прогресса)
      unknown       — не удалось определить
    """
    if not game.events:
        game.cause = "unknown"
        return

    last = game.last_event
    final_cr = game.final_credits
    final_fuel = game.final_fuel

    actions = Counter(ev["action"] for ev in game.events)
    combats = sum(1 for ev in game.events
                  if ev["action"] in ("fight", "escape", "surrender"))
    surrenders = actions.get("surrender", 0)
    escapes = actions.get("escape", 0)
    fights = actions.get("fight", 0)

    tail = game.events[-5:]

    # 1. Уничтожен в бою
    if last["action"] in ("fight", "escape", "surrender"):
        details = (last["details"] or "").lower()
        if any(w in details for w in ("destroy", "kill", "death", "взрыв", "погиб")):
            game.cause = "destroyed"
            game.cause_detail = (
                f"Корабль уничтожен в системе #{last['system_index']} "
                f"{last['system_name']} (действие: {last['action']})")
            return
        if final_cr < 1.0:
            game.cause = "destroyed"
            game.cause_detail = (
                f"Бой в системе #{last['system_index']} "
                f"{last['system_name']}, credits_after = {final_cr:.2f}")
            return

    # 2. Банкрот от пиратов: много сдач, кредиты падают
    if combats >= 3 and surrenders >= combats * 0.6 and final_cr < 10:
        combat_losses = sum(
            (ev["credits_before"] or 0) - (ev["credits_after"] or 0)
            for ev in game.events
            if ev["action"] in ("surrender", "escape", "fight")
            and (ev["credits_before"] or 0) - (ev["credits_after"] or 0) > 0
        )
        game.cause = "piracy_drain"
        game.cause_detail = (
            f"Потеряно {combat_losses:.1f} Cr от {combats} боёв "
            f"({surrenders} сдач, {escapes} побегов, {fights} боёв)")
        return

    # 3. Dead-end: мало топлива, мало кредитов
    if final_cr < 5.0 and final_fuel < 15:
        if last["action"] == "refuel":
            game.cause = "dead_end"
            game.cause_detail = (
                f"Заправка истощила кредиты ({final_cr:.2f} Cr), "
                f"топливо {final_fuel}/70")
            return
        if last["action"] == "jump":
            game.cause = "dead_end"
            game.cause_detail = (
                f"Прыжок оставил {final_fuel} топлива и {final_cr:.2f} Cr — "
                f"бот застрял")
            return
        if last["action"] in ("surrender", "escape", "fight") and final_cr < 5:
            game.cause = "dead_end"
            game.cause_detail = (
                f"После боя: {final_cr:.2f} Cr, {final_fuel} топлива — "
                f"нет средств для продолжения")
            return
        game.cause = "dead_end"
        game.cause_detail = f"Тупик: {final_cr:.2f} Cr, {final_fuel}/70 топлива"
        return

    # 4. Пользователь остановил (Ctrl-C)
    if final_cr > 50.0:
        game.cause = "user_stop"
        game.cause_detail = (
            f"Игра прервана при {final_cr:.2f} Cr, {final_fuel} топлива "
            f"(вероятно Ctrl-C)")
        return

    # 5. Stall: последние события без торговли
    tail_actions = [ev["action"] for ev in tail]
    has_trade = any(a in ("buy", "sell") for a in tail_actions)
    if not has_trade and final_cr < 30:
        game.cause = "stall"
        game.cause_detail = (
            f"Нет торговли в последних {len(tail)} событиях, "
            f"кредиты {final_cr:.2f}")
        return

    # 6. Unknown
    game.cause = "unknown"
    game.cause_detail = (
        f"Не удалось определить (кредиты {final_cr:.2f}, "
        f"топливо {final_fuel}, последнее действие: {last['action']})")


def print_report(
    games: list[GameSegment], player_id: int | None = None
) -> None:
    """Вывести отчёт по причинам окончания игр."""

    W = 72
    print("=" * W)
    print("  АНАЛИЗ ПРИЧИН ОКОНЧАНИЯ ИГР БОТОВ")
    print(f"  База данных: {DB_PATH}")
    pid_str = "ALL" if player_id is None else str(player_id)
    print(f"  Player ID: {pid_str}")
    print("=" * W)

    if not games:
        print("\n  Нет данных — БД пуста или не найдена.")
        print(f"  Путь: {Path(DB_PATH).absolute()}")
        return

    total_games = len(games)
    cause_counts = Counter(g.cause for g in games)

    print(f"\n  Всего игр: {total_games}")
    print(f"  Всего событий: {sum(g.rounds for g in games)}")

    # Сводка по причинам
    print(f"\n  {'Причина':<16} {'Игр':>5} {'Доля':>7} {'Avg Cr':>9} "
          f"{'Avg rounds':>11} {'Avg combats':>12}")
    print("  " + "-" * 68)

    for cause in ["destroyed", "piracy_drain", "dead_end", "stall",
                   "user_stop", "unknown"]:
        subset = [g for g in games if g.cause == cause]
        if not subset:
            continue
        avg_cr = sum(g.final_credits for g in subset) / len(subset)
        avg_rounds = sum(g.rounds for g in subset) / len(subset)
        avg_combats = sum(
            sum(1 for ev in g.events
                if ev["action"] in ("fight", "escape", "surrender"))
            for g in subset) / len(subset)
        pct = len(subset) / total_games * 100
        print(f"  {cause:<16} {len(subset):>5} {pct:>6.1f}% "
              f"{avg_cr:>8.1f}Cr {avg_rounds:>10.0f} {avg_combats:>11.1f}")

    # Детали по каждой игре
    print(f"\n{'=' * W}")
    print("  ДЕТАЛИ ПО ИГРАМ")
    print(f"{'=' * W}")

    for g in games:
        last = g.last_event
        first = g.first_event

        actions = Counter(ev["action"] for ev in g.events)
        combats = sum(1 for ev in g.events
                      if ev["action"] in ("fight", "escape", "surrender"))
        buys = actions.get("buy", 0)
        sells = actions.get("sell", 0)
        jumps = actions.get("jump", 0)
        refuels = actions.get("refuel", 0)

        # Потери от пиратов
        combat_loss = sum(
            (ev["credits_before"] or 0) - (ev["credits_after"] or 0)
            for ev in game.events
            if ev["action"] in ("surrender", "escape", "fight")
            and (ev["credits_before"] or 0) - (ev["credits_after"] or 0) > 0
        )

        # Затраты на топливо
        fuel_spent = sum(
            ev["total_cost"] for ev in g.events
            if ev["action"] == "refuel" and ev["total_cost"]
        )

        print(f"\n  Игра #{g.game_id} | Событий: {g.rounds} | "
              f"Кредиты: {first.get('credits_before', 0):.1f} -> "
              f"{g.final_credits:.2f} Cr")
        print(f"  Причина: {g.cause}")
        print(f"  Детали:  {g.cause_detail}")
        print(f"  Прыжков: {jumps} | Покупок: {buys} | Продаж: {sells} | "
              f"Заправок: {refuels} | Боёв: {combats}")
        print(f"  Потери от пиратов: {combat_loss:.1f} Cr | "
              f"Затраты на топливо: {fuel_spent:.1f} Cr")

        # Последние 3 события
        print(f"  Последние события:")
        for ev in g.events[-3:]:
            action = ev["action"]
            sys_name = ev["system_name"] or "?"
            cr = ev["credits_after"]
            fuel = ev["fuel_after"]
            details = (ev["details"] or "")[:60]
            print(f"    [{action:<10}] {sys_name:<12} "
                  f"cr={cr:>7.2f} fuel={fuel:>3}/70 {details}")

    # Анализ трендов
    if total_games >= 2:
        print(f"\n{'=' * W}")
        print("  ТРЕНДЫ")
        print(f"{'=' * W}")

        # Выживаемость по порядку игр
        print(f"\n  Выживаемость по играм:")
        for g in games:
            bar_len = min(g.rounds, 60)
            bar = "#" * (bar_len // 5) if bar_len > 0 else ""
            print(f"    Игра #{g.game_id:>2}: {g.rounds:>4} событий "
                  f"[{bar:<12}] {g.cause}")

        # Топ опасных систем
        danger_systems: dict[str, dict] = defaultdict(
            lambda: {"combats": 0, "games": set()})
        for g in games:
            for ev in g.events:
                if ev["action"] in ("surrender", "escape", "fight"):
                    key = f"#{ev['system_index']} {ev['system_name']}"
                    danger_systems[key]["combats"] += 1
                    danger_systems[key]["games"].add(g.game_id)

        if danger_systems:
            print(f"\n  Топ опасных систем (по числу боёв):")
            sorted_danger = sorted(
                danger_systems.items(), key=lambda x: x[1]["combats"],
                reverse=True)[:10]
            for name, info in sorted_danger:
                print(f"    {name:<20} боёв: {info['combats']:>3} "
                      f"в {len(info['games'])} играх")

        # Корреляция: бои → банкротство
        print(f"\n  Связь боёв и результата:")
        for g in games:
            combats = sum(1 for ev in g.events
                          if ev["action"] in ("fight", "escape", "surrender"))
            if combats > 0:
                loss_per_combat = (100.0 - g.final_credits) / combats
                print(f"    Игра #{g.game_id}: {combats} боёв, "
                      f"потеря {loss_per_combat:.1f} Cr/бой, "
                      f"итог: {g.cause}")

    print(f"\n{'=' * W}")
    print("  КОНЕЦ ОТЧЁТА")
    print(f"{'=' * W}")


def main() -> None:
    global DB_PATH
    parser = argparse.ArgumentParser(
        description="Анализ причин окончания игр ботов из elite_events.db")
    parser.add_argument(
        "db", nargs="?", default="elite_events.db",
        help="путь к elite_events.db (по умолчанию elite_events.db "
             "в текущей директории)")
    parser.add_argument(
        "--player-id", type=int, default=None,
        help="Фильтр по player_id (None — все игроки)")
    args = parser.parse_args()

    DB_PATH = args.db
    db = Path(args.db)
    if not db.exists():
        print(f"База данных не найдена: {db.absolute()}")
        sys.exit(1)

    events = load_events(str(db), args.player_id)
    games = segment_games(events)

    for g in games:
        determine_cause(g)

    print_report(games, args.player_id)


if __name__ == "__main__":
    main()
