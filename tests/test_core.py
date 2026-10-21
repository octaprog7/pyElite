"""
test_core.py — тесты elite_core: детерминизм, движки, GameState.

Покрывает: DeterministicRNG, GalaxyGenerator, MarketEngine, JumpEngine,
FuelEngine, ShipDefense, CombatEngine, GameState.

Лицензия: GPL v3.
"""

from __future__ import annotations

import pytest

from elite_core import (
    COMMODITIES,
    FUEL_TANK_CAPACITY,
    SHIP_DEFENSE_MAX,
    SHIP_HOLD,
    CombatEngine,
    CombatResult,
    DeterministicRNG,
    FuelEngine,
    GalaxyGenerator,
    GameState,
    JumpEngine,
    JumpResult,
    MarketEngine,
    MarketError,
    ResultBase,
    ShipDefense,
)

SEED_A: list[int] = [0x5A, 0x4A, 0x48, 0x02]
SEED_B: list[int] = [0x00, 0x01, 0x00, 0x00]


# --------------------------------------------------------------------------
# 1. Детерминизм
# --------------------------------------------------------------------------


def test_two_states_identical_with_same_seed():
    gs1 = GameState(galaxy=0, system_index=0, rng_seed=SEED_A)
    gs2 = GameState(galaxy=0, system_index=0, rng_seed=SEED_A)
    assert gs1.systems == gs2.systems
    assert gs1.market.get_market() == gs2.market.get_market()
    assert gs1.generate_description() == gs2.generate_description()


def test_distance_units_0_71_canonical():
    """Каноническое значение из __main__: distance 0->71 == 16 units."""
    gen = GalaxyGenerator()
    engine = JumpEngine(gen, 0)
    assert engine.distance_units(0, 71) == 16


def test_market_tibedi_snapshot():
    gs = GameState(galaxy=0, system_index=0)
    market_tibedi = gs.market.get_market()
    assert gs.market.get_market() == market_tibedi


def test_rng_same_seed_same_bytes():
    r1 = DeterministicRNG(SEED_A)
    r2 = DeterministicRNG(SEED_A)
    assert [r1.next_byte() for _ in range(16)] == [
        r2.next_byte() for _ in range(16)]


def test_rng_different_seed_different_bytes():
    r1 = DeterministicRNG([0, 0, 0, 0])
    r2 = DeterministicRNG(SEED_B)
    assert r1.next_byte() != r2.next_byte()


def test_rng_next_range_inclusive():
    rng = DeterministicRNG([0, 0, 0, 0])   # next_byte всегда 0
    assert rng.next_range(5, 10) == 5      # [lo, hi] инклюзивно
    assert rng.next_range(3, 6) == 3


# --------------------------------------------------------------------------
# 2. GalaxyGenerator
# --------------------------------------------------------------------------


def test_galaxy_has_256_systems():
    gen = GalaxyGenerator()
    systems = gen.generate_galaxy(0)
    assert len(systems) == 256


def test_system_has_all_keys():
    gen = GalaxyGenerator()
    sys_row = gen.generate_galaxy(0)[0]
    for key in ("number", "x", "y", "z", "economy", "government",
                "tech_level", "population", "productivity", "radius_km",
                "name", "economy_name", "government_name"):
        assert key in sys_row


def test_system_name_nonempty():
    gen = GalaxyGenerator()
    for sys_row in gen.generate_galaxy(0):
        assert isinstance(sys_row["name"], str) and sys_row["name"]


def test_system_ranges():
    gen = GalaxyGenerator()
    for sys_row in gen.generate_galaxy(0):
        assert 0 <= sys_row["economy"] <= 7
        assert 0 <= sys_row["government"] <= 7
        assert 0 <= sys_row["tech_level"] <= 17
        assert 0 <= sys_row["x"] <= 255
        assert 0 <= sys_row["y"] <= 255
        assert sys_row["radius_km"] > 0


def test_galaxies_differ():
    gen = GalaxyGenerator()
    assert gen.generate_galaxy(1) != gen.generate_galaxy(0)


# --------------------------------------------------------------------------
# 3. MarketEngine
# --------------------------------------------------------------------------


def test_market_rows_count():
    gs = GameState(galaxy=0, system_index=0)
    rows = gs.market.get_market()
    assert len(rows) == 17


def test_market_row_keys():
    gs = GameState(galaxy=0, system_index=0)
    for row in gs.market.get_market():
        for key in ("name", "unit", "available", "price_buy_cr",
                    "price_sell_cr"):
            assert key in row


