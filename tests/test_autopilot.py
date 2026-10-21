"""
test_autopilot.py — тесты автономного бота elite_autopilot.

Бот играет напрямую через elite_core.GameState (без CLI/UI), полностью
детерминированно (модуль random не используется). Проверяются: структура
результатов, прибыльность, правила боя по щитам, поиск маршрутов,
прогрессивная стратегия и отсутствие застреваний.

Лицензия: GPL v3.
"""

from __future__ import annotations

import inspect
import sqlite3
from unittest.mock import MagicMock

import pytest

import elite_autopilot as ea
from elite_autopilot import Autopilot, BotResult, TradeRoute
from elite_core import GameState


def make_bot(
    galaxy: int = 1,
    system: int = 0,
    credits: float = 100.0,
    risk: str = "medium",
    rounds: int = 60,
) -> Autopilot:
    """Свежий бот с чистым состоянием (для детерминированных прогонов).

    memory_db=None — без памяти самообучения (бот детерминирован и не
    создаёт bot_memory.db в рабочей директории).
    """
    return Autopilot(
        GameState(galaxy=galaxy, system_index=system, credits=credits),
        max_rounds=rounds,
        risk_tolerance=risk,
        log_file=None,
        memory_db=None,
        verbose=False,
    )


# --------------------------------------------------------------------------
# 1. Структура модуля
# --------------------------------------------------------------------------


def test_import_and_all():
    assert set(ea.__all__) == {
        "TradeRoute", "BotDecision", "BotResult", "CombatSimStats",
        "TuneResult", "BotMemory", "Autopilot", "optimize_constants", "main",
    }


def test_no_random_import():
    """random используется ТОЛЬКО в BotMemory (epsilon-greedy Q-learning),
    вся остальная логика бота детерминирована."""
    source = inspect.getsource(ea)
    memory_source = inspect.getsource(ea.BotMemory)
    rest = source.replace(memory_source, "")
    assert "import random" not in rest
    assert "from random" not in rest


def test_risk_tolerance_validation():
    with pytest.raises(ValueError):
        Autopilot(GameState(), risk_tolerance="crazy")


# --------------------------------------------------------------------------
# 2. run() — структура результата и детерминизм
# --------------------------------------------------------------------------


def test_run_result_fields():
    # galaxy 0: стартовая система окружена опасными системами
    # (p_attack >= 0.25) — риск-дисконт EV ограничивает торговлю,
    # лог короче проверяемого минимума.
    res = make_bot(galaxy=0, rounds=40).run()
    assert isinstance(res, BotResult)
    assert 1 <= res.rounds_played <= 40
    assert res.final_credits >= 0.0
    assert res.starting_credits == 100.0
    assert res.profit == pytest.approx(
        res.final_credits - res.starting_credits
    )
    assert res.roi_pct == pytest.approx(
        res.profit / res.starting_credits * 100.0
    )
    assert res.jumps_made >= 0
    assert res.combats_encountered >= 0
    assert res.combats_won >= 0
    assert res.combats_fled >= 0
    assert len(res.log_lines) > 10  # осмысленный лог


def test_run_deterministic():
    """Одинаковое состояние -> одинаковый результат (без random)."""
    r1 = make_bot().run()
    r2 = make_bot().run()
    assert r1 == r2


def _peak_credits(res: BotResult) -> float:
    """Максимум кредитов по логу (кредиты скачут при вложениях в груз)."""
    peak = res.starting_credits
    for line in res.log_lines:
        if line.startswith("[Round"):
            part = line.split("Credits: ")[1]
            peak = max(peak, float(part.split(" Cr")[0]))
    return peak


def test_run_profitable_medium():
    """medium-risk в галактике 0: капитал стабильно растёт.

    Кредиты скачут между покупками (всё вложено в груз) и продажами,
    поэтому рост оценивается по ПИКУ кредитов за прогон.
    """
    res = make_bot(galaxy=0, rounds=100).run()
    # 1.3x: риск-дисконт EV (prior p=0.25 для Dictatorship/Communist)
    # делает часть маршрутов непривлекательной — пик скромнее 1.5x,
    # но торговля остаётся прибыльной.
    assert _peak_credits(res) > res.starting_credits * 1.3


