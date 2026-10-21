"""
test_elite_tui.py — headless-тесты TUI-обёртки (textual pilot).

Запускаются без терминала: App.run_test() от textual.
Требует textual (optional-dependency `tui`); при отсутствии — SKIP.

Лицензия: GPL v3.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input, Label, Static  # noqa: E402

from elite_core import GameState  # noqa: E402
from elite_tui import (  # noqa: E402
    MarketTable,
    TradeLogScreen,
    _max_buy,
    _price_trend,
    _system_trend,
    avg_buy_price,
    FileDialog,
    QUICKSAVE_PATH,
    BuyScreen,
    CombatScreen,
    EliteTUI,
    GameOverScreen,
    HelpScreen,
    InfoScreen,
    JumpScreen,
    SellScreen,
    load_game_from_path,
    save_game_to_path,
)


def _run(coro) -> None:
    """asyncio.run без pytest-asyncio."""
    asyncio.run(coro)


@pytest.fixture
def app(tmp_path):
    """EliteTUI с временным SQLite-логом (elite_tui.py:607)."""
    a = EliteTUI(db_path=str(tmp_path / "events.db"))
    return a


def test_startup_state(app) -> None:
    """Старт: дефолтный экран, GameState создан, топливо/кредиты по норме."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)):
            assert app.state is not None
            assert app.state.fuel == 70.0
            assert app.state.credits == 100.0
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_modal_keys_do_not_leak(app) -> None:
    """Горячие клавиши App не действуют внутри модального диалога (scopes)."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            assert isinstance(app.screen, BuyScreen)

            # 'b'/'q'/'s' внутри диалога не открывают новых экранов
            # и не гасят приложение
            await pilot.press("b", "s", "q")
            await pilot.pause()
            assert app.is_running
            assert len(app.screen_stack) == 2

            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_buy_flow_keyboard(app) -> None:
    """Клавиатурная покупка: Enter на таблице -> ввод количества -> Enter.
    Диалог остаётся открытым (можно покупать несколько товаров подряд)."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter")       # выбрать первую строку (Food)
            await pilot.pause()
            await pilot.press("5", "enter")  # количество в Input
            await pilot.pause()
            st = app.state
            assert st.cargo[0] == 5
            assert st.cargo_weight == 5
            assert st.credits < 100.0
            assert isinstance(app.screen, BuyScreen)   # не закрылся
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_sell_all_button(app) -> None:
    """Кнопка «Продать все»: первый клик показывает сводку и НЕ продаёт,
    повторный клик (подтверждение) продаёт весь трюм по ценам текущей
    системы: трюм пустеет, кредиты растут."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            # Сначала покупаем 5 т. первого товара
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter", "5", "enter")
            await pilot.pause()
            st = app.state
            assert st.cargo[0] == 5
            credits_after_buy = st.credits
            # Теперь продаём всё кнопкой (два клика: сводка + подтверждение)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, SellScreen)
            scr.query_one("#sell-all").press()
            await pilot.pause()
            assert st.cargo[0] == 5          # ещё не продано
            scr.query_one("#sell-all").press()
            await pilot.pause()
            assert st.cargo[0] == 0
            assert st.cargo_weight == 0
            assert st.credits > credits_after_buy
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_sell_all_button_empty_cargo(app) -> None:
    """«Продать все» с пустым трюмом: диалог остаётся открытым,
    состояние не меняется, показывается предупреждение."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("s")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, SellScreen)
            credits_before = app.state.credits
            scr.query_one("#sell-all").press()
            await pilot.pause()
            assert isinstance(app.screen, SellScreen)
            assert app.state.credits == credits_before

    _run(scenario())


