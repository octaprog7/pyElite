"""
pyElite — CLI-игровой цикл (торговля + гиперпрыжки в консоли).

Собирает три детерминированных порта (генератор галактик, рынок, гипердрайв)
в единую партию: прыжки, торговля, заправка, статус, сохранение/загрузка.
Никаких внешних зависимостей; модуль `random` не используется — все расчёты
детерминированы.

Интерфейсные строки локализуются через elite_i18n.I18n (языки en/ru/es);
команда `lang` переключает язык на лету.

Откуда взята логика (строки `src/` и модулей `rework/`):

1. Параметры системы (экономика, правительство, имя):
   - src/code_6a00.asm:556-653 (get_system_info/TT24);
     rework/elite_galaxy_generator.py:197-267.
2. Цены/наличие товаров, покупка и продажа:
   - src/code_6a00.asm:1951-1977 (TT151, цена), 2131-2165 (_7365, наличие),
     990-1005 (покупка), 1174-1185 (продажа);
     rework/elite_core.py (MarketEngine/GameState).
3. Вместимость трюма Cobra MkIII — 22 т: src/save_data.asm:169
   (rework/elite_core.py, SHIP_HOLD).
4. Расстояние между системами, формула _TT111:
   sqrt(dX^2 + (dY>>1)^2) * 4, единицы = 0.1 св. года:
   - src/code_6a00.asm:1631-1724; rework/elite_jumps.py:133-175.
5. Расход топлива = младший байт 16-битного расстояния:
   - src/code_6a00.asm:2222-2230 (_73dd); rework/elite_jumps.py:179-186.
6. Проверка прыжка (RANGE?): старший байт расстояния != 0 или топлива
   меньше расхода -> прыжок невозможен:
   - src/code_6a00.asm:1793-1799; rework/elite_jumps.py:188-211.
7. Топливный бак: максимум 70 ед. = 7.0 св. лет (src/save_data.asm:160:
   ".byte 70 ; PLAYER_FUEL, '7.0'"; src/code_6a00.asm:858 "(max fuel is
   70)"; 2412: "lda # $46"). Заправка ВСЕГДА до полного бака
   (src/code_6a00.asm:2465-2466: "ldx # $46 / stx PLAYER_FUEL");
   бесплатный полный бак нового корабля после гибели —
   src/code_28ba.asm:2068-2071.
8. Цена топлива: (70 - fuel) x 2 внутренних единиц (0.1 Cr) = 0.2 Cr за
   1 ед. топлива (2.0 Cr за 1 св. год): src/code_6a00.asm:2412-2416;
   масштаб цен price_list (единица = 0.1 Cr): src/code_6a00.asm:2725-2738;
   списание денег: src/code_6a00.asm:2298-2315 (_745a), отказ при
   нехватке кредитов: src/code_6a00.asm:2613-2614.
9. Стартовые деньги Джеймсона: 1000 внутренних единиц = "100.00 cr"
   (src/save_data.asm:159; rework/elite_core.py, STARTING_CASH_UNITS).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from elite_core import (
    COMMODITIES,
    MarketEngine,
    MarketError,
    PRECIOUS_LIMIT,
    SHIP_HOLD,
    FUEL_TANK_CAPACITY,
    FUEL_PRICE_PER_UNIT_CR,
    ENGINE_MAX_RANGE_UNITS,
    Cargo,
    SystemRow,
    commodity_index,
    ShipDefense,
    GalaxyGenerator,
    GalaxyGenerator as EliteGalaxyGenerator,
    JumpEngine as Hyperdrive,
    GameState as CoreGameState,
    SystemDescriptionEngine,
)
from elite_analytics import EventLogger, ProfitAnalyzer, RouteFinder
from elite_i18n import I18n, commodity_display
from elite_line_editor import LineEditor

# --------------------------------------------------------------------------
# Constants (see docstring, items 3, 7, 8, 9)
# --------------------------------------------------------------------------

GALAXIES: Final[int] = 8                # galaxies in the game (counter & %11110111)
SYSTEMS_PER_GALAXY: Final[int] = 256    # systems per galaxy
STARTING_FUEL: Final[int] = FUEL_TANK_CAPACITY
STARTING_CREDITS_CR: Final[float] = 100.0   # 1000 units = 100.00 Cr (see item 9)

LOG_DIR: Final[Path] = Path("log")
LOG_FILE: Final[Path] = LOG_DIR / "game_log.csv"
LOG_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "action",
    "details",
    "credits_before",
    "credits_after",
    "fuel_before",
    "fuel_after",
    "cargo_weight_before",
    "cargo_weight_after",
)

@dataclass(frozen=True)
class LogPoint:
    """Снимок финансового состояния для лога события."""

    credits: float
    fuel: float
    cargo_weight: int


class GameLogger:
    """CSV-лог сделок и прыжков (log/game_log.csv)."""

    def __init__(self, path: Path | str = LOG_FILE) -> None:
        self.path: Path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Счётчик записей поддерживается в памяти; если файл уже существует
        # (перезапуск игры), считаем существующие строки один раз.
        self._count: int = 0
        if self.path.exists():
            with self.path.open("r", newline="", encoding="utf-8") as fh:
                self._count = max(sum(1 for _ in csv.reader(fh)) - 1, 0)
        else:
            with self.path.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(LOG_COLUMNS)

    def log(self, action: str, details: str, before: LogPoint, after: LogPoint) -> str:
        """Дописать одну CSV-строку и вернуть её текстом."""
        row: list[str] = [
            datetime.now().astimezone().isoformat(timespec="seconds"),
            action,
            details,
            f"{before.credits:.2f}",
            f"{after.credits:.2f}",
            f"{before.fuel:.1f}",
            f"{after.fuel:.1f}",
            str(before.cargo_weight),
            str(after.cargo_weight),
        ]
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(row)
        self._count += 1
        return ",".join(row)

    def last_row(self) -> str:
        """Последняя запись лога (пустая строка, если лог пуст)."""
        with self.path.open("r", newline="", encoding="utf-8") as fh:
            rows: list[list[str]] = list(csv.reader(fh))
        return ",".join(rows[-1]) if len(rows) > 1 else ""

    def __len__(self) -> int:
        """Количество записей в логе (без строки заголовка), O(1)."""
        return self._count


class GameState:
    """
    Единое состояние партии.

    Поля: galaxy, system_index, fuel, credits, cargo (источник истины для
    денег/груза), а также generator, market, hyperdrive. После любого прыжка
    рынок пересоздаётся через load_system() с переносом денег/груза.
    """

    def __init__(
        self,
        galaxy: int = 0,
        system_index: int = 0,
        fuel: float = float(STARTING_FUEL),
        credits: float = STARTING_CREDITS_CR,
        cargo: Cargo | None = None,
    ) -> None:
        self.generator: EliteGalaxyGenerator = EliteGalaxyGenerator()
        self.galaxy: int = galaxy & 0x07
        self.system_index: int = system_index & 0xFF
        self.fuel: float = float(fuel)
        self.credits: float = float(credits)
        self.cargo: Cargo = (
            list(cargo) if cargo is not None else [0] * len(COMMODITIES)
        )

        self.hyperdrive: Hyperdrive = Hyperdrive(self.generator, self.galaxy)
        self.market: MarketEngine = self._build_market()
        self.defense: ShipDefense = ShipDefense()

        self._systems_cache: list[SystemRow] | None = None
        self._systems_cache_galaxy: int | None = None

    # ------------------------------------------------------------- pythonic API

    def __str__(self) -> str:
        """Краткий статус: галактика, система, топливо, кредиты, груз."""
        return (
            f"Galaxy {self.galaxy} | #{self.system_index} "
            f"{self.system['name']} ({self.system['economy_name']}) | "
            f"Fuel {self.fuel:.0f}/{FUEL_TANK_CAPACITY} "
            f"({self.fuel / 10:.1f} ly) | "
            f"{self.credits:.2f} Cr | "
            f"Cargo {self.cargo_weight}/{SHIP_HOLD} t"
        )

    # ------------------------------------------------------------- map

    @property
    def systems(self) -> list[SystemRow]:
        """Карта текущей галактики (кешируется; инвалидация по galaxy)."""
        if self._systems_cache is None or self._systems_cache_galaxy != self.galaxy:
            self._systems_cache = self.generator.generate_galaxy(self.galaxy)
            self._systems_cache_galaxy = self.galaxy
        return self._systems_cache

    @property
    def system(self) -> SystemRow:
        """Данные текущей системы."""
        return self.systems[self.system_index]

    # ------------------------------------------------------------- market

    def _build_market(self) -> MarketEngine:
        """
        Создать рынок текущей системы (stateless по деньгам/грузу).

        MarketEngine не хранит состояние партии — деньги и груз живут в
        GameState; единственная мутация рынка — commit_buy (доступность),
        привязанная к инстансу (место + сессия стыковки).
        """
        return MarketEngine(self.generator, self.system_index, self.galaxy)

    def load_system(self) -> None:
        """Пересоздать рынок для текущей системы (детерминированно)."""
        self.market = self._build_market()
        self.defense.reset()   # док = полная перезарядка (RES4: FSH=ASH=ENERGY=$FF)

    # ------------------------------------------------------------- fuel

    def update_fuel(self, amount: float) -> float:
        """Изменить топливо на `amount` с ограничением [0, MAX_FUEL]."""
        self.fuel = min(max(self.fuel + amount, 0.0), float(FUEL_TANK_CAPACITY))
        return self.fuel

    @property
    def fuel_units_int(self) -> int:
        """Топливо целыми единицами (формат Hyperdrive)."""
        return int(round(self.fuel))

    @property
    def cargo_weight(self) -> int:
        """Занятые тонны трюма (Food..Minerals, как считает игра)."""
        return sum(self.cargo[:13])

    def system_name(self, system_index: int) -> str:
        """Имя системы по индексу (для сообщений о прыжке)."""
        return str(self.systems[system_index]["name"])

    def generate_description(self, lang: str = "en") -> str:
        """Детерминированное описание текущей планеты («goat soup»).

        lang="en" — оригинальные таблицы; "ru"/"es" — переводы из
        elite_i18n. Используется существующий self.generator (не создаётся
        новый GalaxyGenerator на каждый вызов — кеш галактик генератора
        работает).
        """
        return SystemDescriptionEngine(self.generator).generate_description(
            self.system_index, galaxy=self.galaxy, lang=lang)


class GameLoop:
    """Консольный игровой цикл: разбор и исполнение команд."""

    def __init__(
        self,
        state: GameState | None = None,
        logger: GameLogger | None = None,
    ) -> None:
        self.state: GameState = state if state is not None else GameState()
        self.logger: GameLogger = logger if logger is not None else GameLogger()
        self.events: EventLogger = EventLogger()   # SQLite event log
        self._routes: dict[int, RouteFinder] = {}  # graph cache per galaxy
        self.i18n: I18n = I18n(locale="en")        # interface localization
        # Line editor с историей команд (MC-style, см. elite_line_editor.py).
        # История персистится в .elite_history рядом с game_loop.py (cwd).
        self.editor: LineEditor = LineEditor(
            prompt="> ",
            history_file=".elite_history",
        )

    # ------------------------------------------------------------- helpers

    def _point(self) -> LogPoint:
        """Снимок состояния до/после события (для лога)."""
        st = self.state
        return LogPoint(
            credits=st.credits,
            fuel=st.fuel,
            cargo_weight=st.cargo_weight,
        )

    def _core_state(self) -> CoreGameState:
        """Снимок текущей партии как elite_core.GameState (для аналитики)."""
        st = self.state
        core = CoreGameState(
            galaxy=st.galaxy,
            system_index=st.system_index,
            fuel=st.fuel,
            credits=st.credits,
            cargo=list(st.cargo),
            event_logger=self.events,   # события пишутся автоматически
        )
        # ВАЖНО (намеренный паттерн, НЕ баг): core.defense — ЭТО ССЫЛКА на
        # st.defense. resolve_combat_action() мутирует этот объект прямо,
        # и тем самым передаёт урон обратно в CLI GameState, минуя копию.
        # Это осознанный способ синхронизации защиты после боя — не менять.
        core.defense = st.defense
        # Рынок переиспользуется: commit_buy (доступность) сохраняется в
        # пределах сессии стыковки (load_system() пересоздаёт рынок).
        core.market = st.market
        return core

    def _route_finder(self) -> RouteFinder:
        """RouteFinder для текущей галактики (граф кешируется по galaxy).

        Переиспользуется генератор из GameState (self.state.generator):
        его кеш галактик делится с остальными движками, новый
        GalaxyGenerator() не создаётся.
        """
        galaxy = self.state.galaxy
        rf = self._routes.get(galaxy)
        if rf is None:
            rf = RouteFinder(self.state.generator, galaxy)
            self._routes[galaxy] = rf
        return rf

    def _parse_item_qty(self, args: list[str], verb: str) -> tuple[str | int | None, int]:
        """Разобрать '<товар> <кол-во>' -> (товар, количество) или (None, 0)."""
        if len(args) < 2:
            print(self.i18n.tr("parse.usage", verb=verb))
            return None, 0
        try:
            qty = int(args[-1])
        except ValueError:
            print(self.i18n.tr("parse.not_integer", value=args[-1]))
            return None, 0
        if qty <= 0:
            print(self.i18n.tr("parse.not_positive"))
            return None, 0
        item: str | int = " ".join(args[:-1])
        return (int(item) if item.isdigit() else item), qty

    # ------------------------------------------------------------- commands

    def cmd_status(self) -> None:
        """Текущая система, топливо, груз, кредиты."""
        st = self.state
        sys = st.system
        print(self.i18n.tr("cmd.status.system",
                           index=st.system_index, name=sys["name"]))
        print(self.i18n.tr("cmd.status.economy", name=sys["economy_name"]))
        print(self.i18n.tr("cmd.status.government",
                           name=sys["government_name"]))
        print(self.i18n.tr("cmd.status.fuel",
                           fuel=int(round(st.fuel)), max_fuel=FUEL_TANK_CAPACITY,
                           fuel_ly=st.fuel / 10.0))
        print(self.i18n.tr("cmd.status.cargo",
                           cargo=st.cargo_weight, hold=SHIP_HOLD))
        print(self.i18n.tr("cmd.status.credits", credits=st.credits))
        d = st.defense
        print(self.i18n.tr("cmd.status.defense",
                           fsh=d.forward_shield, ash=d.aft_shield,
                           energy=d.energy))

    def cmd_market(self) -> None:
        """Таблица рынка текущей системы."""
        st = self.state
        print(self.i18n.tr("cmd.market.title",
                           index=st.system_index, name=st.system["name"],
                           economy=st.system["economy_name"]))
        print(self.i18n.tr("cmd.market.header"))
        print(self.i18n.tr("cmd.market.separator"))
        # Table rows — numeric data (no key in elite_i18n.py).
        for row in st.market:
            print(
                f"{row['name']:<15}{row['unit']:<5}{row['available']:>9}"
                f"{row['price_buy_cr']:>12.2f}{row['price_sell_cr']:>12.2f}"
            )

    def nearest_systems(self) -> list[tuple[int, str, int, int]]:
        """
        Системы, достижимые при текущем топливе (can_jump = True):
        (индекс, имя, расстояние в ед. 0.1 св. года, расход топлива).
        Сортировка по расстоянию.
        """
        st = self.state
        fuel = st.fuel_units_int
        result: list[tuple[int, str, int, int]] = []
        for i in range(SYSTEMS_PER_GALAXY):
            if i == st.system_index:
                continue
            if st.hyperdrive.can_jump(st.system_index, i, fuel):
                dist = st.hyperdrive.distance_units(st.system_index, i)
                result.append((i, st.system_name(i), dist, dist & 0xFF))
        result.sort(key=lambda r: r[2])
        return result

    def cmd_near(self) -> None:
        """Список систем в радиусе прыжка."""
        st = self.state
        near = self.nearest_systems()
        print(self.i18n.tr("cmd.near.title", fuel=int(round(st.fuel))))
        if not near:
            print(self.i18n.tr("cmd.near.empty"))
            return
        print(self.i18n.tr("cmd.near.header"))
        for index, name, dist, cost in near:
            print(self.i18n.tr("cmd.near.row", index=index, name=name,
                               dist_ly=dist / 10.0, cost=cost,
                               cost_ly=cost / 10.0))

    def cmd_buy(self, args: list[str]) -> None:
        """Купить товар: проверка рынка, денег и места в трюме."""
        item, qty = self._parse_item_qty(args, "buy")
        if item is None:
            return
        try:
            idx = commodity_index(item, self.i18n.locale)
            name = COMMODITIES[idx]        # каноническое имя — в лог/API
        except MarketError as exc:
            print(self.i18n.tr("cmd.buy.error", exc=str(exc)))
            return
        shown = commodity_display(idx, self.i18n.locale) or name
        st = self.state
        before = self._point()
        core = self._core_state()
        try:
            cost = core.buy(item, qty, lang=self.i18n.locale)
        except MarketError as exc:
            print(self.i18n.tr("cmd.buy.error", exc=str(exc)))
            return
        # синхронизация денег/груза (рынок — тот же объект; событие buy уже
        # записано в elite_events.db методом core.buy)
        st.credits = core.credits
        st.cargo = list(core.cargo)
        after = self._point()
        self.logger.log(
            "buy",
            f"{name} x{qty} at system #{st.system_index} {st.system['name']}",
            before,
            after,
        )
        print(self.i18n.tr("cmd.buy.done", qty=qty, name=shown, cost=cost,
                           credits=st.credits, cargo=st.cargo_weight,
                           hold=SHIP_HOLD))

    def cmd_sell(self, args: list[str]) -> None:
        """Продать товар: проверка наличия в трюме."""
        item, qty = self._parse_item_qty(args, "sell")
        if item is None:
            return
        try:
            idx = commodity_index(item, self.i18n.locale)
            name = COMMODITIES[idx]        # каноническое имя — в лог/API
        except MarketError as exc:
            print(self.i18n.tr("cmd.sell.error", exc=str(exc)))
            return
        shown = commodity_display(idx, self.i18n.locale) or name
        st = self.state
        before = self._point()
        core = self._core_state()
        try:
            income = core.sell(item, qty, lang=self.i18n.locale)
        except MarketError as exc:
            print(self.i18n.tr("cmd.sell.error", exc=str(exc)))
            return
        # синхронизация денег/груза (событие sell уже записано в SQLite)
        st.credits = core.credits
        st.cargo = list(core.cargo)
        after = self._point()
        self.logger.log(
            "sell",
            f"{name} x{qty} at system #{st.system_index} {st.system['name']}",
            before,
            after,
        )
        print(self.i18n.tr("cmd.sell.done", qty=qty, name=shown, income=income,
                           credits=st.credits, cargo=st.cargo_weight,
                           hold=SHIP_HOLD))

    def cmd_jump(self, args: list[str]) -> None:
        """Гиперпрыжок: can_jump -> execute_jump -> обновление состояния."""
        if len(args) != 1:
            print(self.i18n.tr("cmd.jump.usage"))
            return
        try:
            target = int(args[0])
        except ValueError:
            print(self.i18n.tr("cmd.jump.bad_index", value=args[0]))
            return
        st = self.state
        if not 0 <= target < SYSTEMS_PER_GALAXY:
            print(self.i18n.tr("cmd.jump.out_of_range",
                               target=target, max=SYSTEMS_PER_GALAXY - 1))
            return
        if target == st.system_index:
            print(self.i18n.tr("cmd.jump.already_here"))
            return

        fuel = st.fuel_units_int
        dist = st.hyperdrive.distance_units(st.system_index, target)
        cost = st.hyperdrive.calculate_fuel_cost(st.system_index, target)

        # can_jump check (src/code_6a00.asm:1793-1799): engine range
        # and sufficient fuel
        if not st.hyperdrive.can_jump(st.system_index, target, fuel):
            if (dist >> 8) != 0:
                print(self.i18n.tr("cmd.jump.too_far", dist_ly=dist / 10.0))
            else:
                print(self.i18n.tr("cmd.jump.no_fuel", cost=cost, fuel=fuel))
            return

        origin = st.system_index
        before = self._point()
        core = self._core_state()
        result = core.jump(target)
        if not result:
            # can_jump уже прошёл — отказ здесь означает инвариантное
            # нарушение; в -O режиме assert исчезает, поэтому явная проверка.
            raise RuntimeError(
                f"execute_jump failed after can_jump passed: "
                f"{result.error_reason}"
            )

        # синхронизация состояния (рынок/защита пересозданы load_system,
        # событие jump уже записано в elite_events.db методом core.jump)
        st.system_index = core.system_index
        st.fuel = core.fuel
        st.market = core.market
        st.defense = core.defense
        after = self._point()

        details = f"#{origin} {st.system_name(origin)} -> " \
                  f"#{target} {st.system_name(target)}"
        self.logger.log("jump", details, before, after)

        print(self.i18n.tr("cmd.jump.complete",
                           dist_ly=float(result.distance_ly),
                           cost=int(result.fuel_cost),
                           fuel=int(round(st.fuel))))
        print(self.i18n.tr("cmd.jump.arrived",
                           index=st.system_index, name=st.system["name"],
                           economy=st.system["economy_name"]))

        # пиратская встреча после прибытия
        if self._encounter():
            pass  # бой произошёл — результат выведен
        else:
            print(self.i18n.tr("cmd.combat.no_encounter"))

    def cmd_refuel(self, args: list[str]) -> None:
        """
        Заправка ВСЕГДА до полного бака — как в оригинале
        (src/code_6a00.asm:2465-2466: ldx #$46; stx PLAYER_FUEL).
        Цена = (MAX_FUEL - fuel) x 0.2 Cr (src/code_6a00.asm:2412-2416).
        Если передан аргумент (частичная заправка невозможна) — запрос
        подтверждения; при нехватке кредитов — отказ.
        """
        st = self.state
        fuel_now = int(round(st.fuel))
        room = FUEL_TANK_CAPACITY - fuel_now
        cost = room * FUEL_PRICE_PER_UNIT_CR

        if room <= 0:
            print(self.i18n.tr("cmd.refuel.full"))
            return

        if args:  # no partial refuel in the original — confirm full
            print(self.i18n.tr("cmd.refuel.confirm_prompt",
                               max_fuel=FUEL_TANK_CAPACITY, fuel_now=fuel_now,
                               price=FUEL_PRICE_PER_UNIT_CR, cost=cost))
            answer = self.editor.readline("> ").strip().lower()
            if not answer:  # EOF (Ctrl-D) / Ctrl-C / пустой ответ — отмена
                return
            if answer not in ("y", "yes", "д", "да"):
                print(self.i18n.tr("cmd.refuel.cancelled"))
                return

        if st.credits < cost:  # cannot spend more credits than available
            print(self.i18n.tr("cmd.refuel.no_credits", room=room, cost=cost,
                               credits=st.credits))
            return

        core = self._core_state()
        result = core.refuel()
        if not result:
            # предварительные проверки (room, credits) уже прошли — отказ
            # здесь означает инвариантное нарушение.
            raise RuntimeError(
                f"refuel failed after pre-check passed: {result.error_reason}")
        # синхронизация состояния (событие refuel уже записано в SQLite)
        st.credits = core.credits
        st.fuel = core.fuel
        print(self.i18n.tr("cmd.refuel.done", filled=room, cost=cost))

    def cmd_save(self, args: list[str]) -> None:
        """Сохранить GameState в JSON."""
        if len(args) != 1:
            print(self.i18n.tr("cmd.save.usage"))
            return
        st = self.state
        payload = {
            "galaxy": st.galaxy,
            "system_index": st.system_index,
            "fuel": st.fuel,
            "credits": round(st.credits, 2),
            "cargo": {
                COMMODITIES[i]: qty
                for i, qty in enumerate(st.cargo)
                if qty > 0
            },
        }
        path = Path(args[0])
        try:
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(self.i18n.tr("cmd.save.error", exc=str(exc)))
            return
        print(self.i18n.tr("cmd.save.done",
                           path=str(path), galaxy=st.galaxy,
                           index=st.system_index, name=st.system["name"],
                           credits=st.credits, fuel=st.fuel,
                           cargo=st.cargo_weight, hold=SHIP_HOLD))

    def cmd_load(self, args: list[str]) -> None:
        """Загрузить GameState из JSON (с валидацией полей)."""
        if len(args) != 1:
            print(self.i18n.tr("cmd.load.usage"))
            return
        path = Path(args[0])
        if not path.exists():
            print(self.i18n.tr("cmd.load.not_found", path=str(path)))
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(self.i18n.tr("cmd.load.read_error", exc=str(exc)))
            return
        if not isinstance(payload, dict):
            print(self.i18n.tr("cmd.load.invalid_json"))
            return

        try:
            galaxy = int(payload["galaxy"]) & 0x07
            system_index = int(payload["system_index"])
            if not 0 <= system_index < SYSTEMS_PER_GALAXY:
                raise ValueError(
                    f"system {system_index} does not exist (valid range "
                    f"0-{SYSTEMS_PER_GALAXY - 1})"
                )
            fuel = float(payload.get("fuel", 0.0))
            credits = float(payload.get("credits", 0.0))
            cargo: Cargo = [0] * len(COMMODITIES)
            raw_cargo = payload.get("cargo", {})
            if not isinstance(raw_cargo, dict):
                raise ValueError("cargo field must be a dict")
            for name, qty in raw_cargo.items():
                cargo[commodity_index(name)] = max(0, int(qty))
        except (KeyError, ValueError, TypeError) as exc:
            print(self.i18n.tr("cmd.load.invalid_data", exc=str(exc)))
            return

        self.state = GameState(
            galaxy=galaxy,
            system_index=system_index,
            fuel=fuel,
            credits=credits,
            cargo=cargo,
        )
        print(self.i18n.tr("cmd.load.done",
                           path=str(path), galaxy=galaxy, index=system_index,
                           name=self.state.system["name"], credits=credits,
                           fuel=fuel, cargo=self.state.cargo_weight,
                           hold=SHIP_HOLD))

    # ------------------------------------------------ analytics (routes)

    def cmd_route(self, args: list[str]) -> None:
        """Кратчайший маршрут до системы (BFS по графу, рёбра <= 7 св. лет)."""
        if len(args) != 1:
            print(self.i18n.tr("cmd.route.usage"))
            return
        try:
            target = int(args[0])
        except ValueError:
            print(self.i18n.tr("cmd.route.bad_index", value=args[0]))
            return
        st = self.state
        if not 0 <= target < SYSTEMS_PER_GALAXY:
            print(self.i18n.tr("cmd.route.out_of_range",
                               target=target, max=SYSTEMS_PER_GALAXY - 1))
            return
        rf = self._route_finder()
        legs = rf.find_route_with_fuel(
            st.system_index, target, int(round(st.fuel)))
        if legs is None:
            print(self.i18n.tr("cmd.route.unreachable", target=target))
            return
        hops = len(legs)
        fuel_total = sum(int(leg["fuel_cost"]) for leg in legs)
        refuel_total = round(
            sum(float(leg["refuel_cost"]) for leg in legs), 2)
        print(self.i18n.tr("cmd.route.header", target=target,
                           target_name=st.system_name(target), hops=hops,
                           fuel=fuel_total, refuel=refuel_total))
        prev_name = st.system["name"]
        for i, leg in enumerate(legs, start=1):
            print(self.i18n.tr("cmd.route.leg", hop=i,
                               from_name=prev_name,
                               to_name=leg["system_name"],
                               dist_ly=float(leg["distance_ly"]),
                               fuel=int(leg["fuel_cost"])))
            prev_name = leg["system_name"]
        if refuel_total > 0:
            print(self.i18n.tr("cmd.route.refuel_needed", refuel=refuel_total))
        else:
            print(self.i18n.tr("cmd.route.refuel_not_needed"))

    # ------------------------------------------------- analytics (profit)

    def _print_deals(self, deals: list[dict]) -> None:
        """Таблица сделок: Товар | Откуда | Куда | Прибыль/ед. | Прибыль
        итого | Топливо | Заправка | Чистая прибыль."""
        if not deals:
            print(self.i18n.tr("cmd.profit.no_deals"))
            return
        print(self.i18n.tr("cmd.profit.header"))
        # Table rows — numeric data (no key in elite_i18n.py).
        for d in deals:
            print(f"{d['item_name']:<15}{d['origin_name']:<10}{d['target_name']:<10}"
                  f"{d['profit_per_unit']:>10.2f} Cr"
                  f"{d['profit_total']:>12.2f} Cr"
                  f"{d['fuel_used']:>7} units"
                  f"{d['refuel_cost_total']:>8.2f} Cr"
                  f"{d['net_profit']:>8.2f} Cr")

    def cmd_profit(self, args: list[str]) -> None:
        """Без аргумента — топ-10 по всем товарам; с аргументом — все сделки
        по конкретному товару (радиус 1 прыжок)."""
        analyzer = ProfitAnalyzer(self._route_finder())
        core = self._core_state()
        if not args:
            self._print_deals(analyzer.find_best_deals_all_items(core, max_jumps=1))
            return
        item = " ".join(args)
        try:
            deals = analyzer.find_best_deals(core, item, max_jumps=1)
        except MarketError as exc:
            print(self.i18n.tr("cmd.profit.error", exc=str(exc)))
            return
        self._print_deals(deals)

    def cmd_profit_top(self, args: list[str]) -> None:
        """Топ-N сделок по всем товарам (по умолчанию 10)."""
        n = 10
        if args:
            try:
                n = int(args[0])
            except ValueError:
                print(self.i18n.tr("cmd.profit_top.bad_n", value=args[0]))
                return
            if n <= 0:
                print(self.i18n.tr("cmd.profit_top.negative"))
                return
        analyzer = ProfitAnalyzer(self._route_finder())
        core = self._core_state()
        self._print_deals(analyzer.find_best_deals_all_items(core, top_n=n))

    # ------------------------------------------------------------- combat

    def _encounter(self, action: str | None = None) -> bool:
        """Пиратская встреча: проверка, выбор, бой, синхронизация.

        action=None → интерактив после прыжка.
        action задан → напрямую (команда combat).
        Возвращает True, если бой произошёл.
        """
        st = self.state
        # event_logger передан в core: capture() и log_combat() выполнит
        # сам resolve_combat_action() (см. elite_core.GameState).
        core = self._core_state()

        if not core.check_pirate_attack():
            if action is not None:
                print(self.i18n.tr("cmd.combat.no_attack"))
            return False

        # атака!
        if action is None:
            print(self.i18n.tr("cmd.combat.encounter"))
            while True:
                raw = self.editor.readline(
                    self.i18n.tr("cmd.combat.prompt")
                ).strip().lower()
                if not raw:  # EOF (Ctrl-D) / Ctrl-C — бой по умолчанию
                    raw = "fight"
                if raw in ("fight", "escape", "surrender"):
                    action = raw
                    break
                print(self.i18n.tr("cmd.combat.invalid_action"))

        outcome = core.resolve_combat_action(action)

        # синхронизация состояния
        st.fuel = core.fuel
        st.credits = core.credits
        st.cargo = list(core.cargo)
        st.defense = core.defense

        # --- гибель ---
        if outcome.destroyed:
            print(self.i18n.tr("cmd.combat.destroyed"))
            # reset: новый корабль, стартовые условия
            self.state = GameState()
            print(self.i18n.tr("cmd.combat.restart"))
            return True

        # --- результат через i18n ---
        key = f"cmd.combat.{outcome.status}"
        if outcome.status == "escape_success":
            print(self.i18n.tr(key, fuel=outcome.fuel_used))
        elif outcome.status == "escape_no_fuel":
            print(self.i18n.tr(key, need=outcome.detail))
        else:
            print(self.i18n.tr(key))

        # OUCH
        if outcome.ouch_lost:
            print(self.i18n.tr("cmd.combat.ouch", item=outcome.ouch_lost))

        # статус защиты
        d = st.defense
        print(self.i18n.tr("cmd.status.defense",
                           fsh=d.forward_shield, ash=d.aft_shield,
                           energy=d.energy))

        # краткий статус после боя
        print(self.i18n.tr("cmd.status.fuel",
                           fuel=int(round(st.fuel)),
                           max_fuel=FUEL_TANK_CAPACITY,
                           fuel_ly=st.fuel / 10.0))
        print(self.i18n.tr("cmd.status.credits", credits=st.credits))
        print(self.i18n.tr("cmd.status.cargo",
                           cargo=st.cargo_weight, hold=SHIP_HOLD))
        return True

    def cmd_combat(self, args: list[str]) -> None:
        """Бой: combat <fight|escape|surrender>."""
        if len(args) != 1 or args[0].lower() not in ("fight", "escape", "surrender"):
            print(self.i18n.tr("cmd.help.combat"))
            return
        self._encounter(args[0].lower())

    def cmd_info(self) -> None:
        """Описание текущей планеты («goat soup») на локали интерфейса."""
        st = self.state
        desc = st.generate_description(lang=self.i18n.locale)
        if not desc:
            print(self.i18n.tr("cmd.info.empty"))
            return
        print(self.i18n.tr("cmd.info.title"))
        print(desc)

    # ------------------------------------------------------------- language

    def cmd_lang(self, args: list[str]) -> None:
        """Переключение языка интерфейса (en, ru, es)."""
        locales = self.i18n.available_locales()
        if not args:
            print(self.i18n.tr("cmd.lang.current",
                               name=self.i18n.locale_display_name(self.i18n.locale),
                               code=self.i18n.locale))
            print(self.i18n.tr("cmd.lang.available", list=", ".join(locales)))
            return
        lang = args[0].strip().lower()
        if lang not in locales:
            print(self.i18n.tr("cmd.lang.invalid", lang=lang,
                               list=", ".join(locales)))
            return
        self.i18n.set_locale(lang)
        print(self.i18n.tr("cmd.lang.switched",
                           name=self.i18n.locale_display_name(lang), code=lang))

    # ------------------------------------------------------------- help

    def cmd_help(self) -> None:
        """Список команд."""
        print(self.i18n.tr("cmd.help.title"))
        print(self.i18n.tr("cmd.help.status"))
        print(self.i18n.tr("cmd.help.market"))
        print(self.i18n.tr("cmd.help.near"))
        print(self.i18n.tr("cmd.help.buy"))
        print(self.i18n.tr("cmd.help.sell"))
        print(self.i18n.tr("cmd.help.jump"))
        print(self.i18n.tr("cmd.help.refuel"))
        print(self.i18n.tr("cmd.help.route"))
        print(self.i18n.tr("cmd.help.profit"))
        print(self.i18n.tr("cmd.help.profit_top"))
        print(self.i18n.tr("cmd.help.info"))
        print(self.i18n.tr("cmd.help.combat"))
        print(self.i18n.tr("cmd.help.save"))
        print(self.i18n.tr("cmd.help.load"))
        print(self.i18n.tr("cmd.help.lang"))
        print(self.i18n.tr("cmd.help.quit"))

    # ------------------------------------------------------------- loop

    def run_command(self, line: str) -> bool:
        """Выполнить одну команду. Возвращает True при выходе (quit)."""
        parts = line.strip().split()
        if not parts:
            return False
        command, args = parts[0].lower(), parts[1:]

        if command == "quit":
            return True

        handlers: dict[str, object] = {
            "status": self.cmd_status,
            "market": self.cmd_market,
            "near": self.cmd_near,
            "buy": lambda: self.cmd_buy(args),
            "sell": lambda: self.cmd_sell(args),
            "jump": lambda: self.cmd_jump(args),
            "refuel": lambda: self.cmd_refuel(args),
            "route": lambda: self.cmd_route(args),
            "profit": lambda: self.cmd_profit(args),
            "profit-top": lambda: self.cmd_profit_top(args),
            "combat": lambda: self.cmd_combat(args),
            "info": self.cmd_info,
            "save": lambda: self.cmd_save(args),
            "load": lambda: self.cmd_load(args),
            "lang": lambda: self.cmd_lang(args),
            "help": self.cmd_help,
        }
        handler = handlers.get(command)
        if handler is None:
            print(self.i18n.tr("error.unknown_command", command=command))
            return False
        try:
            handler()
        except (ValueError, MarketError) as exc:
            print(self.i18n.tr("error.generic", exc=str(exc)))
        return False

    def run(self) -> None:
        """Интерактивный цикл: ввод команд до quit/Ctrl-D/Ctrl-C."""
        print(self.i18n.tr("app.welcome"))
        while True:
            line = self.editor.readline("> ")
            if not line:
                # EOF (Ctrl-D в пустой строке) или Ctrl-C — эквивалент
                # прежнего except (EOFError, KeyboardInterrupt).
                print("\n" + self.i18n.tr("app.farewell"))
                break
            if self.run_command(line):
                print(self.i18n.tr("app.farewell"))
                break


def main() -> int:
    """Точка входа CLI-версии (console script `pyelite`).

    Запускает интерактивный цикл: ввод команд до quit / Ctrl-D / Ctrl-C.
    """
    GameLoop(GameState(galaxy=0, system_index=0)).run()
    return 0


if __name__ == "__main__":
    # Demo: start at TIBEDI (system #0, galaxy 0), trading cycle.
    #
    # Sequence: status, market, near, buy 5 Food, jump to nearest
    # system, refuel to full (0.2 Cr/unit), save, log row.
    # Tank 70 units = 7.0 ly (src/save_data.asm:160): jump to EDINSOIN
    # costs 16 units, refuel — 16 x 0.2 = 3.20 Cr.
    loop = GameLoop(GameState(galaxy=0, system_index=0))

    loop.run_command("status")
    loop.run_command("market")
    loop.run_command("near")
    loop.run_command("route 19")
    loop.run_command("profit-top 3")
    loop.run_command("buy Food 5")

    nearest = loop.nearest_systems()
    if nearest:
        loop.run_command(f"jump {nearest[0][0]}")

    loop.run_command("refuel")
    loop.run_command("save save_test.json")

    print(f"\nLast log row ({loop.logger.path}):")
    print(loop.logger.last_row())