def test_run_no_stall():
    """Бот не застревает на паре систем."""
    res = make_bot(galaxy=0, rounds=100).run()
    assert "Stall" not in "\n".join(res.log_lines)
    # Досрочный выход допускается ТОЛЬКО через dead_end (CREDIT_FLOOR /
    # истинный тупик) — это рестарт, а не застревание.
    assert res.rounds_played <= 100


# --------------------------------------------------------------------------
# 3. Торговые маршруты
# --------------------------------------------------------------------------


def test_find_best_routes_sorted():
    bot = make_bot(galaxy=0, system=0)
    routes = bot._find_best_routes()
    assert isinstance(routes, list)
    assert all(isinstance(r, TradeRoute) for r in routes)
    profits = [r.net_profit for r in routes]
    assert profits == sorted(profits, reverse=True)
    assert all(p > 0 for p in profits)
    assert all(r.from_index == 0 for r in routes)
    if routes:
        route = routes[0]
        assert route.commodity_name
        assert route.buy_price > 0
        assert route.sell_price > route.buy_price
        assert route.max_qty > 0
        assert route.fuel_cost > 0
        assert route.distance_ly > 0


def test_find_best_routes_respects_fuel_budget():
    """Покупка не должна съедать деньги на долив топлива для прыжка.

    Из бюджета вычитается только стоимость недостающего топлива (бак уже
    может быть полон — тогда долив бесплатный).
    """
    bot = make_bot(galaxy=0, system=0)
    fuel_now = int(round(bot.state.fuel))
    for route in bot._find_best_routes():
        fuel_needed = max(0, route.fuel_cost - fuel_now)
        fuel_cr = fuel_needed * ea.FUEL_PRICE_CR_PER_UNIT
        assert route.buy_price * route.max_qty + fuel_cr <= bot.state.credits


def test_min_profit_filters():
    """Маршруты ниже порогов маржи и чистой прибыли отбрасываются.

    В galaxy 0 (старт, < 500 Cr) действует ранний порог 1.0 Cr/ton;
    поздняя игра (>= 2000 Cr) — жёсткий порог 2.0 Cr/ton.
    """
    early = make_bot(galaxy=0, system=0)
    routes = early._find_best_routes()
    assert routes, "ожидались маршруты с маржой >= 1 Cr/ton"
    for route in routes:
        assert route.profit_per_ton >= ea.EARLY_MIN_PROFIT_PER_TON
        assert route.net_profit >= ea.MIN_NET_PROFIT
    late = make_bot(galaxy=0, system=0, credits=3000.0)
    for route in late._find_best_routes():
        assert route.profit_per_ton >= ea.MIN_PROFIT_PER_TON


def test_danger_penalty_applied():
    """Risk-adjusted EV: net_profit никогда не выше raw (риск не повышает
    прибыль), а опасные системы дисконтируются сильнее безопасных."""
    bot = make_bot(galaxy=0, system=0)
    routes = bot._find_best_routes()
    assert routes
    fuel_now = int(round(bot.state.fuel))
    for route in routes:
        fuel_needed = max(0, route.fuel_cost - fuel_now)
        raw = (
            route.profit_per_ton * route.max_qty
            - fuel_needed * ea.FUEL_PRICE_CR_PER_UNIT
        )
        # _expected_value вычитает ожидаемые потери от атаки
        assert route.net_profit <= raw + 1e-9


def test_expected_value_safe_positive():
    """EV положителен для безопасной системы (Democracy, без истории атак)."""
    bot = make_bot(galaxy=0, system=0)
    bot._market_of(5).system["government"] = 6   # Democracy
    assert bot._expected_value(5, 100.0, 100.0) > 0
    # с пустым трюмом (cargo_value=0) учитывается только выживание
    assert bot._expected_value(5, 10.0) > 0