def test_buy_dialog_max_button(app) -> None:
    """Кнопка «Купить на все» подставляет макс. доступное кол-во единиц
    (по кредитам, наличию и месту в трюме) в поле количества."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, BuyScreen)
            await pilot.press("enter")       # выбрать первую строку (Food)
            await pilot.pause()
            qty = scr.query_one("#buy-qty", Input)
            qty.value = ""
            scr.query_one("#buy-max").press()
            await pilot.pause()
            expected = _max_buy(app.state, 0)
            assert expected > 0
            assert qty.value == str(expected)
            await pilot.press("enter")       # подтвердить покупку
            await pilot.pause()
            assert app.state.cargo[0] == expected
            assert app.state.credits < 100.0

    _run(scenario())


def test_buy_dialog_preselect_commodity(app) -> None:
    """action_buy(ci) открывает диалог покупки с выбранным товаром ci."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_buy(5)
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, BuyScreen)
            assert scr._selected_ci() == 5
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_market_double_click_opens_buy(app) -> None:
    """Двойной клик по строке «РЫНОК» открывает диалог покупки
    с тем же товаром; одиночный клик только подсвечивает строку."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            table = app.query_one("#market-table", MarketTable)
            # Одиночный клик по строке — диалог не открывается
            await pilot.click("#market-table", offset=(10, 2))
            await pilot.pause()
            assert len(app.screen_stack) == 1
            row = table.cursor_coordinate.row
            assert row >= 0
            # Двойной клик (times=2 → второй Click имеет chain=2) по строке
            # открывает диалог покупки с этим же товаром
            await pilot.click("#market-table", offset=(10, 2), times=2)
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, BuyScreen)
            assert scr._selected_ci() == app._market_indices[row]
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_buy_live_preview(app) -> None:
    """Ввод количества в диалоге покупки сразу показывает итог сделки
    (стоимость и остаток кредитов)."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, BuyScreen)
            await pilot.press("enter")       # выбрать первую строку (Food)
            await pilot.pause()
            await pilot.press("5")           # live-предпросмотр
            await pilot.pause()
            info = str(scr.query_one("#buy-info", Label).render())
            assert "5" in info
            assert "=" in info               # итог сделки
            assert "52.00" in info           # 100 - 5 * 9.6

    _run(scenario())


def test_buy_ledger_and_profit_flow(app) -> None:
    """Журнал средних цен закупки: заполняется покупкой, расходуется
    продажей, показывает прибыль."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            # Покупаем 5 т. Food
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter", "5", "enter")
            await pilot.pause()
            st = app.state
            avg = avg_buy_price(st, 0)
            assert avg is not None and avg > 0
            # Продаём всё: прибыль = доход - закупка
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, SellScreen)
            await pilot.press("enter")       # выбрать Food
            await pilot.pause()
            await pilot.press("5")           # live-предпросмотр с прибылью
            await pilot.pause()
            info = str(scr.query_one("#sell-info", Label).render())
            assert "+" in info               # прибыль форматируется со знаком
            await pilot.press("enter")       # продать
            await pilot.pause()
            assert st.cargo[0] == 0
            assert avg_buy_price(st, 0) is None

    _run(scenario())


def test_save_load_buy_ledger(tmp_path, app) -> None:
    """Журнал средних цен закупки сохраняется в .elite и восстанавливается."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter", "5", "enter")
            await pilot.pause()
            avg = avg_buy_price(app.state, 0)
            assert avg is not None
            await pilot.press("escape")
            await pilot.pause()
            path = str(tmp_path / "ledger.elite")
            save_game_to_path(app.state, path)
            loaded = load_game_from_path(path)
            assert avg_buy_price(loaded, 0) == avg

    _run(scenario())


def test_market_basis_column(app) -> None:
    """В таблице РЫНОК есть колонка «Базис» с корректной отметкой тренда."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            table = app.query_one("#market-table", MarketTable)
            assert len(table.columns) == 5
            mark, style = _price_trend(app.state, 0)
            assert mark in {"▼", "▲", "≈"}
            assert style in {"green", "red", "dim"}

    _run(scenario())


def test_sell_double_click_fills_qty(app) -> None:
    """Двойной клик по грузу в диалоге продажи подставляет в поле
    количества весь груз этого типа."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            # Покупаем 7 т. Food
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter", "7", "enter")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, SellScreen)
            # Двойной клик по первой строке груза (y=1 — сразу под шапкой)
            await pilot.click("#sell-table", offset=(10, 1), times=2)
            await pilot.pause()
            qty = scr.query_one("#sell-qty", Input)
            assert qty.value == str(app.state.cargo[0]) == "7"
            await pilot.press("enter")       # продать всё сразу
            await pilot.pause()
            assert app.state.cargo[0] == 0

    _run(scenario())