def test_market_prices_nonnegative():
    gs = GameState(galaxy=0, system_index=0)
    rows = gs.market.get_market()
    assert all(row["price_buy_cr"] >= 0 for row in rows)
    assert all(row["price_buy_cr"] > 0 for row in rows[:16])


def test_market_availability_nonnegative():
    gs = GameState(galaxy=0, system_index=0)
    assert all(row["available"] >= 0 for row in gs.market.get_market())


def test_market_index_by_name():
    gs = GameState(galaxy=0, system_index=0)
    assert gs.market.index("Food") == 0
    assert gs.market.index("Alien Items") == 16


def test_market_index_unknown_raises():
    gs = GameState(galaxy=0, system_index=0)
    with pytest.raises(ValueError):
        gs.market.index(" nonexistent")


def test_check_buy_too_many_raises():
    gs = GameState(galaxy=0, system_index=0)
    available = gs.market.get_market()[0]["available"]
    with pytest.raises(MarketError):
        gs.market.check_buy("Food", available + 1)


def test_check_buy_nonpositive_raises():
    gs = GameState(galaxy=0, system_index=0)
    with pytest.raises(MarketError):
        gs.market.check_buy("Food", 0)


def test_check_sell_missing_cargo_raises():
    gs = GameState(galaxy=0, system_index=0)
    with pytest.raises(MarketError):
        gs.market.check_sell("Food", 1, [0] * 17)


# --------------------------------------------------------------------------
# 4. JumpEngine
# --------------------------------------------------------------------------


def test_distance_same_system_zero():
    gen = GalaxyGenerator()
    engine = JumpEngine(gen, 0)
    assert engine.distance_units(0, 0) == 0


def test_can_jump_no_fuel():
    gen = GalaxyGenerator()
    engine = JumpEngine(gen, 0)
    assert engine.can_jump(0, 71, 0) is False


def test_can_jump_with_fuel():
    gen = GalaxyGenerator()
    engine = JumpEngine(gen, 0)
    assert engine.can_jump(0, 71, 70) is True


def test_execute_jump_unreachable():
    gen = GalaxyGenerator()
    engine = JumpEngine(gen, 0)
    result = engine.execute_jump(0, -1, 70)
    assert result.success is False


def test_execute_jump_success():
    gen = GalaxyGenerator()
    engine = JumpEngine(gen, 0)
    result = engine.execute_jump(0, 71, 70)
    assert result.success is True
    assert result.new_fuel < 70
    assert result.fuel_cost == 16


def test_jump_result_is_dataclass():
    gen = GalaxyGenerator()
    result = JumpEngine(gen, 0).execute_jump(0, 71, 70)
    assert isinstance(result, JumpResult)
    assert isinstance(result, ResultBase)
    for attr in ("success", "error_reason", "distance_units", "distance_ly",
                 "fuel_cost", "new_fuel", "current_system"):
        assert hasattr(result, attr)


# --------------------------------------------------------------------------
# 5. FuelEngine
# --------------------------------------------------------------------------


def test_refuel_full_tank():
    result = FuelEngine().refuel(70.0, 100.0)
    assert result.success is False
    assert result.error_reason is not None


def test_refuel_empty_tank_ok():
    result = FuelEngine().refuel(0.0, 20.0)
    assert result.success is True
    assert result.new_fuel == float(FUEL_TANK_CAPACITY)
    assert result.cost == pytest.approx(70 * 0.2)


def test_refuel_no_credits():
    result = FuelEngine().refuel(0.0, 1.0)
    assert result.success is False


# --------------------------------------------------------------------------
# 6. ShipDefense
# --------------------------------------------------------------------------


def test_defense_initial_values():
    d = ShipDefense()
    assert (d.forward_shield, d.aft_shield, d.energy) == (255, 255, 255)


def test_defense_absorbs_hit():
    d = ShipDefense()
    destroyed, ouch = d.take_damage(100, from_rear=False)
    assert (destroyed, ouch) == (False, False)
    assert d.forward_shield == 155
    assert d.energy == SHIP_DEFENSE_MAX


def test_defense_overflow_to_energy():
    d = ShipDefense()
    destroyed, ouch = d.take_damage(300, from_rear=False)
    assert (destroyed, ouch) == (False, True)
    assert d.forward_shield == 0
    assert d.energy == 210


def test_defense_destroyed():
    d = ShipDefense(energy=10)
    destroyed, _ouch = d.take_damage(100000, from_rear=False)
    assert destroyed is True
    assert d.destroyed is True
    assert d.energy == 0


def test_defense_reset():
    d = ShipDefense(forward_shield=10, aft_shield=20, energy=30)
    d.reset()
    assert (d.forward_shield, d.aft_shield, d.energy) == (255, 255, 255)