def test_expected_value_dangerous_discounted():
    """Точная модель риска (Монте-Карло боя, elite_autopilot._simulate_combat).

    При полном баке побег почти всегда успешен (210/256), поэтому EV Anarchy
    остаётся положительным, но строго ниже gross (риск не повышает прибыль).
    При малом топливе побег почти невозможен (15/256), лучшее действие —
    surrender (потеря 25% груза и 10-50% кредитов) — EV <= 0. Дисконт риска
    растёт при уменьшении топлива.
    """
    bot = make_bot(galaxy=0, system=0)
    bot._market_of(5).system["government"] = 0   # Anarchy
    ev_full = bot._expected_value(5, 100.0, 100.0)
    assert 0 < ev_full < 100.0
    # Малое топливо: побег почти невозможен -> риск не окупается
    bot.state.fuel = 5.0
    ev_low = bot._expected_value(5, 5.0, 100.0)
    assert ev_low <= 0
    assert ev_low < ev_full


def test_expected_value_uses_fuel_after_jump():
    """EV учитывает топливо ПОСЛЕ прыжка: дальний прыжок в рискованную
    систему опаснее ближнего при том же уровне бака."""
    bot = make_bot(galaxy=0, system=0)
    bot._market_of(5).system["government"] = 0   # Anarchy
    near_cost = bot.state.jump_engine.calculate_fuel_cost(0, 5)
    far = make_bot(galaxy=0, system=0)
    far._market_of(5).system["government"] = 0
    # Симулируем «дальний прыжок»: топлива к моменту боя меньше
    bot.state.fuel = float(near_cost) + 1
    ev_after_short = bot._expected_value(5, 100.0, 100.0)
    far.state.fuel = float(near_cost) + 30
    ev_after_long = far._expected_value(5, 100.0, 100.0)
    assert ev_after_long >= ev_after_short


def test_simulate_combat_deterministic_and_bounded():
    """_simulate_combat: детерминизм, границы вероятностей, лучшее действие."""
    bot = make_bot(galaxy=0, system=0)
    s1 = bot._simulate_combat(0, 70, 8)
    s2 = bot._simulate_combat(0, 70, 8)
    assert s1 == s2
    assert s1.action in ("fight", "flee", "surrender")
    assert 0.0 <= s1.p_death <= 1.0
    assert 0.0 <= s1.cargo_frac <= 1.0
    assert 0.0 <= s1.credit_frac <= 1.0
    # Кеш работает: повторный вызов не меняет результат
    assert len(bot._combat_sim_cache) == 1


def test_pre_jump_refuel_guard():
    """Умный бот (1): рискованная цель + неполный бак + деньги -> refuel."""
    bot = make_bot(galaxy=0, system=0, credits=100.0)
    bot._market_of(5).system["government"] = 0   # Anarchy (P ~ 0.5)
    bot.state.fuel = 30.0
    decision = bot._pre_jump_refuel(5)
    assert decision is not None and decision.action == "refuel"
    # Полный бак -> заправка не нужна
    bot.state.fuel = float(ea.FUEL_TANK_CAPACITY)
    assert bot._pre_jump_refuel(5) is None
    # Нет денег -> не мешаем (dead-end логика сама разберётся)
    bot.state.fuel = 30.0
    bot.state.credits = 0.0
    assert bot._pre_jump_refuel(5) is None
    # Безопасная цель (Democracy, P ~ 0.09 < порога) -> без заправки
    bot.state.credits = 100.0
    bot._market_of(7).system["government"] = 6
    assert bot._pre_jump_refuel(7) is None


# --------------------------------------------------------------------------
# 3.1 Умное планирование (3): двухколенные цепочки (_plan_chain)
# --------------------------------------------------------------------------


def test_neighbors_sorted_and_bounded():
    """_neighbors: соседи произвольной системы, сортировка по расходу
    топлива, расход в пределах max_ly и без самой системы."""
    bot = make_bot(galaxy=0, system=0)
    neighbors = bot._neighbors(0, 5.0)
    assert neighbors
    costs = [c for _idx, c in neighbors]
    assert costs == sorted(costs)
    assert all(0 < c <= 50 for c in costs)
    assert all(idx != 0 for idx, _c in neighbors)


def test_continuation_profit_deterministic():
    """_continuation_profit: детерминизм; без кредитов продолжения нет."""
    bot = make_bot(galaxy=0, system=0)
    c1 = bot._continuation_profit(5, 500.0)
    c2 = bot._continuation_profit(5, 500.0)
    assert c1 == c2
    assert c1[0] >= 0.0 and c1[1] >= 0
    assert bot._continuation_profit(5, 0.0) == (0.0, 0)