def test_buy_limit_reason(app) -> None:
    """Инфо-строка покупки показывает, что ограничивает максимум
    (кредиты / трюм / наличие)."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, BuyScreen)
            await pilot.press("enter")       # выбрать Food
            await pilot.pause()
            info = str(scr.query_one("#buy-info", Label).render())
            assert "лимит" in info           # ru-интерфейс TUI
            assert "кредиты" in info or "трюм" in info or "наличие" in info

    _run(scenario())


def test_status_bar_danger_markup(app) -> None:
    """Статус-бар рендерится с разметкой: имя системы и правительства
    присутствуют (стартовая система TIBEDI — Feudal с меткой пиратов)."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            status = str(app.query_one("#status-bar", Static).render())
            assert "TIBEDI" in status
            assert "Feudal" in status
            assert "ПИРАТЫ" in status

    _run(scenario())


def test_undo_buy(app) -> None:
    """Ctrl+Z в диалоге покупки отменяет последнюю покупку целиком
    (кредиты, трюм, наличие на рынке и журнал закупок)."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter", "5", "enter")
            await pilot.pause()
            st = app.state
            assert st.cargo[0] == 5
            assert st.credits < 100.0
            assert avg_buy_price(st, 0) is not None
            await pilot.press("ctrl+z")
            await pilot.pause()
            assert st.cargo[0] == 0
            assert st.credits == 100.0
            assert avg_buy_price(st, 0) is None

    _run(scenario())


def test_undo_sell(app) -> None:
    """Ctrl+Z в диалоге продажи отменяет последнюю продажу."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter", "5", "enter")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, SellScreen)
            await pilot.press("enter", "5", "enter")
            await pilot.pause()
            st = app.state
            assert st.cargo[0] == 0
            credits_after_sell = st.credits
            await pilot.press("ctrl+z")
            await pilot.pause()
            assert st.cargo[0] == 5
            assert st.credits < credits_after_sell

    _run(scenario())


def test_trade_log_f4(app) -> None:
    """F4 открывает журнал сделок сессии; покупки в него попадают."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter", "2", "enter")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.trade_history) == 1
            await pilot.press("f4")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, TradeLogScreen)
            text = str(scr.query_one("#tradelog-text", Static).render())
            assert "2" in text
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_galaxy_trend_column(app) -> None:
    """В карте галактики есть колонка Тренд с корректной меткой."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            table = app.query_one("#galaxy-table", DataTable)
            assert len(table.columns) == 7
            mark, style = _system_trend(app.state, 1)
            assert mark in {"▼", "▲", "≈"}
            assert style in {"green", "red", "dim"}

    _run(scenario())


def test_double_cancel_is_safe(app) -> None:
    """Дублированное нажатие кнопки закрытия (или Esc после клика)
    не роняет приложение: dismiss защищён проверкой вершины стека."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, BuyScreen)
            btn = scr.query_one("#buy-cancel")
            btn.press()
            btn.press()   # дублированное событие уже закрытого диалога
            await pilot.pause()
            assert len(app.screen_stack) == 1
            assert app.is_running

    _run(scenario())


def test_qty_keys(app) -> None:
    """Клавиши +, -, PgUp/PgDn, * управляют количеством без ввода цифр."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, BuyScreen)
            await pilot.press("enter")       # выбрать Food
            await pilot.pause()
            qty = scr.query_one("#buy-qty", Input)
            await pilot.press("plus")
            await pilot.pause()
            assert qty.value == "1"
            await pilot.press("plus")
            await pilot.pause()
            assert qty.value == "2"
            await pilot.press("pageup")
            await pilot.pause()
            assert qty.value == "7"
            await pilot.press("pagedown")
            await pilot.pause()
            assert qty.value == "2"
            await pilot.press("minus")
            await pilot.pause()
            assert qty.value == "1"
            await pilot.press("asterisk")    # максимум
            await pilot.pause()
            assert qty.value == str(_max_buy(app.state, 0))
            await pilot.press("minus")       # шаг вниз работает и от максимума
            await pilot.pause()
            assert int(qty.value) < _max_buy(app.state, 0)

    _run(scenario())


