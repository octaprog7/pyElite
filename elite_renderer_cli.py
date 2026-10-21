"""
elite_renderer_cli.py — терминальный рендерер для pyElite.

Реализация протокола Renderer (elite_backend) чистым stdout: без pygame,
без графики. Предназначен для headless-режима, CI и отладки. Ввод
обрабатывается через input() в игровом цикле, поэтому poll_events()
возвращает пустой список, а tick() — 0.

Работает с реальными интерфейсами elite_core: SystemRow/MarketRow — словари,
near_systems() → [(index, name, dist_units, cost), ...].

Лицензия: GPL v3.
"""

from __future__ import annotations

import os

from elite_backend import GameEvent, RenderState, Renderer
from elite_core import (
    FUEL_TANK_CAPACITY,
    SHIP_DEFENSE_MAX,
    SHIP_HOLD,
    CombatResult,
    GameState,
    ShipDefense,
    SystemRow,
)
from elite_i18n import I18n, commodity_display

__all__ = ["CLIRenderer"]


class CLIRenderer(Renderer):
    """Текстовый рендерер: состояние выводится в терминал через print()."""

    def __init__(self, **kwargs) -> None:
        del kwargs  # параметры бекенда не используются (совместимость фабрики)
        self._state: RenderState = RenderState.DOCKED
        self._active: bool = True
        self._jump_target: int | None = None

    # ------------------------------------------------------------------ API

    def init(self) -> None:
        """Очистить экран и напечатать заголовок."""
        os.system("cls" if os.name == "nt" else "clear")
        print("pyElite (CLI mode)")
        print("=" * 60)

    def set_state(self, state: RenderState) -> None:
        self._state = state

    def render(self, game_state: GameState, i18n: I18n) -> None:
        """Отрисовать текущий режим."""
        if self._state == RenderState.DOCKED:
            self._render_docked(game_state, i18n)
        elif self._state == RenderState.MAP:
            self._render_map(game_state, i18n)
        elif self._state == RenderState.COMBAT:
            self._render_combat(game_state, i18n)
        else:  # FLIGHT / JUMP
            self._render_flight(game_state, i18n)

    def render_jump_progress(
        self, game_state: GameState, i18n: I18n, progress: float
    ) -> None:
        pct: int = int(progress * 100)
        print(i18n.tr("render.jump.progress", pct=pct))
        if progress >= 1.0:
            print(i18n.tr("render.jump.complete"))

    def render_combat_round(
        self,
        game_state: GameState,
        i18n: I18n,
        round_num: int,
        total_rounds: int,
        enemy_damage: int,
        result: CombatResult | None,
    ) -> None:
        print(i18n.tr("render.combat.round",
                      round_num=round_num, total_rounds=total_rounds))
        print(i18n.tr("render.combat.enemy_damage", enemy_damage=enemy_damage))
        defense: ShipDefense = game_state.defense
        print(
            f"FSH={defense.forward_shield} "
            f"ASH={defense.aft_shield} "
            f"ENERGY={defense.energy}"
        )
        if result is not None:
            if result.destroyed:
                print(i18n.tr("render.combat.result_destroyed",
                              status=result.status))
            else:
                print(i18n.tr("render.combat.result", status=result.status))

    def poll_events(self) -> list[GameEvent]:
        """В CLI нет event loop; ввод обрабатывается через input()."""
        return []

    def tick(self) -> int:
        """CLI не имеет FPS."""
        return 0

    def shutdown(self) -> None:
        print("Goodbye, Commander.")
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def get_jump_target(self) -> int | None:
        target = self._jump_target
        self._jump_target = None
        return target

    def show_message(self, msg: str) -> None:
        """No-op: сообщения печатает game_loop_gui через print()."""
        pass

    # ------------------------------------------------------------- rendering

    def _render_docked(self, game_state: GameState, i18n: I18n) -> None:
        """Статус, описание планеты, рынок и подсказка команд."""
        st = game_state
        sys_row: SystemRow = st.system
        print(i18n.tr("cmd.status.system", index=st.system_index,
                      name=sys_row["name"]))
        print(i18n.tr("cmd.status.economy", name=sys_row["economy_name"]))
        print(i18n.tr("cmd.status.government",
                      name=sys_row["government_name"]))
        print(i18n.tr("cmd.status.fuel", fuel=int(round(st.fuel)),
                      max_fuel=FUEL_TANK_CAPACITY, fuel_ly=st.fuel / 10.0))
        print(i18n.tr("cmd.status.cargo", cargo=st.cargo_weight,
                      hold=SHIP_HOLD))
        print(i18n.tr("cmd.status.credits", credits=st.credits))
        defense: ShipDefense = st.defense
        print(i18n.tr("cmd.status.defense", fsh=defense.forward_shield,
                      ash=defense.aft_shield, energy=defense.energy))
        print("-" * 60)
        description: str = st.generate_description(lang=i18n.locale)
        print(i18n.tr("cmd.info.title"))
        print(description)
        print("-" * 60)
        self._render_market(game_state, i18n)
        print("-" * 60)
        print("Commands: status | market | near | buy <item> <qty> | "
              "sell <item> <qty> | jump <idx> | refuel | route <idx> | "
              "combat <fight|escape|surrender> | info | save | load | lang")

    def _render_market(self, game_state: GameState, i18n: I18n) -> None:
        """Таблица рынка: 17 категорий COMMODITIES."""
        header: str = f"{'#':<3}{'Item':<16}{'Price(Cr)':>10}{'Qty(t)':>9}"
        print(header)
        for index, row in enumerate(game_state.market):
            name: str = (commodity_display(index, i18n.locale)
                         or str(row["name"]))
            price: float = float(row["price_buy_cr"])
            qty: int = int(row["available"])
            marker: str = ""
            if index == 16 and qty == 0:      # Alien Items недоступны
                marker = " (unavailable)"
            print(f"{index:<3}{name:<16}{price:>10.1f}{qty:>9}{marker}")

    def _render_map(self, game_state: GameState, i18n: I18n) -> None:
        """Список 256 систем; текущая помечена >>, доступные — *."""
        st = game_state
        print(i18n.tr("render.map.title", index=st.system_index,
                      name=st.system["name"]))
        reachable: dict[int, bool] = {i: True for i, _, _, _ in st.near_systems()}
        # индекс системы берём из enumerate — единый подход с
        # PygameRenderer._render_map (не зависит от ключа словаря SystemRow)
        for idx, sys_row in enumerate(st.systems):
            mark: str = ">>" if idx == st.system_index else " *" if idx in reachable else "  "
            print(f"{idx:>3} {mark} {sys_row['name']:<12} "
                  f"x={sys_row['x']:<3} y={sys_row['y']:<3} "
                  f"{sys_row['economy_name']:<18} {sys_row['government_name']}")

    def _render_flight(self, game_state: GameState, i18n: I18n) -> None:
        """Полёт: система, координаты, топливо, кредиты, щиты, груз."""
        st = game_state
        sys_row: SystemRow = st.system
        print(i18n.tr("render.flight.title"))
        print(i18n.tr("render.flight.system", index=st.system_index,
                      name=sys_row["name"], x=sys_row["x"], y=sys_row["y"]))
        print(i18n.tr("render.flight.fuel_credits", fuel=st.fuel,
                      max_fuel=FUEL_TANK_CAPACITY, credits=st.credits))
        defense: ShipDefense = st.defense
        print(i18n.tr("render.flight.defense", fsh=defense.forward_shield,
                      ash=defense.aft_shield, energy=defense.energy))
        print(i18n.tr("render.flight.cargo", cargo=st.cargo_weight,
                      hold=SHIP_HOLD))

    def _render_combat(self, game_state: GameState, i18n: I18n) -> None:
        """Бой: предупреждение и подсказка действий."""
        print(i18n.tr("render.combat.attack"))
        print(i18n.tr("render.combat.actions"))