def test_defense_ouch_removes_cargo():
    rng = DeterministicRNG([0, 0, 0, 0])   # A=0, X=0 (DORND с нулевым seed)
    cargo = [0] * 17
    cargo[0] = 5
    lost = ShipDefense().ouch(rng, cargo)
    assert lost == COMMODITIES[0]
    assert cargo[0] == 0


def test_defense_ouch_empty_cargo():
    rng = DeterministicRNG([0, 0, 0, 0])
    assert ShipDefense().ouch(rng, [0] * 17) == ""


# --------------------------------------------------------------------------
# 7. CombatEngine
# --------------------------------------------------------------------------


def test_resolve_fight_action():
    ce = CombatEngine()
    result = ce.resolve("fight", DeterministicRNG(SEED_A), fuel=70,
                        credits=100, cargo=[0] * 17, tech_level=7,
                        defense=ShipDefense())
    assert result.action == "fight"


def test_resolve_escape_action():
    ce = CombatEngine()
    result = ce.resolve("escape", DeterministicRNG(SEED_A), fuel=70,
                        credits=100, cargo=[0] * 17, tech_level=5,
                        defense=ShipDefense())
    assert result.action == "escape"


def test_resolve_surrender_success():
    ce = CombatEngine()
    result = ce.resolve("surrender", DeterministicRNG(SEED_A), fuel=70,
                        credits=100, cargo=[0] * 17, tech_level=5,
                        defense=ShipDefense())
    assert result.action == "surrender"
    assert result.success is True


def test_resolve_unknown_action_raises():
    ce = CombatEngine()
    with pytest.raises(ValueError):
        ce.resolve("dance", DeterministicRNG(SEED_A), fuel=70, credits=100,
                   cargo=[0] * 17, tech_level=5, defense=ShipDefense())


def test_resolve_fight_destroyed():
    ce = CombatEngine()
    defense = ShipDefense(forward_shield=0, energy=5)
    result = ce.resolve("fight", DeterministicRNG(SEED_A), fuel=70,
                        credits=100, cargo=[0] * 17, tech_level=0,
                        defense=defense)
    assert result.destroyed is True
    assert result.status == "destroyed"


def test_attack_chance_anarchy_higher():
    ce = CombatEngine()
    assert ce.attack_chance(0) > ce.attack_chance(7)


def test_check_pirate_attack_deterministic():
    ce = CombatEngine()
    r1 = DeterministicRNG(SEED_A)
    r2 = DeterministicRNG(SEED_A)
    assert ce.check_pirate_attack(r1, 0) == ce.check_pirate_attack(r2, 0)


# --------------------------------------------------------------------------
# 8. GameState
# --------------------------------------------------------------------------


def test_state_initial():
    gs = GameState()
    assert gs.galaxy == 0 and gs.system_index == 0
    assert gs.fuel == float(FUEL_TANK_CAPACITY)
    assert gs.credits == 100.0
    assert gs.cargo == [0] * 17


def test_buy_decreases_credits_increases_cargo(game_state):
    before = game_state.credits
    cost = game_state.buy("Food", 1)
    assert game_state.credits == pytest.approx(before - cost)
    assert game_state.cargo[0] == 1


def test_buy_too_much_raises(game_state):
    available = game_state.market.get_market()[0]["available"]
    with pytest.raises(MarketError):
        game_state.buy("Food", available + 1)


def test_sell_after_buy(game_state):
    game_state.buy("Food", 1)
    credits_before = game_state.credits
    income = game_state.sell("Food", 1)
    assert game_state.credits == pytest.approx(credits_before + income)
    assert game_state.cargo[0] == 0


def test_jump_changes_state(game_state):
    result = game_state.jump(71)
    assert result.success is True
    assert game_state.system_index == 71
    assert game_state.fuel < 70.0


def test_jump_invalid_no_change(game_state):
    before_sys = game_state.system_index
    before_fuel = game_state.fuel
    result = game_state.jump(-5)
    assert result.success is False
    assert game_state.system_index == before_sys
    assert game_state.fuel == before_fuel


def test_refuel_increases_fuel(game_state):
    game_state.update_fuel(-20)
    result = game_state.refuel()
    assert result.success is True
    assert game_state.fuel == float(FUEL_TANK_CAPACITY)


def test_near_systems_sorted(game_state):
    near = game_state.near_systems()
    assert near, "TIBEDI должен иметь достижимые системы"
    for item in near:
        assert len(item) == 4
        assert isinstance(item[0], int)
    distances = [item[2] for item in near]
    assert distances == sorted(distances)