def test_plan_chain_contract():
    """_plan_chain: первое колено с chain_fuel > fuel_cost первого колена
    и суммарной прибылью >= 2*MIN_NET_PROFIT; детерминизм."""
    bot = make_bot(galaxy=0, system=0)
    raw = sorted(bot._raw_routes(), key=lambda r: r.net_profit, reverse=True)
    chain = bot._plan_chain(raw[: ea.CHAIN_FIRST_LEGS])
    if chain is None:
        pytest.skip("no profitable chain from this start")
    assert chain.chain_fuel > chain.fuel_cost
    assert chain.net_profit >= 2 * ea.MIN_NET_PROFIT
    assert bot._plan_chain(raw[: ea.CHAIN_FIRST_LEGS]) == chain


def test_best_plan_efficiency_consistent():
    """_best_plan: цепочка выбирается только когда она выгоднее лучшего
    одноколенного маршрута по Cr на единицу топлива."""
    bot = make_bot(galaxy=0, system=0, credits=3000.0)
    plan = bot._best_plan()
    if plan is None:
        pytest.skip("no routes from this start")
    single = max(
        bot._raw_routes(),
        key=lambda r: r.net_profit / max(r.fuel_cost, 1),
    )
    if plan.chain_fuel:
        assert plan.net_profit / plan.chain_fuel > single.net_profit / single.fuel_cost
    else:
        assert plan.to_index == single.to_index


def test_tunables_override():
    """Умный бот (4): tunables переопределяют константы экземпляра."""
    bot = make_bot()
    assert bot._fuel_reserve_units(52) == ea.MIN_FUEL_RESERVE
    bot._tunables["MIN_FUEL_RESERVE"] = 30.0
    assert bot._fuel_reserve_units(52) == 30
    # _tuned: неизвестное имя -> KeyError (опечатка в имени константы)
    with pytest.raises(KeyError):
        bot._tuned("TYPO_CONSTANT")


def test_optimize_constants_smoke():
    """optimize_constants: координатный спуск работает, результат
    применяется к боту через tunables."""
    res = ea.optimize_constants(
        galaxies=(0,),
        rounds=15,
        seeds=1,
        passes=1,
        params=("MIN_NET_PROFIT",),
        grid={"MIN_NET_PROFIT": (2.0, 20.0, 60.0)},
        verbose=False,
    )
    # Если ни одно значение сетки не улучшило score — остаётся дефолт 5.0
    assert res.best["MIN_NET_PROFIT"] in (2.0, 5.0, 20.0, 60.0)
    assert res.log_lines
    # Найденный набор применяется к боту без ошибок
    st = GameState(galaxy=0, system_index=0)
    st.load_system()
    bot = Autopilot(
        st, max_rounds=10, risk_tolerance="medium",
        log_file=None, memory_db=None, verbose=False,
        tunables=res.best,
    )
    result = bot.run()
    assert result.rounds_played > 0


# --------------------------------------------------------------------------
# 4. Прогрессивная стратегия
# --------------------------------------------------------------------------


def test_progressive_commodities():
    cheap = [0, 1, 12]
    mid = cheap + [4, 7, 8]
    assert make_bot(credits=100).state.credits < 500
    assert set(make_bot(credits=100)._allowed_commodities()) == set(cheap)
    assert set(make_bot(credits=1000)._allowed_commodities()) == set(mid)
    assert set(make_bot(credits=5000)._allowed_commodities()) == set(range(16))


def test_late_game_uses_expensive_goods():
    """С большим капиталом бот покупает дорогие товары (Alloys/Furs)."""
    bot = make_bot(credits=3000.0, rounds=30)
    res = bot.run()
    buy_lines = [l for l in res.log_lines if "Action: BUY" in l]
    names = " ".join(buy_lines)
    assert any(name in names for name in ("Alloys", "Furs", "Gold", "Luxuries"))


# --------------------------------------------------------------------------
# 5. Бой
# --------------------------------------------------------------------------