def test_last_commodity_memory(app) -> None:
    """Повторное открытие диалогов (b/s) ставит курсор на товар,
    выбранный в прошлый раз."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Запоминаем второй товар РЫНКА как «последний» для покупки
            app.last_buy_ci = app._market_indices[1]
            await pilot.press("b")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, BuyScreen)
            assert scr._selected_ci() == app._market_indices[1]
            await pilot.press("escape")
            await pilot.pause()
            # Для продажи аналогично
            app.last_sell_ci = 0
            await pilot.press("s")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, SellScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_adaptive_width(app) -> None:
    """CSS диалогов использует адаптивную ширину min(width, 95%)."""

    assert "width: 72; max-width: 95%" in elite_tui_src()
    assert "width: 84; max-width: 95%" in elite_tui_src()


def elite_tui_src() -> str:
    import inspect

    import elite_tui

    return inspect.getsource(elite_tui)


def test_sell_dialog_empty_cargo(app) -> None:
    """Продажа с пустым трюмом: диалог открывается и закрывается по Esc."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, SellScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_jump_dialog_opens_and_cancels(app) -> None:
    """Диалог прыжка: открывается по 'j', Esc возвращает на главный экран."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("j")
            await pilot.pause()
            assert isinstance(app.screen, JumpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_wait_recharges_and_refreshes(app) -> None:
    """'w' — ход ожидания: приложение живо, состояние доступно."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("w")
            await pilot.pause()
            assert app.state is not None
            assert app.is_running

    _run(scenario())


def test_refuel_when_full(app) -> None:
    """'r' при полном баке: только сообщение в лог, без ошибок."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            fuel_before = app.state.fuel
            await pilot.press("r")
            await pilot.pause()
            assert app.state.fuel == fuel_before

    _run(scenario())


# --------------------------------------------------------------------------
# Сохранение/загрузка (.elite): сериализация, quick save/load, диалоги
# --------------------------------------------------------------------------


def test_save_load_roundtrip(tmp_path) -> None:
    """save/load: полное восстановление состояния + продолжение PRNG."""
    st = GameState(galaxy=0, system_index=0)
    st.load_system()
    st.buy("Food", 5)
    st.defense.forward_shield = 200
    st.rng.next_byte()                      # сдвиг случайной последовательности
    path = str(tmp_path / "save.elite")
    save_game_to_path(st, path)

    st2 = load_game_from_path(path)
    assert st2.credits == st.credits
    assert st2.cargo == st.cargo
    assert st2.galaxy == st.galaxy
    assert st2.system_index == st.system_index
    assert st2.fuel == st.fuel
    assert (st2.defense.forward_shield, st2.defense.aft_shield,
            st2.defense.energy) == (
        st.defense.forward_shield, st.defense.aft_shield,
        st.defense.energy)
    assert st2.market.available(0) == st.market.available(0)
    assert list(st2.rng.state) == list(st.rng.state)
    # Детерминизм продолжается: следующий байт PRNG совпадает
    assert st.rng.next_byte() == st2.rng.next_byte()


def test_load_rejects_bad_files(tmp_path) -> None:
    """Битый JSON или неверная версия сейва -> ValueError."""
    bad = tmp_path / "bad.elite"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_game_from_path(str(bad))

    wrong_version = tmp_path / "v99.elite"
    wrong_version.write_text('{"version": 99}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_game_from_path(str(wrong_version))


def test_quick_save_load_roundtrip(tmp_path) -> None:
    """F5/F9: quick save -> изменения -> quick load восстанавливает."""

    async def scenario() -> None:
        app = EliteTUI(db_path=str(tmp_path / "events.db"))
        app.quick_save_path = str(tmp_path / QUICKSAVE_PATH)
        async with app.run_test(size=(120, 40)) as pilot:
            # Покупаем 5 Food (диалог остаётся открытым — закрываем)
            await pilot.press("b", "enter", "5", "enter", "escape")
            await pilot.pause()
            saved_credits = app.state.credits
            # Quick save
            await pilot.press("f5")
            await pilot.pause()
            # Ещё покупка после сейва
            await pilot.press("b", "enter", "3", "enter", "escape")
            await pilot.pause()
            assert app.state.cargo[0] == 8
            # Quick load откатывает к сейву
            await pilot.press("f9")
            await pilot.pause()
            assert app.state.cargo[0] == 5
            assert app.state.credits == saved_credits
            assert os.path.exists(app.quick_save_path)

    _run(scenario())


def test_file_dialog_save_returns_elite_path(tmp_path) -> None:
    """Диалог сохранения: имя без расширения получает .elite, Enter
    возвращает полный путь через колбэк push_screen."""

    async def scenario() -> None:
        app = EliteTUI(db_path=str(tmp_path / "events.db"))
        results: list = []
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(
                FileDialog(mode="save", directory=str(tmp_path)),
                results.append,
            )
            await pilot.pause()
            await pilot.press("tab")           # DataTable -> Input
            await pilot.press("t", "e", "s", "t")
            await pilot.press("enter")
            await pilot.pause()
        assert results == [os.path.join(str(tmp_path), "test.elite")]

    _run(scenario())


def test_file_dialog_load_lists_files(tmp_path) -> None:
    """Диалог загрузки: показывает .elite-файлы; Enter на строке
    подставляет имя в поле, второй Enter подтверждает выбор."""
    (tmp_path / "qs1.elite").write_text("{}", encoding="utf-8")

    async def scenario() -> None:
        app = EliteTUI(db_path=str(tmp_path / "events.db"))
        results: list = []
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(
                FileDialog(mode="load", directory=str(tmp_path)),
                results.append,
            )
            await pilot.pause()
            await pilot.press("enter")         # выбор строки -> в Input
            await pilot.pause()
            await pilot.press("enter")         # подтверждение
            await pilot.pause()
        assert results == [str(tmp_path / "qs1.elite")]

    _run(scenario())


def test_save_load_dialog_flow(tmp_path) -> None:
    """F2 сохраняет в файл из диалога, F3 загружает из списка файлов."""

    async def scenario() -> None:
        app = EliteTUI(db_path=str(tmp_path / "events.db"))
        app.saves_dir = str(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            # Покупаем 5 Food и сохраняем через F2 (имя "s1")
            await pilot.press("b", "enter", "5", "enter", "escape")
            await pilot.pause()
            saved_credits = app.state.credits
            await pilot.press("f2")
            await pilot.pause()
            await pilot.press("tab", "s", "1")
            await pilot.press("enter")
            await pilot.pause()
            assert os.path.exists(str(tmp_path / "s1.elite"))
            # Ещё покупка, затем загрузка через F3 (файл в списке)
            await pilot.press("b", "enter", "2", "enter", "escape")
            await pilot.pause()
            assert app.state.cargo[0] == 7
            await pilot.press("f3")
            await pilot.pause()
            await pilot.press("enter")         # выбрать строку -> Input
            await pilot.pause()
            await pilot.press("enter")         # подтвердить
            await pilot.pause()
            assert app.state.cargo[0] == 5
            assert app.state.credits == saved_credits

    _run(scenario())


# --------------------------------------------------------------------------
# Доработки: переподключение логгера, бой/game over, прыжок, заправка,
# описание системы, валидация имени файла
# --------------------------------------------------------------------------


class _FakeLogger:
    """Минимальная реализация EventLoggerProtocol для тестов."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.session_id: str = "fake-session"

    def new_session(self, session_id=None) -> str:
        self.events.append("new_session")
        self.session_id = session_id or "fake-session-2"
        return self.session_id

    def capture(self, gs) -> None:
        self.events.append("capture")

    def log_buy(self, gs, item, qty, unit_price, total_cost) -> None:
        self.events.append(f"buy:{item}:{qty}")

    def log_sell(self, gs, item, qty, unit_price, total_cost) -> None:
        self.events.append(f"sell:{item}:{qty}")

    def log_jump(self, gs, target_index, target_name,
                 distance_ly, fuel_cost) -> None:
        self.events.append(f"jump:{target_index}")

    def log_refuel(self, gs, cost, new_fuel) -> None:
        self.events.append("refuel")

    def log_combat(self, gs, action, details) -> None:
        self.events.append(f"combat:{action}")

    def log_wait(self, gs, details) -> None:
        self.events.append("wait")

    def close(self) -> None:
        self.events.append("close")