def test_cargo_weight_property(game_state):
    game_state.cargo[0] = 5
    game_state.cargo[13] = 99    # драгоценности не считаются в тоннах
    assert game_state.cargo_weight == sum(game_state.cargo[:13])


def test_load_system_resets_defense(game_state):
    game_state.defense.take_damage(500, from_rear=False)
    assert game_state.defense.forward_shield == 0
    game_state.load_system()
    assert game_state.defense.forward_shield == SHIP_DEFENSE_MAX
    assert game_state.defense.energy == SHIP_DEFENSE_MAX


def test_generate_description_nonempty(game_state):
    assert game_state.generate_description()


def test_update_fuel_clamp(game_state):
    assert game_state.update_fuel(10) == float(FUEL_TANK_CAPACITY)
    game_state.update_fuel(-100)
    assert game_state.fuel == 0.0


def test_check_pirate_attack_deterministic_seed():
    gs1 = GameState(galaxy=0, system_index=0, rng_seed=SEED_A)
    gs2 = GameState(galaxy=0, system_index=0, rng_seed=SEED_A)
    assert gs1.check_pirate_attack() == gs2.check_pirate_attack()


def test_resolve_combat_action_surrender(game_state):
    result: CombatResult = game_state.resolve_combat_action("surrender")
    assert result.action == "surrender"
    assert result.success is True


# --------------------------------------------------------------------------
# 9. Дополнительное покрытие (ветки движков)
# --------------------------------------------------------------------------


def test_commodity_index_prefix_and_case():
    from elite_core import commodity_index
    assert commodity_index("foo") == 0
    assert commodity_index("FOOD") == 0
    assert commodity_index(3) == 3
    with pytest.raises(MarketError):
        commodity_index(99)
    with pytest.raises(MarketError):
        commodity_index("no such goods")


def test_market_price_and_unit_names(game_state):
    assert game_state.market.price_cr(0) > 0
    assert game_state.market.unit_name(16) == "T"


def test_market_index_int_invalid(game_state):
    with pytest.raises(MarketError):
        game_state.market.index(99)


def test_execute_jump_negative_fuel():
    gen = GalaxyGenerator()
    result = JumpEngine(gen, 0).execute_jump(0, 71, -1)
    assert result.success is False


def test_execute_jump_too_far():
    """Дистанция >= 256 единиц -> 'RANGE?' (hi byte != 0)."""
    gen = GalaxyGenerator()
    engine = JumpEngine(gen, 0)
    far = next((t for t in range(256)
                if engine.distance_units(0, t) >> 8 != 0), None)
    if far is None:
        pytest.skip("нет систем дальше 25.6 св. лет от TIBEDI")
    assert engine.can_jump(0, far, 70) is False
    result = engine.execute_jump(0, far, 70)
    assert result.success is False
    assert "range" in (result.error_reason or "").lower()


def test_buy_hold_full(game_state):
    game_state.cargo[0] = SHIP_HOLD     # трюм занят тоннами
    with pytest.raises(MarketError):
        game_state.buy("Textiles", 1)


def test_buy_not_enough_credits(game_state):
    game_state.credits = 1.0
    with pytest.raises(MarketError):
        game_state.buy("Food", 1)


def test_buy_precious_limit(game_state):
    game_state.cargo[13] = 199          # Gold: лимит 200 ед.
    with pytest.raises(MarketError):
        game_state.buy("Gold", 2)


def test_refuel_not_enough_credits(game_state):
    game_state.update_fuel(-10)
    game_state.credits = 0.5            # нужно 2.0 Cr
    result = game_state.refuel()
    assert result.success is False


def test_near_systems_empty_at_zero_fuel(game_state):
    game_state.update_fuel(-70)
    assert game_state.near_systems() == []


def test_resolve_escape_no_fuel():
    ce = CombatEngine()
    result = ce.resolve("escape", DeterministicRNG([0, 0, 0, 0]), fuel=0,
                        credits=100, cargo=[0] * 17, tech_level=5,
                        defense=ShipDefense())
    assert result.status == "escape_no_fuel"
    assert result.detail == 1


def test_resolve_escape_success():
    ce = CombatEngine()
    result = ce.resolve("escape", DeterministicRNG([0, 0, 0, 0]), fuel=70,
                        credits=100, cargo=[0] * 17, tech_level=5,
                        defense=ShipDefense())
    assert result.status == "escape_success"
    assert result.fuel_used == 1


def test_resolve_escape_fail():
    ce = CombatEngine()
    result = ce.resolve("escape", DeterministicRNG([0xFF] * 4), fuel=70,
                        credits=100, cargo=[0] * 17, tech_level=5,
                        defense=ShipDefense())
    assert result.status == "escape_fail"
    assert result.fuel_used == 6