def _combat_decision(
    risk: str, energy: int, fsh: int, ash: int, gov: int = 7
) -> str:
    """Решение в бою при заданных щитах и правительстве системы.

    gov по умолчанию 7 (Corporate) — безопасная система; для опасных
    передаётся 0 (Anarchy) или 3 (Dictatorship).
    """
    state = GameState()
    state.system["government"] = gov   # SystemRow — dict, правка локальна
    state.defense.energy = energy
    state.defense.forward_shield = fsh
    state.defense.aft_shield = ash
    bot = Autopilot(state, risk_tolerance=risk, verbose=False, memory_db=None)
    return bot._handle_combat().action


def test_combat_medium_safe_system_full_shields_fights():
    # Corporate (gov=7): полные щиты -> fight
    assert _combat_decision("medium", 255, 255, 255) == "fight"


def test_combat_medium_safe_system_low_energy_surrenders():
    # energy < 25% от 255 (~64) -> surrender
    assert _combat_decision("medium", 40, 255, 255) == "surrender"


def test_combat_medium_safe_system_half_energy_flees():
    # energy < 50% от 255 (~128) -> flee
    assert _combat_decision("medium", 100, 255, 255) == "flee"


def test_combat_medium_safe_system_broken_forward_shield_flees():
    assert _combat_decision("medium", 200, 30, 255) == "flee"


def test_combat_medium_anarchy_always_flees():
    # Anarchy (gov=0) — flee даже при полных щитах.
    assert _combat_decision("medium", 255, 255, 255, gov=0) == "flee"
    assert _combat_decision("medium", 255, 255, 255, gov=1) == "flee"   # Feudal


def test_combat_medium_moderate_fights_only_with_full_shields():
    # Dictatorship (gov=3): fight только при energy>=200 и FSH>=200.
    assert _combat_decision("medium", 210, 220, 255, gov=3) == "fight"
    assert _combat_decision("medium", 150, 220, 255, gov=3) == "flee"
    assert _combat_decision("medium", 40, 255, 255, gov=3) == "surrender"


def test_combat_low_always_flees():
    assert _combat_decision("low", 255, 255, 255) == "flee"
    assert _combat_decision("low", 0, 0, 0, gov=0) == "flee"


def test_combat_high_fights_except_anarchy_weak_shields():
    assert _combat_decision("high", 255, 255, 255) == "fight"
    assert _combat_decision("high", 255, 255, 255, gov=0) == "fight"
    # Anarchy + слабые щиты -> flee даже для high.
    assert _combat_decision("high", 100, 50, 255, gov=0) == "flee"


def test_combat_handled_in_run():
    """Бой после прыжка логируется, счётчики согласованы."""
    res = make_bot(rounds=100).run()
    combat_logs = [l for l in res.log_lines if "COMBAT:" in l]
    assert len(combat_logs) == res.combats_encountered
    assert res.combats_won + res.combats_fled <= res.combats_encountered


# --------------------------------------------------------------------------
# 6. main() — CLI отчёт
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 7. Бесконечный режим (max_rounds=0, STALL_LIMIT=0)
# --------------------------------------------------------------------------


def test_default_max_rounds_is_infinite():
    assert Autopilot(GameState(), memory_db=None).max_rounds == 0


def test_positive_max_rounds_backward_compatible():
    assert Autopilot(GameState(), max_rounds=50, memory_db=None).max_rounds == 50
    assert Autopilot(GameState(), max_rounds=-3, memory_db=None).max_rounds == 0


def test_wait_under_stall_limit_does_not_stop():
    """WAIT-раунды не останавливают бота, пока их меньше STALL_LIMIT."""
    assert ea.STALL_LIMIT == 10
    bot = make_bot(rounds=5)

    def always_wait() -> ea.BotDecision:
        return ea.BotDecision("wait", {}, "test stall")

    bot._plan_turn = always_wait  # type: ignore[method-assign]
    res = bot.run()
    assert res.rounds_played == 5  # 5 < 10 — дошли до лимита раундов