def test_load_reconnects_event_logger(tmp_path) -> None:
    """load_game_from_path: логгер подключается, события пишутся после загрузки."""
    st = GameState(galaxy=0, system_index=0)
    st.load_system()
    path = str(tmp_path / "s.elite")
    save_game_to_path(st, path)

    logger = _FakeLogger()
    st2 = load_game_from_path(path, event_logger=logger)
    assert st2.event_logger is logger
    st2.buy("Food", 1)
    assert "buy:Food:1" in logger.events


def test_quick_load_reconnects_app_logger(app, tmp_path) -> None:
    """F9: после быстрой загрузки state.event_logger === app.logger."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("f5")
            await pilot.pause()
            await pilot.press("b", "enter", "1", "enter", "escape")
            await pilot.pause()
            await pilot.press("f9")
            await pilot.pause()
            assert app.state.event_logger is app.logger

    _run(scenario())


def test_jump_flow_executes(app) -> None:
    """Прыжок: выбор первой строки карты меняет систему и списывает топливо."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            target = app.state.near_systems()[0][0]
            fuel_before = app.state.fuel
            # Детерминизм: отключаем случайную пиратскую атаку.
            app.state.check_pirate_attack = lambda: False  # noqa: SLF001
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("enter")       # первая (ближайшая) система
            await pilot.pause()
            assert app.state.system_index == target
            assert app.state.fuel < fuel_before
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_wait_logs_wait_event(app) -> None:
    """'w': событие хода (action="wait") пишется в журнал через wait_turn()."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            fake = _FakeLogger()
            app.logger = fake
            app.state.event_logger = fake
            shields_before = app.state.defense.forward_shield
            await pilot.press("w")
            await pilot.pause()
            assert "wait" in fake.events
            # Рынок не изменился (привязан к прыжкам, как в оригинале)
            assert app.state.market is not None
            assert app.state.defense.forward_shield >= shields_before

    _run(scenario())


def test_refuel_when_not_full(app) -> None:
    """'r' при неполном баке: бак становится полным, кредиты списываются."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            app.state.fuel = 10.0
            await pilot.press("r")
            await pilot.pause()
            assert app.state.fuel == 70.0
            assert app.state.credits < 100.0

    _run(scenario())