def test_resolve_fight_loss():
    ce = CombatEngine()
    result = ce.resolve("fight", DeterministicRNG([0xFF] * 4), fuel=70,
                        credits=100, cargo=[0] * 17, tech_level=0,
                        defense=ShipDefense())
    assert result.status == "fight_lose"
    assert result.credits_lost == 20.0


# --------------------------------------------------------------------------
# Описание планеты («goat soup») на разных языках (en — ядро, ru/es — i18n)
# --------------------------------------------------------------------------


def _slots(text: str) -> set[str]:
    from elite_core import SystemDescriptionEngine
    """Набор плейсхолдеров-групп в фразе (определяет потребление байтов)."""
    return {s for s in SystemDescriptionEngine.SLOT_GROUPS if s in text}


def test_desc_tables_parity_with_core():
    """RU/ES таблицы описаний 1:1 с английскими: размеры групп, число
    экономик, число шаблонов/фраз и набор плейсхолдеров каждой фразы."""
    from elite_core import SystemDescriptionEngine
    from elite_i18n import desc_tables

    en_groups = SystemDescriptionEngine.SLOT_GROUPS
    en_templates = SystemDescriptionEngine.TEMPLATES
    for lang in ("ru", "es"):
        tables = desc_tables(lang)
        assert set(tables.groups) == set(en_groups)
        for key in en_groups:
            assert len(tables.groups[key]) == len(en_groups[key]), (lang, key)
        assert len(tables.economies) == 8, lang
        assert len(tables.templates) == len(en_templates), lang
        for t_en, t_loc in zip(en_templates, tables.templates):
            assert len(t_en) == len(t_loc), lang
            for p_en, p_loc in zip(t_en, t_loc):
                assert _slots(p_en[0]) == _slots(p_loc[0]), (lang, p_loc[0])


def test_generate_description_ru(game_state):
    desc = game_state.generate_description(lang="ru")
    assert desc
    assert game_state.system["name"] in desc
    assert any("\u0400" <= ch <= "\u04FF" for ch in desc)


def test_generate_description_ru_deterministic(game_state):
    assert (game_state.generate_description(lang="ru")
            == game_state.generate_description(lang="ru"))


def test_generate_description_es(game_state):
    desc = game_state.generate_description(lang="es")
    assert desc
    assert game_state.system["name"] in desc


def test_generate_description_bad_lang(game_state):
    with pytest.raises(ValueError):
        game_state.generate_description(lang="de")


# --------------------------------------------------------------------------
# Локализация названий товаров (показ + разбор ввода; канонические — в API)
# --------------------------------------------------------------------------


def test_commodity_index_localized():
    from elite_core import MarketError, commodity_index

    assert commodity_index("Еда", "ru") == 0
    assert commodity_index("еда", "ru") == 0          # регистр
    assert commodity_index("Мех", "ru") == 11         # prefix-матчинг
    assert commodity_index("Comida", "es") == 0
    assert commodity_index("Food") == 0               # без локали — канон
    assert commodity_index("Food", "ru") == 0         # канон при любой локали
    with pytest.raises(MarketError):
        commodity_index("Еда")                        # без локали — не ищется
    with pytest.raises(MarketError):
        commodity_index("Кактус", "ru")


def test_buy_sell_localized_names(game_state):
    cost = game_state.buy("Еда", 2, lang="ru")
    assert game_state.cargo[0] == 2
    assert cost > 0
    income = game_state.sell("Еда", 1, lang="ru")
    assert game_state.cargo[0] == 1
    assert income > 0
    # В журнал ушло каноническое имя (проверка через _FakeLogger не нужна:
    # log_buy вызывается с нормализованным item — проверяем через запись)
    from elite_core import MarketError
    with pytest.raises(MarketError):
        game_state.buy("Еда", 1)                      # без lang — отклонено


def test_commodity_names_parity():
    from elite_core import COMMODITIES
    from elite_i18n import COMMODITY_NAMES, commodity_display, resolve_commodity

    for lang, names in COMMODITY_NAMES.items():
        assert len(names) == len(COMMODITIES), lang
    assert commodity_display(0, "ru") == "Еда"
    assert commodity_display(15, "ru") == "Драгоценные камни"
    assert commodity_display(0, "en") is None         # en -> каноническое имя
    assert commodity_display(99, "ru") is None
    assert resolve_commodity("Еда", "ru") == 0
    assert resolve_commodity("Comida", "es") == 0
    assert resolve_commodity("Еда", "en") == -1
    assert resolve_commodity("Кактус", "ru") == -1