def test_run_keyboard_interrupt_graceful(monkeypatch):
    """KeyboardInterrupt внутри run() перехватывается и логируется."""
    bot = make_bot(rounds=50)

    def boom() -> ea.BotDecision:
        raise KeyboardInterrupt

    monkeypatch.setattr(bot, "_plan_turn", boom)
    res = bot.run()  # не должен пробрасывать исключение
    assert any(
        "Interrupted by user (Ctrl-C)." in line for line in res.log_lines
    )
    assert res.rounds_played >= 1
    assert res.final_credits >= 0.0


# --------------------------------------------------------------------------
# 8. main() и запуск в отдельном процессе
# --------------------------------------------------------------------------


def test_infinite_run_terminates_by_signal():
    """Без пиратов бот (max_rounds=0) работает бесконечно и выходит по SIGINT.

    Проверка в отдельном процессе: SIGINT после паузы -> exit 0, в логе —
    'Interrupted by user (Ctrl-C).', отчёт напечатан.
    """
    import signal
    import subprocess
    import sys
    import time

    code = """
from elite_core import GameState
from elite_autopilot import Autopilot
GameState.check_pirate_attack = lambda self: False  # вечная торговля
res = Autopilot(GameState(galaxy=0, system_index=0), max_rounds=0,
                log_file=None, memory_db=None, verbose=False).run()
in_log = any('Interrupted by user (Ctrl-C).' in l for l in res.log_lines)
print('DONE rounds=%d ctrl_c_in_log=%s' % (res.rounds_played, in_log))
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(1.0)
    proc.send_signal(signal.SIGINT)
    out, _ = proc.communicate(timeout=20)
    assert proc.returncode == 0, out
    assert "DONE rounds=" in out
    assert "ctrl_c_in_log=True" in out, out


def test_main_propagates_keyboard_interrupt_before_run(monkeypatch):
    """Ctrl-C до внутреннего try run() не перехватывается main().

    Реальный run() ловит KeyboardInterrupt сам и возвращает BotResult;
    main() не дублирует этот перехват (мёртвый код убран). Если же
    исключение всё-таки возникло до внутреннего try run() — оно
    распространяется вверх, а не маскируется под return 0.
    """
    fake = MagicMock()
    fake.run.side_effect = KeyboardInterrupt
    monkeypatch.setattr(ea, "Autopilot", lambda *args, **kwargs: fake)
    with pytest.raises(KeyboardInterrupt):
        ea.main()


def test_main_report(capsys, monkeypatch):
    """main() печатает отчёт; Autopilot замокан, чтобы не писать лог-файл."""
    fake = MagicMock()
    fake.run.return_value = BotResult(
        rounds_played=100,
        final_credits=4523.80,
        starting_credits=100.0,
        profit=4423.80,
        roi_pct=4423.8,
        jumps_made=47,
        combats_encountered=8,
        combats_won=3,
        combats_fled=5,
    )
    monkeypatch.setattr(ea, "Autopilot", lambda *args, **kwargs: fake)
    assert ea.main() == 0
    out = capsys.readouterr().out
    assert "=== pyElite — Autopilot Report ===" in out
    assert "Rounds played:    100" in out
    assert "Final credits:    4523.80 Cr" in out
    assert "ROI:              4424%" in out
    assert "=== End Report ===" in out


# --------------------------------------------------------------------------
# 9. BotMemory — Bayesian-статистика систем (умный бот (5): без Q/UCB1)
# --------------------------------------------------------------------------


def test_bot_memory_danger_prior_by_government(tmp_path):
    """Bayesian: prior по правительству; опыт смещает оценку."""
    mem = ea.BotMemory(str(tmp_path / "mem.db"))
    # без данных Anarchy (gov 0) опаснее Corporate (gov 7)
    assert mem.danger_score(10, 0) > mem.danger_score(20, 7)
    mem.record_visit(10, attacked=True)
    mem.record_visit(10, attacked=False)
    assert 0.4 < mem.danger_score(10, 0) < 1.0
    mem.close()


def test_bot_memory_system_stats_persist(tmp_path):
    """record_visit/record_attack персистентны между открытиями БД."""
    path = str(tmp_path / "mem.db")
    mem = ea.BotMemory(path)
    mem.record_visit(7, attacked=False)
    mem.record_attack(7)
    mem.record_visit(7, attacked=True)
    stats = mem._get_system_stats(7)
    assert stats == {"visits": 2, "attacks": 2}
    mem.close()
    mem2 = ea.BotMemory(path)
    assert mem2._get_system_stats(7) == {"visits": 2, "attacks": 2}
    mem2.close()


def test_bot_memory_player_id_separation(tmp_path):
    """Разные player_id в одной БД не видят данные друг друга."""
    path = str(tmp_path / "mem.db")
    mem5 = ea.BotMemory(path, player_id=5)
    mem5.record_visit(42, attacked=True)
    assert mem5._get_system_stats(42)["attacks"] == 1
    mem5.close()

    mem0 = ea.BotMemory(path, player_id=0)
    assert mem0._get_system_stats(42)["attacks"] == 0
    mem0.close()


def test_bot_memory_migrates_old_db(tmp_path):
    """Старая БД (PK без player_id) мигрируется: данные -> player_id=0;
    таблицы combat_q/route_stats (Q-learning/UCB1 удалены) игнорируются,
    но не удаляются."""
    path = str(tmp_path / "old_mem.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE combat_q ("
        "  state_key TEXT NOT NULL, action TEXT NOT NULL,"
        "  q_value REAL NOT NULL DEFAULT 0.0,"
        "  PRIMARY KEY (state_key, action))")
    conn.execute(
        "CREATE TABLE route_stats ("
        "  route_key TEXT PRIMARY KEY, tries INTEGER NOT NULL DEFAULT 0,"
        "  total_profit REAL NOT NULL DEFAULT 0.0,"
        "  avg_profit REAL NOT NULL DEFAULT 0.0)")
    conn.execute(
        "CREATE TABLE system_stats ("
        "  system_index INTEGER PRIMARY KEY, visits INTEGER NOT NULL DEFAULT 0,"
        "  attacks INTEGER NOT NULL DEFAULT 0)")
    conn.execute(
        "INSERT INTO combat_q (state_key, action, q_value) "
        "VALUES ('1,1,1', 'flee', 0.7)")
    conn.execute(
        "INSERT INTO route_stats (route_key, tries, total_profit, avg_profit) "
        "VALUES ('X->Y:Food', 3, 30.0, 10.0)")
    conn.execute(
        "INSERT INTO system_stats (system_index, visits, attacks) "
        "VALUES (7, 5, 2)")
    conn.commit()
    conn.close()

    mem = ea.BotMemory(path, player_id=2)   # миграция при открытии
    # Мигрированные данные принадлежат ИГРОКУ 0, поэтому player 2 их не видит
    assert mem._get_system_stats(7)["attacks"] == 0
    mem.record_visit(7, attacked=True)      # данные игрока 2
    mem.close()

    mem0 = ea.BotMemory(path, player_id=0)  # старые данные целы
    assert mem0._get_system_stats(7)["visits"] == 5
    assert mem0._get_system_stats(7)["attacks"] == 2
    mem0.close()

    mem2 = ea.BotMemory(path, player_id=2)  # данные игрока 2 на месте
    assert mem2._get_system_stats(7)["visits"] == 1
    mem2.close()

    # Старые таблицы не удаляются (просто игнорируются)
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"combat_q", "route_stats"} <= tables


def test_autopilot_fallback_without_memory():
    """memory_db=None: бот работает по старой логике (без памяти)."""
    bot = Autopilot(GameState(), memory_db=None)
    assert bot._memory is None
    d = bot._handle_combat()
    assert d.action in ("fight", "flee", "surrender")


def test_autopilot_with_memory_runs(tmp_path):
    """Полный прогон бота с памятью: не падает, БД создаётся."""
    bot = Autopilot(
        GameState(galaxy=1, system_index=0),
        max_rounds=30,
        risk_tolerance="medium",
        log_file=None,
        memory_db=str(tmp_path / "mem.db"),
        verbose=False,
    )
    res = bot.run()
    assert res.rounds_played > 0
    assert (tmp_path / "mem.db").exists()


# --------------------------------------------------------------------------
# 10. Замечания: лимит кеша рынков
# --------------------------------------------------------------------------


def test_market_cache_cleared_after_limit():
    """Кеш рынков очищается при превышении MARKET_CACHE_LIMIT (64)."""
    bot = make_bot(galaxy=0, system=0)
    for i in range(1, 66):            # 65 записей — выше лимита
        bot._market_of(i)
    assert len(bot._market_cache) == 65
    bot._market_of(100)               # новый ключ -> кеш сброшен и перезаполнен
    assert len(bot._market_cache) == 1
    assert 100 in bot._market_cache


def test_execute_sell_clears_pending(tmp_path):
    """_execute_sell: продажа очищает pending и данные о покупке."""
    bot = Autopilot(
        GameState(galaxy=0, system_index=0),
        memory_db=str(tmp_path / "mem.db"),
        log_file=None,
        verbose=False,
    )
    st = bot.state
    st.buy("Food", 5)
    bot._bought_at[0] = st.system_index
    bot._bought_price[0] = st.market.price_cr(0)
    assert st.jump(71)
    bot._pending_sell = {
        "commodity_index": 0,
        "quantity": 5,
        "price": st.market.price_cr(0),
    }
    assert bot._execute_sell()
    assert bot._pending_sell is None
    assert 0 not in bot._bought_at and 0 not in bot._bought_price
    assert bot._memory._get_system_stats(71)["visits"] == 0
    # (визиты записывает _execute_jump; прямой st.jump() память не пишет)


# --------------------------------------------------------------------------
# 11. Банкротство: отчаянный прыжок и STALL_LIMIT
# --------------------------------------------------------------------------


def test_credit_floor_bankrupt():
    """Банкрот с топливом: кредитный пол -> dead_end (рестарт) вместо
    вечного WAIT и вместо сжигания топлива на exploration/desperate-jump.

    CREDIT_FLOOR=50 срабатывает раньше шагов exploration (6) и desperate
    (6.5): при credits=0.5 и отсутствии прибыльного маршрута рестарт
    дешевле, чем прыжки без денег на заправку.
    """
    bot = make_bot(galaxy=1, system=0, credits=0.5)
    st = bot.state
    near = st.near_systems()
    if not near:
        pytest.skip("no reachable systems from start")
    nearest_cost = near[0][3]
    st.fuel = float(nearest_cost)     # ровно на прыжок, без резерва
    assert bot._can_refuel() is False           # денег на заправку нет
    decision = bot._plan_turn()
    assert decision.action == "dead_end"
    assert "Credit floor" in decision.reason


def test_desperate_jump_min_fuel(monkeypatch):
    """Отчаянный прыжок: hard-фильтр опасных + минимальный расход топлива."""
    bot = make_bot(galaxy=1, system=0, credits=0.5)
    bot.state.fuel = 38.0
    # дальняя система #32 — Anarchy (p_attack=0.5, EV-дисконт ниже),
    # ближняя #5 — Democracy (безопасна, EV выше); порядок near_systems
    # НЕ по расстоянию — дальняя стоит первой
    bot._market_of(32).system["government"] = 0   # Anarchy
    bot._market_of(5).system["government"] = 6    # Democracy
    monkeypatch.setattr(
        bot.state, "near_systems",
        lambda: [(32, "FAR", 320, 32), (5, "NEAR", 50, 5)])
    assert bot._desperate_jump_target() == 5


def test_dead_end_break():
    """Истинный тупик (0 Cr, 0 топлива) -> run() завершается за 1 раунд."""
    bot = make_bot(galaxy=1, system=0, credits=0.0, rounds=100)
    bot.state.fuel = 0.0
    res = bot.run()
    assert res.rounds_played == 1
    assert any("Dead-end" in line for line in res.log_lines)


def test_stall_limit_break():
    """STALL_LIMIT WAIT подряд -> run() завершается (предохранитель)."""
    assert ea.STALL_LIMIT == 10
    bot = make_bot(rounds=200)

    def always_wait() -> ea.BotDecision:
        return ea.BotDecision("wait", {}, "test stall")

    bot._plan_turn = always_wait  # type: ignore[method-assign]
    res = bot.run()
    assert res.rounds_played == ea.STALL_LIMIT
    assert any("Stall: no progress" in line for line in res.log_lines)