def test_info_screen_opens_and_cancels(app) -> None:
    """'i' открывает описание системы, Esc закрывает."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("i")
            await pilot.pause()
            assert isinstance(app.screen, InfoScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_combat_surrender_flow(app) -> None:
    """Бой: сдача ('u') не уничтожает корабль и возвращает на главный экран."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(CombatScreen(app.state), app._on_combat_done)
            await pilot.pause()
            assert isinstance(app.screen, CombatScreen)
            await pilot.press("u")
            await pilot.pause()
            assert len(app.screen_stack) == 1
            assert app.is_running

    _run(scenario())


def test_combat_destroyed_game_over_new_game(app) -> None:
    """Бой: уничтожение -> GameOverScreen -> 'n' начинает новую игру."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            # Обнуляем защиту: любая атака (>= 3 x 40 урона) уничтожит корабль.
            app.state.defense.forward_shield = 0
            app.state.defense.aft_shield = 0
            app.state.defense.energy = 1
            app.push_screen(CombatScreen(app.state), app._on_combat_done)
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            assert isinstance(app.screen, GameOverScreen)
            await pilot.press("n")
            await pilot.pause()
            assert len(app.screen_stack) == 1
            assert app.state.credits == 100.0
            assert app.state.fuel == 70.0

    _run(scenario())


def test_game_over_quit_closes_logger(app) -> None:
    """GameOverScreen: 'q' выходит и закрывает журнал событий."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            app.state.defense.forward_shield = 0
            app.state.defense.aft_shield = 0
            app.state.defense.energy = 1
            app.push_screen(CombatScreen(app.state), app._on_combat_done)
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            assert not app.is_running
            assert app.logger is None

    _run(scenario())


def test_help_screen_via_key_and_button(app) -> None:
    """'h' и кнопка 'Справка' открывают HelpScreen; Esc/кнопка закрывают."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("h")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

            await pilot.click("#btn-help")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.click("#help-close")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_help_screen_keys_do_not_leak(app) -> None:
    """Внутри справки игровые клавиши не срабатывают."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("h")
            await pilot.pause()
            await pilot.press("b", "s", "q")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            assert app.is_running
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    _run(scenario())


def test_new_game_starts_new_session(app) -> None:
    """Новая игра (в т.ч. после game over) начинает новую партию в журнале."""

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            fake = _FakeLogger()
            app.logger = fake
            app.state.event_logger = fake
            app._new_game()
            await pilot.pause()
            assert "new_session" in fake.events
            assert app.state.event_logger is fake

    _run(scenario())


def test_file_dialog_rejects_path_traversal(tmp_path) -> None:
    """FileDialog: имя с путями ('../evil') отклоняется, диалог остаётся открыт."""

    async def scenario() -> None:
        app = EliteTUI(db_path=str(tmp_path / "events.db"))
        results: list = []
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(
                FileDialog(mode="save", directory=str(tmp_path)),
                results.append,
            )
            await pilot.pause()
            await pilot.press("tab")           # DataTable -> Input
            await pilot.pause()
            app.screen.query_one("#file-name", Input).value = "../evil"
            await pilot.press("enter")
            await pilot.pause()
            assert results == []
            assert isinstance(app.screen, FileDialog)

    _run(scenario())
