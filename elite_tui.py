#!/usr/bin/env python3
"""
elite_tui.py — TUI-версия pyElite на Textual.

Ядро (elite_core) не трогается — TUI вызывает тот же API, что бот.
EventLogger передаётся в GameState (ядро логирует автоматически).
player_id=0 — человек.

Запуск:  python elite_tui.py [--lang en|ru|es]
        (по умолчанию язык интерфейса — ru; доступны en, ru, es)
Зависимости:  pip install textual

Иерархия экранов: DialogScreen (Esc/кнопки отмены) — база всех
модальных диалогов; TradeDialogScreen(DialogScreen) добавляет общее
для покупки/продажи (undo Ctrl+Z, шаги количества, предвыбор товара);
CombatScreen/GameOverScreen — «голые» ModalScreen, т.к. их клавиши и
кнопки возвращают результат, а не отменяют диалог.

Управление:
  b — купить товар        (диалог: выбрать строку, ввести кол-во, Enter)
  s — продать товар       (диалог: выбрать строку, ввести кол-во, Enter;
                          кнопка «Продать все» продаёт весь трюм по
                          ценам текущей системы)
  Двойной клик по товару в списке «РЫНОК» открывает диалог покупки
  с этим же товаром; в диалоге есть кнопка «Купить на все» (макс.
  доступное кол-во по кредитам подставляется в поле количества).
  j — прыжок в систему    (диалог: выбрать строку или клик)
  i — описание системы    (данные системы + «goat soup»)
  h — справка (клавиши и памятка игроку)
  r — заправка до полного
  w — ждать ход          (регенерация щитов +1)
  q — выход
  F5 — quick save, F9 — quick load (quicksave.elite)
  F2 — диалог сохранения, F3 — диалог загрузки (файлы .elite)
  F4 — журнал сделок сессии
  В диалогах: Esc — отмена, Ctrl+Z — отменить последнюю сделку,
  +/- / PgUp/PgDn — шаг количества, * — максимум; b/s помнят товар
  В бою: a — атака, f — побег, u — сдача

Лицензия: GPL v3.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from elite_core import (
    COMMODITIES,
    MARKET_TABLE,
    DeterministicRNG,
    EventLoggerProtocol,
    FUEL_TANK_CAPACITY,
    PRECIOUS_LIMIT,
    SHIP_DEFENSE_MAX,
    SHIP_HOLD,
    GameState,
    MarketEngine,
    MarketError,
)
from elite_analytics import EventLogger
from elite_i18n import I18n, commodity_display

try:
    from textual import events
    from textual.app import App, ComposeResult
    from textual.message import Message
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen
    from textual.widgets import Button, DataTable, Input, Label, RichLog, Static
    from rich.text import Text
except ImportError:
    print("Error: textual is not installed.\nRun: pip install textual", file=sys.stderr)
    sys.exit(1)

# ── Константы ───────────────────────────────────────────────────────

PLAYER_ID = 0  # человек
TUI_LANG = "ru"   # язык интерфейса TUI


def _commodity_ru(index: int) -> str:
    """Локализованное название товара для интерфейса (язык _I18N)."""
    return commodity_display(index, _I18N.locale) or COMMODITIES[index]


# Локализатор TUI (интерфейс русскоязычный).
_I18N = I18n(TUI_LANG)

# CombatResult.status -> ключ i18n (сообщения боя на языке интерфейса).
_COMBAT_STATUS_KEYS = {
    "fight_win": "cmd.combat.fight_win",
    "fight_lose": "cmd.combat.fight_lose",
    "escape_success": "cmd.combat.escape_success",
    "escape_fail": "cmd.combat.escape_fail",
    "escape_no_fuel": "cmd.combat.escape_no_fuel",
    "surrender": "cmd.combat.surrender",
    "destroyed": "cmd.combat.destroyed",
}


def _combat_message(outcome) -> str:
    """Локализованное сообщение боя по CombatResult.status."""
    key = _COMBAT_STATUS_KEYS.get(outcome.status)
    if key is None:
        return str(outcome.message)
    if outcome.status == "escape_success":
        return _I18N.tr(key, fuel=outcome.fuel_used)
    if outcome.status == "escape_no_fuel":
        return _I18N.tr(key, need=outcome.detail)
    return _I18N.tr(key)

GOV_NAMES = {
    0: "Anarchy", 1: "Feudal", 2: "Multi-Gov", 3: "Dictatorship",
    4: "Communist", 5: "Confederacy", 6: "Democracy", 7: "Corporate",
}

GOV_STYLE = {
    0: "red", 1: "red", 2: "yellow", 3: "yellow", 4: "yellow",
    5: "green", 6: "green", 7: "green",
}

GOV_MARK = {0: "!!!", 1: "!!", 2: "!", 3: "!", 4: "!", 5: "", 6: "", 7: ""}

# ── Цветовая палитра TUI (единые семантические стили) ───────────────
# Статусы и сообщения используют эти константы вместо «сырых» цветов:
STYLE_GOOD = "green"    # прибыль, дешевле базы, успешные операции
STYLE_WARN = "yellow"   # предупреждения, отменённые действия
STYLE_BAD = "red"       # убыток, опасность, дороже базы
STYLE_DIM = "dim"       # нейтрально, у базовых цен

# ── Сохранение/загрузка (.elite) ────────────────────────────────────

SAVE_VERSION = 1
SAVE_EXTENSION = ".elite"
QUICKSAVE_PATH = "quicksave.elite"


def save_game_to_path(state: GameState, path: str) -> None:
    """Сохранить GameState в JSON-файл (.elite).

    Сохраняется всё, что не восстанавливается детерминированно из ядра:
    позиция, топливо, кредиты, груз, щиты, состояние PRNG (продолжение
    случайной последовательности) и текущая доступность товаров рынка
    (она меняется покупками — commit_buy).
    """
    data = {
        "version": SAVE_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "galaxy": state.galaxy,
        "system_index": state.system_index,
        "fuel": state.fuel,
        "credits": state.credits,
        "cargo": list(state.cargo),
        "defense": {
            "forward_shield": state.defense.forward_shield,
            "aft_shield": state.defense.aft_shield,
            "energy": state.defense.energy,
        },
        "rng_state": list(state.rng.state),
        "market_available": list(state.market._available),  # noqa: SLF001
        # Журнал средних цен закупки (TUI-слой, см. record_buy). Необязателен:
        # сейвы без него (старые) загружаются без истории прибыли.
        "buy_ledger": {
            str(ci): [round(spent, 4), qty]
            for ci, (spent, qty) in getattr(state, "buy_ledger", {}).items()
        },
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def load_game_from_path(
    path: str,
    event_logger: EventLoggerProtocol | None = None,
) -> GameState:
    """Загрузить GameState из файла .elite.

    ValueError при битом/несовместимом файле. Рынок пересоздаётся через
    load_system() (детерминированно), затем восстанавливается текущая
    доступность товаров и прочее сохранённое состояние.

    event_logger — журнал событий, переподключается к восстановленному
    состоянию (иначе после загрузки события перестают логироваться).
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("save file is not a JSON object")
    if data.get("version") != SAVE_VERSION:
        raise ValueError(f"unsupported save version: {data.get('version')!r}")
    cargo = data.get("cargo")
    if not isinstance(cargo, list) or len(cargo) != 17:
        raise ValueError("save file: cargo must be a list of 17 values")

    st = GameState(
        galaxy=int(data["galaxy"]),
        system_index=int(data["system_index"]),
        fuel=float(data["fuel"]),
        credits=float(data["credits"]),
        cargo=[int(x) for x in cargo],
        event_logger=event_logger,
    )
    st.load_system()   # рынок + щиты по правилам стыковки, затем правим
    defense = data.get("defense", {})
    st.defense.forward_shield = int(
        defense.get("forward_shield", SHIP_DEFENSE_MAX))
    st.defense.aft_shield = int(
        defense.get("aft_shield", SHIP_DEFENSE_MAX))
    st.defense.energy = int(defense.get("energy", SHIP_DEFENSE_MAX))
    rng_state = data.get("rng_state")
    if isinstance(rng_state, list) and len(rng_state) == 4:
        st.rng = DeterministicRNG([int(x) for x in rng_state])
    market_available = data.get("market_available")
    if isinstance(market_available, list) and len(market_available) == 17:
        st.market._available = [int(x) for x in market_available]  # noqa: SLF001
    buy_ledger = data.get("buy_ledger")
    if isinstance(buy_ledger, dict):
        ledger: dict[int, tuple[float, int]] = {}
        for key, value in buy_ledger.items():
            try:
                ci = int(key)
                spent, qty = float(value[0]), int(value[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if 0 <= ci < len(COMMODITIES) and qty > 0 and spent > 0:
                ledger[ci] = (spent, qty)
        st.buy_ledger = ledger
    return st


def _sys_info(state: GameState, index: int) -> tuple[str, str, int]:
    """(economy_name, gov_name, gov_index) для системы index."""
    m = MarketEngine(state.generator, index, state.galaxy)
    gov = int(m.system["government"])
    return (
        str(m.system["economy_name"]),
        GOV_NAMES.get(gov, "?"),
        gov,
    )


def _buy_limits(state: GameState, ci: int) -> tuple[int, int, int, int]:
    """Лимиты покупки товара ci: (макс, наличие, по кредитам, по трюму)."""
    rows = state.market.get_market()
    price = float(rows[ci]["price_buy_cr"])
    avail = int(rows[ci]["available"])
    by_credits = int(state.credits / price) if price > 0 else 0
    if ci <= 12:
        by_space = SHIP_HOLD - state.cargo_weight
    else:
        by_space = PRECIOUS_LIMIT - state.cargo[ci]
    return max(0, min(avail, by_space, by_credits)), avail, by_credits, by_space


def _max_buy(state: GameState, ci: int) -> int:
    """Макс. количество товара ci для покупки."""
    return _buy_limits(state, ci)[0]


def _price_trend(state: GameState, ci: int) -> tuple[str, str]:
    """(метка, стиль) отклонения цены товара от базовой.

    Цены рынка детерминированы для системы (TT151), поэтому «трендом»
    служит отношение текущей цены к базовой цене товара из MARKET_TABLE:
    ▼ — дешевле базы (выгодно покупать), ▲ — дороже базы, ≈ — у базы.
    """
    base_cr: float = MARKET_TABLE[ci][0] * 0.4
    price: float = float(state.market.get_market()[ci]["price_buy_cr"])
    if price < base_cr * 0.98:
        return "▼", STYLE_GOOD
    if price > base_cr * 1.02:
        return "▲", STYLE_BAD
    return "≈", STYLE_DIM


def _price_trend_text(state: GameState, ci: int) -> str:
    """Локализованное описание отклонения цены от базы (для инфо-строк)."""
    mark, _style = _price_trend(state, ci)
    key = {
        "▼": "tui.trend.below",
        "▲": "tui.trend.above",
    }.get(mark, "tui.trend.base")
    return _I18N.tr(key)


def _price_deviation_pct(state: GameState, ci: int) -> int:
    """Отклонение текущей цены от базовой в процентах (округлённо)."""
    base_cr: float = MARKET_TABLE[ci][0] * 0.4
    if base_cr <= 0:
        return 0
    price: float = float(state.market.get_market()[ci]["price_buy_cr"])
    return round((price / base_cr - 1.0) * 100)


def _system_trend(state: GameState, index: int) -> tuple[str, str]:
    """(метка, стиль) «дешевизны» системы для торговли.

    Среднее отклонение цен основных товаров (индексы 0..12) от базовых:
    ▼ — в среднем дешевле базы (выгодно закупаться), ▲ — дороже (выгодно
    продавать сюда), ≈ — около базовых цен."""
    m = MarketEngine(state.generator, index, state.galaxy)
    total = 0.0
    n = 0
    for ci in range(13):
        base_cr: float = MARKET_TABLE[ci][0] * 0.4
        if base_cr <= 0:
            continue
        total += m.price_cr(ci) / base_cr
        n += 1
    ratio = total / n if n else 1.0
    if ratio < 0.98:
        return "▼", STYLE_GOOD
    if ratio > 1.02:
        return "▲", STYLE_BAD
    return "≈", STYLE_DIM


def _trade_snapshot(state: GameState) -> tuple:
    """Снимок состояния, изменяемого сделкой (для Undo, TUI-слой)."""
    return (
        state.credits,
        list(state.cargo),
        list(state.market._available),          # noqa: SLF001
        dict(getattr(state, "buy_ledger", {})),
    )


def _trade_restore(state: GameState, snapshot: tuple) -> None:
    """Восстановить состояние из снимка (отмена последней сделки)."""
    credits, cargo, available, ledger = snapshot
    state.credits = credits
    state.cargo[:] = cargo
    state.market._available = available         # noqa: SLF001
    state.buy_ledger = ledger   # type: ignore[attr-defined]


def record_buy(state: GameState, ci: int, qty: int, cost: float) -> None:
    """Учесть покупку в журнале средних цен закупки (TUI-слой).

    Журнал живёт как атрибут state.buy_ledger {ci: (потрачено, куплено)},
    чтобы ядро elite_core не менялось; сохраняется в .elite-файл."""
    ledger: dict[int, tuple[float, int]] = getattr(state, "buy_ledger", None) or {}
    spent, bought = ledger.get(ci, (0.0, 0))
    ledger[ci] = (spent + cost, bought + qty)
    state.buy_ledger = ledger   # type: ignore[attr-defined]


def record_sell(state: GameState, ci: int, qty: int) -> None:
    """Списать проданное из журнала средних цен закупки."""
    ledger: dict[int, tuple[float, int]] = getattr(state, "buy_ledger", None) or {}
    spent, bought = ledger.get(ci, (0.0, 0))
    if bought <= 0:
        return
    avg = spent / bought
    bought = max(0, bought - qty)
    spent = max(0.0, spent - avg * min(qty, bought + qty))
    if bought > 0 and spent > 0.0:
        ledger[ci] = (spent, bought)
    else:
        ledger.pop(ci, None)
    state.buy_ledger = ledger   # type: ignore[attr-defined]


def avg_buy_price(state: GameState, ci: int) -> float | None:
    """Средняя цена закупки товара (None — если товар не покупался)."""
    ledger = getattr(state, "buy_ledger", None)
    if not ledger:
        return None
    spent, bought = ledger.get(ci, (0.0, 0))
    if bought <= 0:
        return None
    return spent / bought


def _shields(state: GameState) -> tuple[int, int, int]:
    """(forward_shield, aft_shield, energy) безопасно."""
    d = state.defense
    return (
        int(getattr(d, "forward_shield", 0)),
        int(getattr(d, "aft_shield", 0)),
        int(getattr(d, "energy", 0)),
    )

# ── Таблица «РЫНОК» ─────────────────────────────────────────────────

class DoubleClickTable(DataTable):
    """DataTable, рассылающий RowActivated при двойном клике по строке.

    Обычный DataTable «глушит» клики (event.stop в _on_click), поэтому
    двойной клик перехватывается здесь; строка под курсором мыши берётся
    из meta-стиля так же, как в DataTable._on_click (row == -1 — заголовок).
    Обработчик: on_double_click_table_row_activated(event), event.row."""

    class RowActivated(Message):
        """Двойной клик по строке (row — индекс строки таблицы)."""

        def __init__(self, table: "DoubleClickTable", row: int) -> None:
            self.table = table
            self.row = row
            super().__init__()

        @property
        def control(self) -> "DoubleClickTable":
            return self.table

    async def _on_click(self, event: events.Click) -> None:
        if event.chain >= 2:
            row = event.style.meta.get("row")
            if isinstance(row, int) and row >= 0:
                self.post_message(self.RowActivated(self, row))
        await super()._on_click(event)

class MarketTable(DoubleClickTable):
    """Таблица «РЫНОК» главного окна (двойной клик — купить товар)."""

class SellTable(DoubleClickTable):
    """Таблица груза в диалоге продажи (двойной клик — продать всё)."""

class QtyInput(Input):
    """Поле количества в диалогах покупки/продажи.

    Клавиша '*' (максимум) не вставляется символом, а вызывает
    action_qty_max экрана-владельца: priority-binding для '*'
    не срабатывает, пока фокус в поле ввода."""

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "asterisk":
            event.stop()
            event.prevent_default()
            screen = self.screen
            if hasattr(screen, "action_qty_max"):
                screen.action_qty_max()
            return
        await super()._on_key(event)

# ── Базовые классы диалогов ─────────────────────────────────────────

def _safe_dismiss(screen: ModalScreen, result: object | None = None) -> None:
    """Закрыть экран, только если он всё ещё на вершине стека.

    Защита от двойного клика по кнопке закрытия и от дублированных
    событий уже закрытого диалога: Screen.dismiss безусловно вызывает
    pop_screen, а тот бросает ScreenStackError на пустом стеке."""
    if screen.app.screen is screen:
        screen.dismiss(result)

class DialogScreen(ModalScreen):
    """Базовый класс модальных диалогов.

    Общие черты: Esc отменяет диалог (dismiss(None)); кнопки с id,
    оканчивающимися на «-close»/«-cancel», тоже закрывают диалог без
    результата. Подклассы задают свой CSS, compose() и обработчики
    содержательных кнопок (вызывая super().on_button_pressed() для
    кнопок закрытия)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    DialogScreen { align: center middle; }
    .dialog-buttons {
        height: auto; layout: horizontal; padding: 1 0 0 0;
    }
    .dialog-buttons Button { margin: 0 1; }
    """

    def action_cancel(self) -> None:
        """Esc: закрыть диалог без результата."""
        _safe_dismiss(self)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id or ""
        if btn.endswith("-close") or btn.endswith("-cancel"):
            _safe_dismiss(self)

class TradeDialogScreen(DialogScreen):
    """Общая база диалогов покупки (BuyScreen) и продажи (SellScreen).

    Общее поведение: состояние игры и предвыбор товара (initial_ci),
    отмена последней сделки (Ctrl+Z, снимок состояния), шаги количества
    (+/- — 1, PgUp/PgDn — 5, '*' — максимум). Подклассы реализуют хуки:
    _setup_table, _reload, _update_info, _show_preview, _set_qty_max,
    _remember_selected и задают id виджетов TABLE_ID/QTY_ID/INFO_ID."""

    TABLE_ID = ""
    QTY_ID = ""
    INFO_ID = ""

    BINDINGS = [
        Binding("ctrl+z", "undo", "Undo"),
        Binding("plus", "qty_plus", "Qty+1", priority=True),
        Binding("+", "qty_plus", show=False),
        Binding("minus", "qty_minus", "Qty-1", priority=True),
        Binding("-", "qty_minus", show=False),
        Binding("pageup", "qty_plus5", "Qty+5", priority=True),
        Binding("pagedown", "qty_minus5", "Qty-5", priority=True),
        Binding("asterisk", "qty_max", "Qty max", priority=True),
        Binding("*", "qty_max", show=False),
    ]

    def __init__(self, state: GameState, initial_ci: int | None = None):
        super().__init__()
        self.state = state
        self.initial_ci = initial_ci
        self._indices: list[int] = []
        self._last_snapshot: tuple | None = None

    # ── Доступ к виджетам ──

    def _table(self) -> DataTable:
        return self.query_one(self.TABLE_ID, DataTable)

    def _qty_input(self) -> QtyInput:
        return self.query_one(self.QTY_ID, QtyInput)

    def _info_label(self) -> Label:
        return self.query_one(self.INFO_ID, Label)

    # ── Хуки подклассов ──

    def _setup_table(self) -> None:
        """Колонки таблицы (вызывается из on_mount до _reload())."""

    def _reload(self) -> None:
        """Перестроить таблицу, сохраняя позицию курсора."""
        t = self._table()
        try:
            cursor = t.cursor_coordinate.row
        except Exception:   # noqa: BLE001 — таблица ещё пуста
            cursor = 0
        t.clear()
        self._indices = []
        self._reload_rows()
        if 0 <= cursor < len(self._indices):
            t.move_cursor(row=cursor)
        self._after_reload()

    def _reload_rows(self) -> None:
        """Заполнить таблицу строками (вызывается из _reload)."""

    def _after_reload(self) -> None:
        """Действия после перестроения таблицы (вызывается из _reload)."""

    def _update_info(self) -> None:
        """Инфо-строка о выбранном товаре."""

    def _show_preview(self) -> None:
        """Live-предпросмотр сделки по мере ввода количества."""

    def _preview_qty(self) -> int | None:
        """Разобрать количество для предпросмотра.

        None — товар не выбран или значение некорректно (в этом случае
        показана _update_info)."""
        ci = self._selected_ci()
        if ci < 0:
            return None
        try:
            qty = int(self._qty_input().value.strip())
        except ValueError:
            self._update_info()
            return None
        if qty <= 0:
            self._update_info()
            return None
        return qty

    def _parse_qty(self) -> int | None:
        """Разобрать поле количества; при ошибке — сообщение в инфо-строку."""
        qty_str = self._qty_input().value.strip()
        if not qty_str:
            self._info_label().update(_I18N.tr("tui.qty.required"))
            return None
        try:
            qty = int(qty_str)
        except ValueError:
            self._info_label().update(_I18N.tr("tui.qty.invalid"))
            return None
        if qty <= 0:
            self._info_label().update(_I18N.tr("tui.qty.positive"))
            return None
        return qty

    def _check_qty(self, ci: int, qty: int) -> bool:
        """Дополнительная проверка количества (лимиты конкретной сделки)."""
        return True

    def _apply_trade(self, ci: int, qty: int) -> float:
        """Провести сделку, вернуть сумму; может бросить ValueError/MarketError."""
        raise NotImplementedError

    def _after_trade(self, ci: int, qty: int, amount: float) -> None:
        """Журнал и история после успешной сделки."""

    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-итог сделки по мере ввода количества."""
        if event.input.id == self.QTY_ID.lstrip("#"):
            self._show_preview()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._update_info()
        # Переносим фокус в поле ввода количества (клавиатурный сценарий)
        self._qty_input().focus()

    def _do_confirm(self) -> None:
        """Общее проведение сделки: валидация → снапшот → хуки подкласса."""
        ci = self._selected_ci()
        if ci < 0:
            self._info_label().update(_I18N.tr("tui.need_select"))
            return
        qty = self._parse_qty()
        if qty is None or not self._check_qty(ci, qty):
            return
        # Сделка выполняется здесь — диалог остаётся открытым
        # (удобно совершать несколько сделок подряд).
        self._last_snapshot = _trade_snapshot(self.state)
        try:
            amount = self._apply_trade(ci, qty)
        except (ValueError, MarketError) as exc:
            self._last_snapshot = None
            self._info_label().update(_I18N.tr("tui.trade.failed", exc=exc))
            return
        self._remember_selected(ci)
        self._after_trade(ci, qty, amount)
        self.state.defense.recharge(1)
        self.app._refresh()
        self._qty_input().value = ""
        self._reload()
        self._update_info()

    # ── Общее поведение ──

    def on_mount(self) -> None:
        self._setup_table()
        self._reload()
        if self.initial_ci is not None:
            self.select_commodity(self.initial_ci)

    def select_commodity(self, ci: int) -> None:
        """Предварительно выбрать товар ci и перенести фокус в поле кол-ва."""
        try:
            row = self._indices.index(ci)
        except ValueError:
            return
        self._table().move_cursor(row=row)
        self._remember_selected(ci)
        self._update_info()
        self._qty_input().focus()

    def _selected_ci(self) -> int:
        try:
            row = self._table().cursor_coordinate.row
        except AttributeError:
            return -1
        if 0 <= row < len(self._indices):
            return self._indices[row]
        return -1

    def _bump_qty(self, delta: int) -> None:
        """Изменить количество в поле ввода на delta (клавиши +, -, PgUp/PgDn)."""
        inp = self._qty_input()
        try:
            cur = int(inp.value.strip())
        except ValueError:
            cur = 0
        inp.value = str(max(0, cur + delta))
        self._show_preview()

    def action_qty_plus(self) -> None:
        self._bump_qty(1)

    def action_qty_minus(self) -> None:
        self._bump_qty(-1)

    def action_qty_plus5(self) -> None:
        self._bump_qty(5)

    def action_qty_minus5(self) -> None:
        self._bump_qty(-5)

    def action_qty_max(self) -> None:
        """'*': подставить максимальное количество."""
        self._set_qty_max()

    def action_undo(self) -> None:
        """Ctrl+Z: отменить последнюю сделку, сделанную в этом диалоге."""
        if self._last_snapshot is None:
            self._info_label().update(_I18N.tr("tui.undo.none"))
            return
        _trade_restore(self.state, self._last_snapshot)
        self._last_snapshot = None
        self.app._log(_I18N.tr("tui.undo.done"), style=STYLE_WARN)
        self.app._refresh()
        self._qty_input().value = ""
        self._reload()
        self._update_info()

# ── Диалог: покупка ─────────────────────────────────────────────────

class BuyScreen(TradeDialogScreen):
    """Выбрать товар в таблице → ввести количество → Enter.

    initial_ci — предварительно выбранный товар (двойной клик по строке
    в списке «РЫНОК» главного окна открывает диалог с этим товаром)."""

    TABLE_ID = "#buy-table"
    QTY_ID = "#buy-qty"
    INFO_ID = "#buy-info"

    CSS = """
    #buy-container {
        width: 72; max-width: 95%; height: auto; max-height: 85%;
        border: round $accent; padding: 1 2;
    }
    #buy-table { height: 12; }
    #buy-info { color: yellow; height: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="buy-container"):
            yield Label(_I18N.tr("tui.buy.title"))
            yield DataTable(id="buy-table", cursor_type="row")
            yield QtyInput(
                placeholder=_I18N.tr("tui.buy.qty_placeholder"), id="buy-qty")
            yield Label("", id="buy-info")
            with Horizontal(id="buy-buttons", classes="dialog-buttons"):
                yield Button(_I18N.tr("tui.btn.buy"), id="buy-ok", variant="success")
                yield Button(
                    _I18N.tr("tui.btn.buy_max"), id="buy-max", variant="warning")
                yield Button(
                    _I18N.tr("tui.btn.done"), id="buy-cancel", variant="error")

    def _setup_table(self) -> None:
        t = self._table()
        t.add_column(_I18N.tr("tui.col.commodity"), width=20)
        t.add_column(_I18N.tr("tui.col.price"), width=8)
        t.add_column(_I18N.tr("tui.col.avail"), width=7)
        t.add_column(_I18N.tr("tui.col.in_hold"), width=7)

    def _remember_selected(self, ci: int) -> None:
        self.app.last_buy_ci = ci

    def _reload_rows(self) -> None:
        rows = self.state.market.get_market()
        for i in range(len(COMMODITIES) - 1):
            price = float(rows[i]["price_buy_cr"])
            avail = int(rows[i]["available"])
            hold = self.state.cargo[i]
            self._table().add_row(
                _commodity_ru(i), f"{price:.1f}", str(avail),
                str(hold) if hold > 0 else "-",
            )
            self._indices.append(i)

    def _update_info(self) -> None:
        ci = self._selected_ci()
        if ci < 0:
            return
        mx, avail, by_credits, by_space = _buy_limits(self.state, ci)
        name = _commodity_ru(ci)
        price = float(self.state.market.get_market()[ci]["price_buy_cr"])
        # Что именно ограничивает максимум: кредиты, трюм или наличие
        if mx <= 0:
            if avail <= 0:
                limit = _I18N.tr("tui.buy.limit_none")
            elif by_credits <= 0:
                limit = _I18N.tr("tui.buy.limit_credits")
            else:
                limit = _I18N.tr("tui.buy.limit_space")
        elif by_credits == mx:
            limit = _I18N.tr("tui.buy.limit_credits")
        elif by_space == mx:
            limit = _I18N.tr("tui.buy.limit_space")
        else:
            limit = _I18N.tr("tui.buy.limit_stock")
        trend = _price_trend_text(self.state, ci)
        self._info_label().update(
            _I18N.tr(
                "tui.buy.info", name=name, price=price, trend=trend,
                mx=mx, limit=limit, credits=self.state.credits,
            )
        )

    def _show_preview(self) -> None:
        """Предпросмотр: сколько стоит введённое количество и что
        останется на счету."""
        qty = self._preview_qty()
        if qty is None:
            return
        ci = self._selected_ci()
        price = float(self.state.market.get_market()[ci]["price_buy_cr"])
        cost = price * qty
        self._info_label().update(
            _I18N.tr(
                "tui.buy.preview", name=_commodity_ru(ci), qty=qty,
                price=price, cost=cost, rest=self.state.credits - cost,
            )
        )

    def _check_qty(self, ci: int, qty: int) -> bool:
        if qty > _max_buy(self.state, ci):
            mx, _avail, _by_credits, _by_space = _buy_limits(self.state, ci)
            self._info_label().update(
                _I18N.tr("tui.buy.max_entered", mx=mx, qty=qty))
            return False
        return True

    def _apply_trade(self, ci: int, qty: int) -> float:
        return self.state.buy(COMMODITIES[ci], qty)

    def _after_trade(self, ci: int, qty: int, cost: float) -> None:
        record_buy(self.state, ci, qty, cost)
        self.app._log(
            _I18N.tr(
                "tui.buy.done", qty=qty, name=_commodity_ru(ci), cost=cost),
            style=STYLE_GOOD,
        )
        self.app._record_trade(_I18N.tr(
            "tui.trade.bought", qty=qty, name=_commodity_ru(ci), cost=cost))

    def _set_qty_max(self) -> None:
        """«Купить на все»: подставить макс. доступное кол-во единиц
        (по кредитам, наличию на рынке и месту в трюме)."""
        ci = self._selected_ci()
        if ci < 0:
            self._info_label().update(_I18N.tr("tui.need_select"))
            return
        mx, _avail, _by_credits, _by_space = _buy_limits(self.state, ci)
        if mx <= 0:
            self._info_label().update(
                _I18N.tr(
                    "tui.buy.unavailable", name=_commodity_ru(ci),
                    credits=self.state.credits,
                )
            )
            return
        self._qty_input().value = str(mx)
        self._update_info()
        self._qty_input().focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "buy-qty":
            self._do_confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "buy-ok":
            self._do_confirm()
        elif event.button.id == "buy-max":
            self._set_qty_max()
        else:
            super().on_button_pressed(event)

class SellScreen(TradeDialogScreen):
    """Выбрать груз из трюма → ввести количество → Enter."""

    TABLE_ID = "#sell-table"
    QTY_ID = "#sell-qty"
    INFO_ID = "#sell-info"

    CSS = """
    #sell-container {
        width: 72; max-width: 95%; height: auto; max-height: 85%;
        border: round $success; padding: 1 2;
    }
    #sell-table { height: 12; }
    #sell-info { color: yellow; height: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="sell-container"):
            yield Label(_I18N.tr("tui.sell.title"))
            yield SellTable(id="sell-table", cursor_type="row")
            yield QtyInput(
                placeholder=_I18N.tr("tui.sell.qty_placeholder"), id="sell-qty")
            yield Label("", id="sell-info")
            with Horizontal(id="sell-buttons", classes="dialog-buttons"):
                yield Button(_I18N.tr("tui.btn.sell"), id="sell-ok", variant="success")
                yield Button(
                    _I18N.tr("tui.btn.sell_all"), id="sell-all", variant="warning")
                yield Button(
                    _I18N.tr("tui.btn.done"), id="sell-cancel", variant="error")

    def _setup_table(self) -> None:
        t = self._table()
        t.add_column(_I18N.tr("tui.col.commodity"), width=20)
        t.add_column(_I18N.tr("tui.col.price"), width=8)
        t.add_column(_I18N.tr("tui.col.in_hold"), width=7)

    def _remember_selected(self, ci: int) -> None:
        self.app.last_sell_ci = ci

    def _reload_rows(self) -> None:
        self._sell_all_armed = False   # состав груза изменился
        rows = self.state.market.get_market()
        self._has_cargo = False
        for i in range(len(COMMODITIES) - 1):
            hold = self.state.cargo[i]
            if hold <= 0:
                continue
            self._has_cargo = True
            price = float(rows[i]["price_buy_cr"])
            self._table().add_row(_commodity_ru(i), f"{price:.1f}", str(hold))
            self._indices.append(i)

    def _after_reload(self) -> None:
        if not getattr(self, "_has_cargo", True):
            self._info_label().update(_I18N.tr("tui.sell.empty"))

    def _update_info(self) -> None:
        ci = self._selected_ci()
        if ci < 0:
            return
        hold = self.state.cargo[ci]
        price = float(self.state.market.get_market()[ci]["price_buy_cr"])
        avg = avg_buy_price(self.state, ci)
        if avg is not None:
            self.query_one("#sell-info", Label).update(
                _I18N.tr(
                    "tui.sell.info_avg", name=_commodity_ru(ci), price=price,
                    hold=hold, income=price * hold, avg=avg,
                    profit=price * hold - avg * hold,
                )
            )
        else:
            self.query_one("#sell-info", Label).update(
                _I18N.tr(
                    "tui.sell.info", name=_commodity_ru(ci), price=price,
                    hold=hold, income=price * hold,
                )
            )

    def _show_preview(self) -> None:
        """Предпросмотр: доход от введённого количества и прибыль
        относительно средней цены закупки."""
        qty = self._preview_qty()
        if qty is None:
            return
        ci = self._selected_ci()
        price = float(self.state.market.get_market()[ci]["price_buy_cr"])
        income = price * qty
        avg = avg_buy_price(self.state, ci)
        if avg is not None:
            self.query_one("#sell-info", Label).update(
                _I18N.tr(
                    "tui.sell.preview_profit", name=_commodity_ru(ci),
                    qty=qty, price=price, income=income,
                    profit=income - avg * qty,
                )
            )
        else:
            self.query_one("#sell-info", Label).update(
                _I18N.tr(
                    "tui.sell.preview", name=_commodity_ru(ci),
                    qty=qty, price=price, income=income,
                )
            )

    def _check_qty(self, ci: int, qty: int) -> bool:
        hold = self.state.cargo[ci]
        if qty > hold:
            self._info_label().update(
                _I18N.tr("tui.sell.only_hold", hold=hold, qty=qty))
            return False
        return True

    def _apply_trade(self, ci: int, qty: int) -> float:
        return self.state.sell(COMMODITIES[ci], qty)

    def _after_trade(self, ci: int, qty: int, income: float) -> None:
        avg = avg_buy_price(self.state, ci)
        record_sell(self.state, ci, qty)
        self.app._record_trade(_I18N.tr(
            "tui.trade.sold", qty=qty, name=_commodity_ru(ci), income=income))
        if avg is not None:
            profit = income - avg * qty
            self.app._log(
                _I18N.tr(
                    "tui.sell.done_profit", qty=qty, name=_commodity_ru(ci),
                    income=income, profit=profit,
                ),
                style=STYLE_GOOD if profit >= 0 else STYLE_BAD,
            )
        else:
            self.app._log(
                _I18N.tr(
                    "tui.sell.done", qty=qty, name=_commodity_ru(ci),
                    income=income,
                ),
                style=STYLE_GOOD,
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "sell-qty":
            self._do_confirm()

    def on_double_click_table_row_activated(
        self, event: "DoubleClickTable.RowActivated",
    ) -> None:
        """Двойной клик по грузу — подставить в поле количества
        весь груз этого типа."""
        row = event.row
        if not (0 <= row < len(self._indices)):
            return
        ci = self._indices[row]
        self._table().move_cursor(row=row)
        self._qty_input().value = str(self.state.cargo[ci])
        self._update_info()
        self._show_preview()

    def _sell_all(self) -> None:
        """«Продать все»: продать весь груз трюма безусловно по ценам
        текущей звёздной системы (с подтверждением суммы)."""
        if not self._sell_all_armed:
            # Первый клик: показать сводку и потребовать подтверждения
            positions = 0
            total_qty = 0
            total_value = 0.0
            rows = self.state.market.get_market()
            for ci in range(len(COMMODITIES) - 1):
                qty = self.state.cargo[ci]
                if qty <= 0:
                    continue
                positions += 1
                total_qty += qty
                total_value += float(rows[ci]["price_buy_cr"]) * qty
            if positions == 0:
                self.query_one("#sell-info", Label).update(
                    _I18N.tr("tui.sell.empty"))
                return
            self._sell_all_armed = True
            self.query_one("#sell-info", Label).update(
                _I18N.tr(
                    "tui.sell.all_confirm", positions=positions,
                    qty=total_qty, total=total_value,
                )
            )
            return
        self._sell_all_armed = False
        self._last_snapshot = _trade_snapshot(self.state)
        sold_any = False
        total = 0.0
        total_profit = 0.0
        has_ledger = False
        for ci in range(len(COMMODITIES) - 1):
            qty = self.state.cargo[ci]
            if qty <= 0:
                continue
            try:
                income = self.state.sell(COMMODITIES[ci], qty)
            except (ValueError, MarketError) as exc:
                self.query_one("#sell-info", Label).update(
                    _I18N.tr(
                        "tui.sell.failed", name=_commodity_ru(ci), exc=exc))
                return
            sold_any = True
            total += income
            avg = avg_buy_price(self.state, ci)
            record_sell(self.state, ci, qty)
            if avg is not None:
                has_ledger = True
                total_profit += income - avg * qty
            self.app._log(
                _I18N.tr(
                    "tui.sell.done", qty=qty, name=_commodity_ru(ci),
                    income=income,
                ),
                style=STYLE_GOOD,
            )
        if not sold_any:
            self.query_one("#sell-info", Label).update(
                _I18N.tr("tui.sell.empty"))
            return
        self.state.defense.recharge(1)
        if has_ledger:
            self.app._log(
                _I18N.tr(
                    "tui.sell.all_done_profit", total=total, profit=total_profit),
                style=STYLE_GOOD + " bold",
            )
        else:
            self.app._log(
                _I18N.tr("tui.sell.all_done", total=total),
                style=STYLE_GOOD + " bold",
            )
        self.query_one("#sell-info", Label).update(
            _I18N.tr(
                "tui.sell.all_done_info_profit" if has_ledger
                else "tui.sell.all_done_info",
                total=total, profit=total_profit,
            )
        )
        self.app._refresh()
        self.query_one("#sell-qty", Input).value = ""
        self._reload()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sell-ok":
            self._do_confirm()
        elif event.button.id == "sell-all":
            self._sell_all()
        else:
            super().on_button_pressed(event)

class JumpScreen(DialogScreen):
    """Выбрать систему назначения → клик или Enter."""

    CSS = """
    #jump-container {
        width: 80; max-width: 95%; height: auto; max-height: 85%;
        border: round $warning; padding: 1 2;
    }
    #jump_table { height: 14; }
    """

    def __init__(self, state: GameState):
        super().__init__()
        self.state = state
        self._indices: list[int] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="jump-container"):
            yield Label(_I18N.tr("tui.jump.title"))
            yield DataTable(id="jump_table", zebra_stripes=True, cursor_type="row")
            with Horizontal(id="jump-buttons", classes="dialog-buttons"):
                yield Button(_I18N.tr("tui.btn.cancel"), id="jump-cancel", variant="error")

    def on_mount(self) -> None:
        t = self.query_one("#jump_table", DataTable)
        t.add_column(_I18N.tr("tui.col.system"), width=12)
        t.add_column(_I18N.tr("tui.col.ly"), width=6)
        t.add_column(_I18N.tr("tui.col.fuel"), width=7)
        t.add_column(_I18N.tr("tui.col.economy"), width=12)
        t.add_column(_I18N.tr("tui.col.gov"), width=12)
        t.add_column(_I18N.tr("tui.col.risk"), width=4)

        self._indices = []

        # Материализуем список — вдруг near_systems() возвращает генератор
        systems = list(self.state.near_systems())

        for index, name, dist_units, fuel_cost in systems:
            dist_ly = dist_units / 10.0
            economy, gov_name, gov = _sys_info(self.state, index)
            mark = GOV_MARK.get(gov, "")
            style = GOV_STYLE.get(gov, "white")
            fuel_ok = int(round(self.state.fuel)) >= fuel_cost
            row_style = style if fuel_ok else "dim"

            t.add_row(
                Text(name, style=row_style),
                Text(f"{dist_ly:.1f}", style=row_style),
                Text(str(fuel_cost), style=row_style),
                Text(economy, style=row_style),
                Text(gov_name, style=row_style),
                Text(mark, style=row_style),
            )
            self._indices.append(index)

        if not systems:
            t.add_row(
                Text(_I18N.tr("tui.jump.empty"), style=STYLE_BAD),
                Text(""), Text(""), Text(""), Text(""), Text(""),
            )

        t.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        t = self.query_one("#jump_table", DataTable)
        try:
            row = t.cursor_coordinate.row
        except AttributeError:
            return
        if 0 <= row < len(self._indices):
            _safe_dismiss(self, self._indices[row])

class CombatScreen(ModalScreen):
    """Выбор боевого действия: атака / побег / сдача."""

    CSS = """
    CombatScreen { align: center middle; }
    #combat-container {
        width: 60; max-width: 95%; height: auto;
        border: round red; padding: 1 2;
    }
    #combat-title { color: red; text-style: bold; }
    #combat-info { padding: 1 0; }
    #combat-buttons { height: auto; layout: horizontal; padding: 1 0 0 0; }
    #combat-buttons Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("a", "attack", "Attack"),
        Binding("f", "flee", "Flee"),
        Binding("u", "surrender", "Surrender"),
        Binding("escape", "flee", "Flee"),
    ]

    def __init__(self, state: GameState):
        super().__init__()
        self.state = state

    def compose(self) -> ComposeResult:
        gov = int(self.state.system["government"])
        fsh, ash, eng = _shields(self.state)
        with Vertical(id="combat-container"):
            yield Label(_I18N.tr("tui.combat.title"), id="combat-title")
            yield Label(
                _I18N.tr(
                    "tui.combat.info",
                    name=self.state.system['name'],
                    gov=GOV_NAMES.get(gov, '?'),
                    fsh=fsh, ash=ash, eng=eng,
                    credits=self.state.credits,
                    cargo=self.state.cargo_weight, hold=SHIP_HOLD,
                ),
                id="combat-info",
            )
            with Horizontal(id="combat-buttons"):
                yield Button(
                    _I18N.tr("tui.btn.attack"), id="combat-attack", variant="error")
                yield Button(
                    _I18N.tr("tui.btn.flee"), id="combat-flee", variant="warning")
                yield Button(
                    _I18N.tr("tui.btn.surrender"),
                    id="combat-surrender", variant="success",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        if btn == "combat-attack":
            _safe_dismiss(self, "fight")
        elif btn == "combat-flee":
            _safe_dismiss(self, "flee")
        elif btn == "combat-surrender":
            _safe_dismiss(self, "surrender")

    def action_attack(self) -> None:
        _safe_dismiss(self, "fight")

    def action_flee(self) -> None:
        _safe_dismiss(self, "flee")

    def action_surrender(self) -> None:
        _safe_dismiss(self, "surrender")

# ── Диалог: конец игры ──────────────────────────────────────────────

class GameOverScreen(ModalScreen):
    """Новая игра или выход."""

    CSS = """
    GameOverScreen { align: center middle; }
    #gameover-container {
        width: 50; max-width: 95%; height: auto;
        border: round red; padding: 1 2;
    }
    #gameover-title { color: red; text-style: bold; }
    #gameover-buttons { height: auto; layout: horizontal; padding: 1 0 0 0; }
    #gameover-buttons Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("n", "new_game", "New Game"),
        Binding("q", "quit_game", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="gameover-container"):
            yield Label(_I18N.tr("tui.gameover.title"), id="gameover-title")
            yield Label(_I18N.tr("tui.gameover.text"))
            with Horizontal(id="gameover-buttons"):
                yield Button(
                    _I18N.tr("tui.btn.new_game"),
                    id="gameover-new", variant="success",
                )
                yield Button(
                    _I18N.tr("tui.btn.quit"), id="gameover-quit", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "gameover-new":
            _safe_dismiss(self, "new")
        elif event.button.id == "gameover-quit":
            _safe_dismiss(self, "quit")

    def action_new_game(self) -> None:
        _safe_dismiss(self, "new")

    def action_quit_game(self) -> None:
        _safe_dismiss(self, "quit")

# ── Диалог: описание системы ────────────────────────────────────────

class InfoScreen(DialogScreen):
    """Описание текущей системы: данные TT24 + «goat soup»."""

    CSS = """
    #info-container {
        width: 70; max-width: 95%; height: auto; max-height: 85%;
        border: round $accent; padding: 1 2;
    }
    #info-title { text-style: bold; }
    #info-text { padding: 1 0; }
    """

    def __init__(self, state: GameState):
        super().__init__()
        self.state = state

    def compose(self) -> ComposeResult:
        gov = int(self.state.system["government"])
        fsh, ash, eng = _shields(self.state)
        with Vertical(id="info-container"):
            yield Label(
                _I18N.tr(
                    "tui.info.title",
                    name=self.state.system['name'],
                    galaxy=self.state.galaxy + 1,
                ),
                id="info-title",
            )
            yield Label(
                _I18N.tr(
                    "tui.info.body",
                    economy=self.state.system['economy_name'],
                    gov=GOV_NAMES.get(gov, '?'),
                    tech=int(self.state.system['tech_level']),
                    pop=int(self.state.system['population']) / 10,
                    fsh=fsh, ash=ash, eng=eng,
                    description=self.state.generate_description(
                        lang=_I18N.locale),
                ),
                id="info-text",
            )
            with Horizontal(id="info-buttons", classes="dialog-buttons"):
                yield Button(
                    _I18N.tr("tui.btn.close"), id="info-close", variant="primary")

class FileDialog(DialogScreen):
    """Выбор файла сохранения (.elite) для записи или загрузки.

    mode="save" — ввод имени файла (Enter/кнопка «Сохранить»);
    mode="load" — выбор файла из таблицы (Enter заполняет поле ввода,
    повторный Enter/кнопка «Загрузить» — подтверждение).
    """

    CSS = """
    #file-container {
        width: 72; max-width: 95%; height: auto; max-height: 85%;
        border: round $primary; padding: 1 2;
    }
    #file-table { height: 10; }
    #file-info { color: yellow; height: 1; }
    """

    def __init__(self, mode: str = "save", directory: str = ".") -> None:
        super().__init__()
        self.mode = mode                # "save" | "load"
        self.directory = directory
        self._files: list[str] = []

    def compose(self) -> ComposeResult:
        title = (
            _I18N.tr("tui.file.save_title")
            if self.mode == "save"
            else _I18N.tr("tui.file.load_title")
        )
        ok_label = (
            _I18N.tr("tui.btn.save")
            if self.mode == "save"
            else _I18N.tr("tui.btn.load")
        )
        with Vertical(id="file-container"):
            yield Label(title)
            yield DataTable(id="file-table", cursor_type="row")
            yield Input(
                placeholder=_I18N.tr("tui.file.name_placeholder"),
                id="file-name",
            )
            yield Label("", id="file-info")
            with Horizontal(id="file-buttons", classes="dialog-buttons"):
                yield Button(ok_label, id="file-ok", variant="success")
                yield Button(
                    _I18N.tr("tui.btn.cancel"), id="file-cancel", variant="error")

    def on_mount(self) -> None:
        t = self.query_one("#file-table", DataTable)
        t.add_column(_I18N.tr("tui.col.file"), width=30)
        t.add_column(_I18N.tr("tui.col.size"), width=10)
        t.add_column(_I18N.tr("tui.col.modified"), width=19)
        try:
            names = sorted(
                (f for f in os.listdir(self.directory)
                 if f.endswith(SAVE_EXTENSION)),
                key=lambda f: os.path.getmtime(os.path.join(self.directory, f)),
                reverse=True,
            )
        except OSError:
            names = []
        for name in names:
            full = os.path.join(self.directory, name)
            try:
                size = os.path.getsize(full)
                mtime = datetime.fromtimestamp(
                    os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M:%S")
            except OSError:
                continue
            t.add_row(name, f"{size} B", mtime)
            self._files.append(name)
        self.query_one("#file-table", DataTable).focus()

    def _selected_file(self) -> str | None:
        t = self.query_one("#file-table", DataTable)
        try:
            row = t.cursor_coordinate.row
        except AttributeError:
            return None
        if 0 <= row < len(self._files):
            return self._files[row]
        return None

    def _full_path(self) -> str | None:
        name = self.query_one("#file-name", Input).value.strip()
        if not name:
            selected = self._selected_file()
            if selected is None:
                self.query_one("#file-info", Label).update(
                    _I18N.tr("tui.file.name_required"))
                return None
            name = selected
        # Валидация: только базовое имя файла — без путей и слэшей
        # (защита от path traversal вида "../../x.elite").
        if ("/" in name or "\\" in name or "\0" in name
                or name in (".", "..")):
            self.query_one("#file-info", Label).update(
                _I18N.tr("tui.file.name_invalid"))
            return None
        if not name.endswith(SAVE_EXTENSION):
            name += SAVE_EXTENSION
        return os.path.join(self.directory, name)

    def _confirm(self) -> None:
        path = self._full_path()
        if path is not None:
            _safe_dismiss(self, path)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        name = self._selected_file()
        if name is not None:
            name_input = self.query_one("#file-name", Input)
            name_input.value = name
            name_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "file-name":
            self._confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "file-ok":
            self._confirm()
        else:
            super().on_button_pressed(event)

class HelpScreen(DialogScreen):
    """Окно помощи: клавиши управления и краткая памятка игроку."""

    CSS = """
    #help-container {
        width: 84; max-width: 95%; height: auto; max-height: 90%;
        border: round $accent; padding: 1 2;
    }
    #help-title { text-style: bold; color: $accent; }
    /* Прокрутка: длинный текст не выталкивает кнопку за край экрана */
    #help-scroll {
        height: auto; max-height: 24; min-height: 5;
        padding: 1 0;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-container"):
            yield Label(_I18N.tr("tui.help.title"), id="help-title")
            with VerticalScroll(id="help-scroll"):
                yield Static(_I18N.tr("tui.help.text"), id="help-text")
            with Horizontal(id="help-buttons", classes="dialog-buttons"):
                yield Button(
                    _I18N.tr("tui.btn.close"), id="help-close", variant="primary")

class TradeLogScreen(DialogScreen):
    """F4: журнал сделок текущей сессии (в памяти, не сохраняется)."""

    CSS = """
    #tradelog-container {
        width: 80; max-width: 95%; height: auto; max-height: 85%;
        border: round $warning; padding: 1 2;
    }
    #tradelog-title { text-style: bold; color: $warning; }
    #tradelog-scroll {
        height: auto; max-height: 24; min-height: 3; padding: 1 0;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Close")]

    def __init__(self, trades: list[str]):
        super().__init__()
        self.trades = trades

    def compose(self) -> ComposeResult:
        with Vertical(id="tradelog-container"):
            yield Label(_I18N.tr("tui.tradelog.title"), id="tradelog-title")
            with VerticalScroll(id="tradelog-scroll"):
                if self.trades:
                    yield Static("\n".join(self.trades), id="tradelog-text")
                else:
                    yield Static(
                        _I18N.tr("tui.tradelog.empty"), id="tradelog-text")
            with Horizontal(id="tradelog-buttons", classes="dialog-buttons"):
                yield Button(
                    _I18N.tr("tui.btn.close"),
                    id="tradelog-close", variant="primary",
                )

class EliteTUI(App):
    """TUI для pyElite на Textual."""

    CSS = """
    Screen { layout: vertical; }

    #status-bar {
        height: auto; border: round $primary; padding: 0 1;
    }

    #middle { height: 1fr; layout: horizontal; }

    #market-panel {
        width: 1fr; border: round $accent; padding: 0 1;
    }
    #galaxy-panel {
        width: 1fr; border: round $warning; padding: 0 1;
    }

    #log-panel { height: 10; border: round $success; padding: 0 1; }

    #action-bar {
        height: auto; layout: horizontal; dock: bottom; padding: 0 1;
    }
    #action-bar Button { margin: 0 1; }

    DataTable { height: 1fr; }
    RichLog { height: 1fr; }

    /* На узких терминалах таблицы не должны сжиматься в пару строк */
    #market-table, #galaxy-table { min-height: 14; }
    """

    BINDINGS = [
        Binding("b", "buy", "Buy"),
        Binding("s", "sell", "Sell"),
        Binding("j", "jump", "Jump"),
        Binding("i", "info", "Info"),
        Binding("h", "help", "Help"),
        Binding("r", "refuel", "Refuel"),
        Binding("w", "wait", "Wait"),
        Binding("q", "quit", "Quit"),
        Binding("f2", "save_dialog", "Save", show=False),
        Binding("f3", "load_dialog", "Load", show=False),
        Binding("f4", "trade_log", "Trades", show=False),
        Binding("f5", "quick_save", "QuickSave", show=False),
        Binding("f9", "quick_load", "QuickLoad", show=False),
    ]

    def __init__(self, db_path: str = "elite_events.db"):
        super().__init__()
        self.db_path = db_path
        self.quick_save_path: str = QUICKSAVE_PATH
        self.saves_dir: str = "."   # каталог для диалогов F2/F3
        self.state: GameState | None = None
        self.logger: EventLogger | None = None
        # Товарный индекс каждой строки таблицы «РЫНОК» (без «товаров чужих»)
        self._market_indices: list[int] = []
        # Журнал сделок сессии (F4): короткие строки с таймстампом
        self.trade_history: list[str] = []
        # Последний выбранный товар в диалогах покупки/продажи (b/s)
        self.last_buy_ci: int | None = None
        self.last_sell_ci: int | None = None

    # ── Жизненный цикл ──

    def _new_game(self) -> None:
        """Начать новую игру с чистым состоянием."""
        if self.logger is not None:
            self.logger.new_session()   # новая партия в журнале событий
        self.state = GameState(
            galaxy=0, system_index=0, event_logger=self.logger,
        )
        self.state.load_system()
        self.state.fuel = float(FUEL_TANK_CAPACITY)
        self.state.credits = 100.0
        # Журнал средних цен закупки (TUI-слой, см. record_buy)
        self.state.buy_ledger = {}   # type: ignore[attr-defined]

    def compose(self) -> ComposeResult:
        yield Static(id="status-bar")
        with Horizontal(id="middle"):
            with Vertical(id="market-panel"):
                yield Label(_I18N.tr("tui.panel.market"))
                yield MarketTable(id="market-table")
            with Vertical(id="galaxy-panel"):
                yield Label(_I18N.tr("tui.panel.galaxy"))
                yield DataTable(id="galaxy-table")
        yield RichLog(id="log-panel")
        with Horizontal(id="action-bar"):
            yield Button(_I18N.tr("tui.btn.buy_key"), id="btn-buy")
            yield Button(_I18N.tr("tui.btn.sell_key"), id="btn-sell")
            yield Button(_I18N.tr("tui.btn.jump_key"), id="btn-jump")
            yield Button(_I18N.tr("tui.btn.refuel_key"), id="btn-refuel")
            yield Button(_I18N.tr("tui.btn.wait_key"), id="btn-wait")
            yield Button(_I18N.tr("tui.btn.help_key"), id="btn-help")
            yield Button(_I18N.tr("tui.btn.trades_key"), id="btn-trades")
            yield Button(_I18N.tr("tui.btn.quit_key"), id="btn-quit")

    def on_mount(self) -> None:
        self.logger = EventLogger(self.db_path, player_id=PLAYER_ID)
        self._new_game()
        self._log(_I18N.tr("tui.welcome"))
        self._log(
            _I18N.tr(
                "tui.start",
                name=self.state.system['name'],
                galaxy=self.state.galaxy + 1,
            )
        )
        self._log(_I18N.tr("tui.keys_hint"))
        self._refresh()

    # ── Отображение ──

    def _log(self, msg: str, style: str = "") -> None:
        log = self.query_one("#log-panel", RichLog)
        if style:
            log.write(Text(msg, style=style))
        else:
            log.write(msg)

    def _refresh(self) -> None:
        """Обновить все панели из текущего состояния."""
        self._refresh_status()
        self._refresh_market()
        self._refresh_galaxy()

    def _refresh_status(self) -> None:
        st = self.state
        gov = int(st.system["government"])
        fsh, ash, eng = _shields(st)
        gov_name = GOV_NAMES.get(gov, "?")
        gov_style = GOV_STYLE.get(gov, "white")
        mark = GOV_MARK.get(gov, "")
        # Опасные системы помечены: цвет правительства + метка пиратов
        danger = (
            f" [bold red]{mark} {_I18N.tr('tui.status.pirates')}[/]"
            if mark else ""
        )
        line = (
            f" {st.system['name']} (G{st.galaxy + 1})  |  "
            f"{st.system['economy_name']}  |  "
            f"[{gov_style}]{gov_name}[/]{danger}  |  "
            + _I18N.tr(
                "tui.status.bar",
                credits=st.credits, fuel=int(round(st.fuel)),
                max=FUEL_TANK_CAPACITY,
                cargo=st.cargo_weight, hold=SHIP_HOLD,
                fsh=fsh, ash=ash, eng=eng,
            )
        )
        self.query_one("#status-bar", Static).update(line)

    def _refresh_market(self) -> None:
        t = self.query_one("#market-table", MarketTable)
        t.clear(columns=True)
        t.add_column(_I18N.tr("tui.col.commodity"), width=20)
        t.add_column(_I18N.tr("tui.col.price"), width=8)
        t.add_column(_I18N.tr("tui.market.col_basis"), width=8)
        t.add_column(_I18N.tr("tui.col.avail"), width=7)
        t.add_column(_I18N.tr("tui.col.hold"), width=6)
        rows = self.state.market.get_market()
        self._market_indices = []
        for i, name in enumerate(COMMODITIES):
            if i == 16:
                continue
            price = float(rows[i]["price_buy_cr"])
            avail = int(rows[i]["available"])
            hold = self.state.cargo[i]
            color = "green" if hold > 0 else ""
            mark, mark_style = _price_trend(self.state, i)
            pct = _price_deviation_pct(self.state, i)
            t.add_row(
                Text(_commodity_ru(i), style=color),
                Text(f"{price:.1f}", style=color),
                Text(f"{mark}{pct:+d}%", style=mark_style),
                Text(str(avail), style=color),
                Text(str(hold) if hold > 0 else "-", style=color),
            )
            self._market_indices.append(i)

    def _refresh_galaxy(self) -> None:
        t = self.query_one("#galaxy-table", DataTable)
        t.clear(columns=True)
        t.add_column(_I18N.tr("tui.col.system"), width=12)
        t.add_column(_I18N.tr("tui.col.ly"), width=6)
        t.add_column(_I18N.tr("tui.col.fuel"), width=7)
        t.add_column(_I18N.tr("tui.col.economy"), width=12)
        t.add_column(_I18N.tr("tui.col.gov"), width=12)
        t.add_column(_I18N.tr("tui.col.risk"), width=4)
        t.add_column(_I18N.tr("tui.map.col_trend"), width=5)
        for index, name, dist_units, fuel_cost in self.state.near_systems():
            dist_ly = dist_units / 10.0
            economy, gov_name, gov = _sys_info(self.state, index)
            mark = GOV_MARK.get(gov, "")
            style = GOV_STYLE.get(gov, "white")
            fuel_ok = int(round(self.state.fuel)) >= fuel_cost
            row_style = style if fuel_ok else "dim"
            trend_mark, trend_style = _system_trend(self.state, index)
            t.add_row(
                Text(name, style=row_style),
                Text(f"{dist_ly:.1f}", style=row_style),
                Text(str(fuel_cost), style=row_style),
                Text(economy, style=row_style),
                Text(gov_name, style=row_style),
                Text(mark, style=row_style),
                Text(trend_mark, style=trend_style),
            )

    # ── Действия ──

    def action_buy(self, initial_ci: int | None = None) -> None:
        if initial_ci is None:
            initial_ci = self.last_buy_ci
        self.push_screen(BuyScreen(self.state, initial_ci), self._on_buy_done)

    def action_sell(self, initial_ci: int | None = None) -> None:
        if initial_ci is None:
            initial_ci = self.last_sell_ci
        self.push_screen(SellScreen(self.state, initial_ci), self._on_sell_done)

    def action_jump(self) -> None:
        self.push_screen(JumpScreen(self.state), self._on_jump_done)

    def action_info(self) -> None:
        self.push_screen(InfoScreen(self.state))

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_refuel(self) -> None:
        if int(round(self.state.fuel)) >= FUEL_TANK_CAPACITY:
            self._log(_I18N.tr("tui.refuel.full"), style=STYLE_WARN)
            return
        result = self.state.refuel()
        if not result:
            self._log(
                _I18N.tr("tui.refuel.failed", reason=result.error_reason),
                style=STYLE_BAD,
            )
            return
        self._log(
            _I18N.tr("tui.refuel.done", cost=result.cost), style="cyan")
        self.state.defense.recharge(1)
        self._refresh()

    def action_wait(self) -> None:
        """Ход ожидания: щиты/энергия +1 (GameState.wait_turn).

        Как в оригинале, рынок и опасность привязаны к прыжкам:
        ожидание не обновляет рынок и не перезапускает проверки атак.
        Событие хода пишется в журнал (action="wait")."""
        self.state.wait_turn()
        self._log(_I18N.tr("tui.wait.done"), style=STYLE_DIM)
        self._refresh()

    # ── Сохранение/загрузка ──

    def action_quick_save(self) -> None:
        """F5: быстрое сохранение в фиксированный файл (как в FPS)."""
        if self.state is None:
            return
        try:
            save_game_to_path(self.state, self.quick_save_path)
        except OSError as exc:
            self._log(
                _I18N.tr("tui.quicksave.failed", exc=exc), style=STYLE_BAD)
            return
        self._log(
            _I18N.tr("tui.quicksave.done", path=self.quick_save_path),
            style=STYLE_GOOD,
        )

    def action_quick_load(self) -> None:
        """F9: быстрая загрузка из фиксированного файла."""
        self._load_from_path(self.quick_save_path)

    def action_save_dialog(self) -> None:
        """F2: диалог сохранения с выбором имени файла (.elite)."""
        self.push_screen(
            FileDialog(mode="save", directory=self.saves_dir),
            self._on_save_done,
        )

    def action_load_dialog(self) -> None:
        """F3: диалог загрузки со списком файлов (.elite)."""
        self.push_screen(
            FileDialog(mode="load", directory=self.saves_dir),
            self._on_load_done,
        )

    def _record_trade(self, text: str) -> None:
        """Добавить запись в журнал сделок сессии (F4)."""
        stamp = datetime.now().strftime("%H:%M:%S")
        self.trade_history.append(f"{stamp} {text}")

    def action_trade_log(self) -> None:
        """F4: журнал сделок текущей сессии."""
        self.push_screen(TradeLogScreen(list(self.trade_history)))

    def _on_save_done(self, result) -> None:
        if result is None or self.state is None:
            return
        try:
            save_game_to_path(self.state, result)
        except OSError as exc:
            self._log(
                _I18N.tr("tui.save.failed", exc=exc), style=STYLE_BAD)
            return
        self._log(_I18N.tr("tui.save.done", path=result), style=STYLE_GOOD)

    def _on_load_done(self, result) -> None:
        if result is None:
            return
        self._load_from_path(result)

    def _load_from_path(self, path: str) -> None:
        if not os.path.exists(path):
            self._log(
                _I18N.tr("tui.load.not_found", path=path), style=STYLE_WARN)
            return
        try:
            self.state = load_game_from_path(path, event_logger=self.logger)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._log(
                _I18N.tr("tui.load.failed", exc=exc), style=STYLE_BAD)
            return
        self._log(
            _I18N.tr(
                "tui.load.done", path=path,
                name=self.state.system['name'], credits=self.state.credits,
            ),
            style=STYLE_GOOD,
        )
        self._refresh()

    def close_logger(self) -> None:
        """Закрыть журнал событий (идемпотентно)."""
        if self.logger is not None:
            self.logger.close()
            self.logger = None

    def action_quit(self) -> None:
        self.close_logger()
        self.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        if btn == "btn-buy":
            self.action_buy()
        elif btn == "btn-sell":
            self.action_sell()
        elif btn == "btn-jump":
            self.action_jump()
        elif btn == "btn-refuel":
            self.action_refuel()
        elif btn == "btn-wait":
            self.action_wait()
        elif btn == "btn-help":
            self.action_help()
        elif btn == "btn-trades":
            self.action_trade_log()
        elif btn == "btn-quit":
            self.action_quit()

    def on_double_click_table_row_activated(
        self, event: "DoubleClickTable.RowActivated",
    ) -> None:
        """Двойной клик по товару в списке «РЫНОК» → диалог покупки
        этого же товара (события других таблиц игнорируются)."""
        if event.table.id != "market-table":
            return
        row = event.row
        if 0 <= row < len(self._market_indices):
            self.action_buy(self._market_indices[row])

    # ── Колбэки диалогов ──

    def _on_buy_done(self, result) -> None:
        """Закрытие диалога покупки (покупки выполняются внутри диалога,
        чтобы можно было купить несколько товаров подряд)."""
        self._refresh()

    def _on_sell_done(self, result) -> None:
        """Закрытие диалога продажи (продажи выполняются внутри диалога)."""
        self._refresh()

    def _on_jump_done(self, result) -> None:
        if result is None:
            return
        target = result
        old_name = self.state.system["name"]
        jump_result = self.state.jump(target)
        if not jump_result:
            self._log(
                _I18N.tr("tui.jump.failed", reason=jump_result.error_reason),
                style=STYLE_BAD,
            )
            return
        new_name = self.state.system["name"]
        self._log(
            _I18N.tr(
                "tui.jump.done", old=old_name, new=new_name,
                dist=jump_result.distance_ly, cost=jump_result.fuel_cost,
            ),
            style="cyan",
        )
        self._refresh()
        # Проверка пиратской атаки после прыжка
        if self.state.check_pirate_attack():
            self._log(
                _I18N.tr("tui.notify.pirates"), style=STYLE_BAD + " bold")
            self.notify(
                _I18N.tr("tui.notify.pirates"),
                severity="error", timeout=10,
            )
            self.push_screen(
                CombatScreen(self.state), self._on_combat_done,
            )

    def _on_combat_done(self, result) -> None:
        if result is None:
            return
        action = result
        core_action = "escape" if action == "flee" else action
        outcome = self.state.resolve_combat_action(core_action)
        self._log(
            _I18N.tr(
                "tui.combat.log", action=action,
                message=_combat_message(outcome),
            ),
            style=STYLE_WARN,
        )
        if outcome.destroyed:
            self._log(
                _I18N.tr("tui.gameover.log"), style=STYLE_BAD + " bold")
            self.notify(
                _I18N.tr("tui.notify.destroyed"),
                severity="error", timeout=10,
            )
            self.push_screen(GameOverScreen(), self._on_game_over)
        else:
            self._refresh()

    def _on_game_over(self, result) -> None:
        if result == "new":
            self._new_game()
            self._log(_I18N.tr("tui.new_game"), style="cyan")
            self._refresh()
        elif result == "quit":
            self.action_quit()

# ── Точка входа ─────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="elite_tui",
        description="pyElite — TUI-версия (Textual).",
    )
    parser.add_argument(
        "-l", "--lang",
        default=TUI_LANG,
        metavar="CODE",
        choices=("en", "ru", "es"),
        help="язык интерфейса: en, ru, es (по умолчанию: %(default)s)",
    )
    args = parser.parse_args()
    _I18N.set_locale(args.lang)
    app = EliteTUI()
    try:
        app.run()
    finally:
        # Закрываем журнал даже при аварийном выходе (Ctrl+C и т.п.).
        app.close_logger()
    return 0


if __name__ == "__main__":
    sys.exit(main())
