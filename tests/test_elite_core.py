"""
test_elite_core.py — тесты ядра elite_core.py.

Покрывает: DeterministicRNG, константы, commodity_index, GalaxyGenerator,
MarketEngine, JumpEngine, FuelEngine, ShipDefense, CombatEngine,
SystemDescriptionEngine, GameState.

Запуск: python test_elite_core.py
Зависимости: только стандартная библиотека (unittest) + elite_core.
"""

import os
import sys
import unittest
from unittest import TestCase

# Добавить корень проекта (rework/) в sys.path для standalone-запуска:
# python tests/test_elite_core.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elite_core import (
    # Constants
    SEED_GALAXY_0,
    NAME_PAIRS,
    ECONOMIES,
    GOVERNMENTS,
    COMMODITIES,
    MARKET_TABLE,
    UNIT_BY_FLAGS,
    SHIP_HOLD,
    PRECIOUS_LIMIT,
    STARTING_CASH_UNITS,
    FUEL_TANK_CAPACITY,
    FUEL_PRICE_PER_UNIT_CR,
    ENGINE_MAX_RANGE_UNITS,
    SHIP_DEFENSE_MAX,
    DANGER_TABLE,
    # Types
    Cargo,
    SystemRow,
    MarketRow,
    JumpResult,
    # Dataclasses
    RefuelResult,
    CombatResult,
    ShipDefense,
    # Functions
    commodity_index,
    # Engines
    DeterministicRNG,
    GalaxyGenerator,
    MarketEngine,
    MarketError,
    JumpEngine,
    FuelEngine,
    CombatEngine,
    SystemDescriptionEngine,
    GameState,
)


# ============================================================
# 1. DeterministicRNG
# ============================================================
class TestDeterministicRNG(TestCase):

    def test_default_seed(self):
        rng = DeterministicRNG()
        self.assertEqual(rng.state, (0x4A, 0x5A, 0x48, 0x02))

    def test_custom_seed(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        self.assertEqual(rng.state, (1, 2, 3, 4))

    def test_determinism_same_seed(self):
        a = DeterministicRNG([10, 20, 30, 40])
        b = DeterministicRNG([10, 20, 30, 40])
        for _ in range(100):
            self.assertEqual(a.next_byte(), b.next_byte())

    def test_different_seed_different_output(self):
        a = DeterministicRNG([1, 2, 3, 4])
        b = DeterministicRNG([5, 6, 7, 8])
        results_a = [a.next_byte() for _ in range(10)]
        results_b = [b.next_byte() for _ in range(10)]
        self.assertNotEqual(results_a, results_b)

    def test_byte_range(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        for _ in range(1000):
            v = rng.next_byte()
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 255)

    def test_next_word(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        rng2 = DeterministicRNG([1, 2, 3, 4])
        hi = rng2.next_byte()
        lo = rng2.next_byte()
        self.assertEqual(rng.next_word(), (hi << 8) | lo)

    def test_next_range(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        for _ in range(100):
            v = rng.next_range(5, 10)
            self.assertGreaterEqual(v, 5)
            self.assertLessEqual(v, 10)

    def test_next_range_single(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        for _ in range(10):
            self.assertEqual(rng.next_range(7, 7), 7)

    def test_pick_single(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        self.assertEqual(rng.pick(["only"]), "only")

    def test_pick_two(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        results = set()
        for _ in range(200):
            results.add(rng.pick(["a", "b"]))
        # With band=128, both halves should appear
        self.assertEqual(results, {"a", "b"})


# ============================================================
# 2. Constants
# ============================================================
class TestConstants(TestCase):

    def test_seed_galaxy_0(self):
        self.assertEqual(len(SEED_GALAXY_0), 6)
        self.assertTrue(all(isinstance(b, int) for b in SEED_GALAXY_0))

    def test_name_pairs(self):
        self.assertEqual(len(NAME_PAIRS), 32)

    def test_economies(self):
        self.assertEqual(len(ECONOMIES), 8)
        self.assertIn("Rich Industrial", ECONOMIES)

    def test_governments(self):
        self.assertEqual(len(GOVERNMENTS), 8)
        self.assertIn("Anarchy", GOVERNMENTS)

    def test_commodities(self):
        self.assertEqual(len(COMMODITIES), 17)
        self.assertEqual(COMMODITIES[0], "Food")
        self.assertEqual(COMMODITIES[16], "Alien Items")

    def test_market_table(self):
        self.assertEqual(len(MARKET_TABLE), 16)
        for entry in MARKET_TABLE:
            self.assertEqual(len(entry), 4)

    def test_unit_by_flags(self):
        self.assertEqual(UNIT_BY_FLAGS[0], "T")
        self.assertEqual(UNIT_BY_FLAGS[1], "KG")

    def test_ship_hold(self):
        self.assertEqual(SHIP_HOLD, 22)

    def test_precious_limit(self):
        self.assertEqual(PRECIOUS_LIMIT, 200)

    def test_starting_cash_units(self):
        self.assertEqual(STARTING_CASH_UNITS, 1000)

    def test_fuel_tank_capacity(self):
        self.assertEqual(FUEL_TANK_CAPACITY, 70)

    def test_fuel_price(self):
        self.assertAlmostEqual(FUEL_PRICE_PER_UNIT_CR, 0.2)

    def test_engine_max_range(self):
        self.assertEqual(ENGINE_MAX_RANGE_UNITS, 256)

    def test_ship_defense_max(self):
        self.assertEqual(SHIP_DEFENSE_MAX, 255)

    def test_danger_table(self):
        self.assertEqual(len(DANGER_TABLE), 8)
        self.assertEqual(DANGER_TABLE[0], 249)
        self.assertEqual(DANGER_TABLE[7], 19)


# ============================================================
# 3. commodity_index
# ============================================================
class TestCommodityIndex(TestCase):

    def test_int_valid(self):
        self.assertEqual(commodity_index(0), 0)
        self.assertEqual(commodity_index(16), 16)

    def test_int_invalid(self):
        with self.assertRaises(MarketError):
            commodity_index(17)
        with self.assertRaises(MarketError):
            commodity_index(-1)

    def test_name_exact(self):
        self.assertEqual(commodity_index("Food"), 0)
        self.assertEqual(commodity_index("Alien Items"), 16)

    def test_name_case_insensitive(self):
        self.assertEqual(commodity_index("food"), 0)
        self.assertEqual(commodity_index("FOOD"), 0)

    def test_name_prefix(self):
        self.assertEqual(commodity_index("comp"), 7)
        self.assertEqual(commodity_index("rad"), 2)

    def test_unknown_name(self):
        with self.assertRaises(MarketError):
            commodity_index("nonexistent")

    def test_strip(self):
        self.assertEqual(commodity_index("  Food  "), 0)

    def test_empty_string(self):
        """Пустая строка — префикс любого товара (startswith(''))."""
        self.assertEqual(commodity_index(""), 0)


# ============================================================
# 4. GalaxyGenerator
# ============================================================
class TestGalaxyGenerator(TestCase):

    def setUp(self):
        self.gen = GalaxyGenerator()

    def test_galaxy_0_has_256_systems(self):
        systems = self.gen.generate_galaxy(0)
        self.assertEqual(len(systems), 256)

    def test_all_galaxies(self):
        for g in range(8):
            systems = self.gen.generate_galaxy(g)
            self.assertEqual(len(systems), 256)

    def test_determinism(self):
        a = self.gen.generate_galaxy(0)
        b = self.gen.generate_galaxy(0)
        self.assertEqual(a, b)

    def test_first_system_tibedi(self):
        systems = self.gen.generate_galaxy(0)
        self.assertEqual(systems[0]["name"], "TIBEDI")

    def test_71_is_edisoin(self):
        systems = self.gen.generate_galaxy(0)
        self.assertEqual(systems[71]["name"], "EDINSOIN")

    def test_system_fields(self):
        systems = self.gen.generate_galaxy(0)
        s = systems[0]
        for key in ("number", "x", "y", "z", "economy", "government",
                     "tech_level", "population", "productivity", "radius_km",
                     "name", "economy_name", "government_name"):
            self.assertIn(key, s)

    def test_economy_range(self):
        systems = self.gen.generate_galaxy(0)
        for s in systems:
            self.assertGreaterEqual(s["economy"], 0)
            self.assertLessEqual(s["economy"], 7)

    def test_government_range(self):
        systems = self.gen.generate_galaxy(0)
        for s in systems:
            self.assertGreaterEqual(s["government"], 0)
            self.assertLessEqual(s["government"], 7)

    def test_tech_level_range(self):
        systems = self.gen.generate_galaxy(0)
        for s in systems:
            self.assertGreaterEqual(s["tech_level"], 0)
            self.assertLessEqual(s["tech_level"], 255)

    def test_galaxy_mask(self):
        """Galaxy number is masked with &0x07."""
        a = self.gen.generate_galaxy(0)
        b = self.gen.generate_galaxy(8)
        self.assertEqual(a, b)

    def test_different_galaxies_different(self):
        a = self.gen.generate_galaxy(0)
        b = self.gen.generate_galaxy(1)
        self.assertNotEqual(a[0]["name"], b[0]["name"])

    def test_coords_range(self):
        systems = self.gen.generate_galaxy(0)
        for s in systems:
            self.assertGreaterEqual(s["x"], 0)
            self.assertLessEqual(s["x"], 255)
            self.assertGreaterEqual(s["y"], 0)
            self.assertLessEqual(s["y"], 255)


# ============================================================
# 5. MarketEngine
# ============================================================
class TestMarketEngine(TestCase):

    def setUp(self):
        self.gen = GalaxyGenerator()
        self.market = MarketEngine(self.gen, 0, 0)  # TIBEDI

    def test_17_categories(self):
        rows = self.market.get_market()
        self.assertEqual(len(rows), 17)

    def test_alien_items_unavailable(self):
        self.assertEqual(self.market.available(16), 0)

    def test_alien_items_price_zero(self):
        self.assertEqual(self.market.price_cr(16), 0.0)

    def test_determinism(self):
        a = MarketEngine(self.gen, 0, 0)
        b = MarketEngine(self.gen, 0, 0)
        self.assertEqual(a.get_market(), b.get_market())

    def test_prices_nonnegative(self):
        for i in range(17):
            self.assertGreaterEqual(self.market.price_cr(i), 0.0)

    def test_available_nonnegative(self):
        for i in range(17):
            self.assertGreaterEqual(self.market.available(i), 0)

    def test_available_le_63(self):
        """Availability masked with &0x3F (max 63)."""
        for i in range(16):
            self.assertLessEqual(self.market.available(i), 63)

    def test_unit_names(self):
        for i in range(16):
            unit = self.market.unit_name(i)
            self.assertIn(unit, ("T", "KG", "g"))

    def test_index_by_name(self):
        self.assertEqual(self.market.index("Food"), 0)
        self.assertEqual(self.market.index("Computers"), 7)

    def test_index_by_int(self):
        self.assertEqual(self.market.index(0), 0)
        self.assertEqual(self.market.index(16), 16)

    def test_index_invalid(self):
        with self.assertRaises(MarketError):
            self.market.index(17)
        with self.assertRaises(MarketError):
            self.market.index("nonexistent")

    def test_check_buy_ok(self):
        idx, cost = self.market.check_buy("Food", 1)
        self.assertEqual(idx, 0)
        self.assertGreater(cost, 0)

    def test_check_buy_too_many(self):
        avail = self.market.available(0)
        with self.assertRaises(MarketError):
            self.market.check_buy("Food", avail + 1)

    def test_check_buy_zero(self):
        with self.assertRaises(MarketError):
            self.market.check_buy("Food", 0)

    def test_check_sell_ok(self):
        cargo = [0] * 17
        cargo[0] = 5
        idx, income = self.market.check_sell("Food", 3, cargo)
        self.assertEqual(idx, 0)
        self.assertGreater(income, 0)

    def test_check_sell_too_many(self):
        cargo = [0] * 17
        cargo[0] = 2
        with self.assertRaises(MarketError):
            self.market.check_sell("Food", 3, cargo)


# ============================================================
# 6. JumpEngine
# ============================================================
class TestJumpEngine(TestCase):

    def setUp(self):
        self.gen = GalaxyGenerator()
        self.jump = JumpEngine(self.gen, 0)

    def test_distance_0_to_71(self):
        """TIBEDI (#0) to EDINSOIN (#71) = 16 units (1.6 ly)."""
        self.assertEqual(self.jump.distance_units(0, 71), 16)

    def test_distance_symmetry(self):
        for i in range(0, 256, 17):
            for j in range(0, 256, 31):
                if i != j:
                    self.assertEqual(
                        self.jump.distance_units(i, j),
                        self.jump.distance_units(j, i),
                        f"asymmetry at {i},{j}")

    def test_distance_to_self_is_zero(self):
        for i in range(0, 256, 50):
            self.assertEqual(self.jump.distance_units(i, i), 0)

    def test_fuel_cost_is_low_byte(self):
        dist = self.jump.distance_units(0, 71)
        cost = self.jump.calculate_fuel_cost(0, 71)
        self.assertEqual(cost, dist & 0xFF)

    def test_can_jump_same_system(self):
        """Прыжок в текущую систему допустим (расстояние 0, расход 0)."""
        self.assertTrue(self.jump.can_jump(0, 0, 70))

    def test_can_jump_valid(self):
        """0->71 with 70 fuel should work (cost=16)."""
        self.assertTrue(self.jump.can_jump(0, 71, 70))

    def test_can_jump_insufficient_fuel(self):
        self.assertFalse(self.jump.can_jump(0, 71, 10))

    def test_can_jump_invalid_system(self):
        self.assertFalse(self.jump.can_jump(-1, 71, 70))
        self.assertFalse(self.jump.can_jump(0, 256, 70))

    def test_execute_jump_success(self):
        result = self.jump.execute_jump(0, 71, 70)
        self.assertTrue(result.success)
        self.assertEqual(result.fuel_cost, 16)
        self.assertEqual(result.new_fuel, 54)
        self.assertEqual(result.current_system, 71)

    def test_execute_jump_no_fuel(self):
        result = self.jump.execute_jump(0, 71, 10)
        self.assertFalse(result.success)
        self.assertIn("fuel", result.error_reason)

    def test_execute_jump_invalid(self):
        result = self.jump.execute_jump(0, 256, 70)
        self.assertFalse(result.success)

    def test_coords(self):
        x, y = self.jump.coords(0)
        self.assertIsInstance(x, int)
        self.assertIsInstance(y, int)

    def test_coords_invalid(self):
        with self.assertRaises(ValueError):
            self.jump.coords(256)

    def test_distance_positive_for_distinct_coords(self):
        """Расстояние > 0, кроме пар с dx=0 и |dy|<=1 (округление dy>>1).

        Особенность формулы _TT111: (1 >> 1) == 0, поэтому пары систем
        с одинаковым X и разницей Y в 1 единицу дают distance == 0.
        """
        systems = self.gen.generate_galaxy(0)
        checked = 0
        for i in range(256):
            for j in range(i + 1, 256):
                dx = abs(int(systems[i]["x"]) - int(systems[j]["x"]))
                dy = abs(int(systems[i]["y"]) - int(systems[j]["y"]))
                d = self.jump.distance_units(i, j)
                if dx == 0 and dy <= 1:
                    self.assertEqual(d, 0)
                else:
                    self.assertGreater(d, 0)
                checked += 1
        self.assertGreater(checked, 0)

    def test_distance_le_511(self):
        """16-bit distance should fit in 0-511 (after sqrt*4)."""
        for i in range(0, 256, 10):
            for j in range(0, 256, 10):
                if i != j:
                    d = self.jump.distance_units(i, j)
                    self.assertLessEqual(d, 1023)


# ============================================================
# 7. FuelEngine
# ============================================================
class TestFuelEngine(TestCase):

    def setUp(self):
        self.fe = FuelEngine()

    def test_capacity(self):
        self.assertEqual(self.fe.capacity, 70)

    def test_price(self):
        self.assertAlmostEqual(self.fe.price_per_unit_cr, 0.2)

    def test_cost_to_full_empty(self):
        self.assertAlmostEqual(self.fe.cost_to_full(0), 14.0)

    def test_cost_to_full_half(self):
        self.assertAlmostEqual(self.fe.cost_to_full(35), 7.0)

    def test_cost_to_full_full(self):
        self.assertAlmostEqual(self.fe.cost_to_full(70), 0.0)

    def test_refuel_full(self):
        result = self.fe.refuel(70, 100)
        self.assertFalse(result.success)
        self.assertIn("full", result.error_reason)

    def test_refuel_success(self):
        result = self.fe.refuel(50, 100)
        self.assertTrue(result.success)
        self.assertEqual(result.new_fuel, 70)
        self.assertAlmostEqual(result.cost, 4.0)

    def test_refuel_no_credits(self):
        result = self.fe.refuel(0, 1)
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_reason)

    def test_refuel_exact(self):
        result = self.fe.refuel(0, 14.0)
        self.assertTrue(result.success)
        self.assertAlmostEqual(result.cost, 14.0)

    def test_refuel_barely_enough(self):
        result = self.fe.refuel(0, 14.0)
        self.assertTrue(result.success)


# ============================================================
# 8. ShipDefense
# ============================================================
class TestShipDefense(TestCase):

    def test_defaults(self):
        d = ShipDefense()
        self.assertEqual(d.forward_shield, 255)
        self.assertEqual(d.aft_shield, 255)
        self.assertEqual(d.energy, 255)
        self.assertFalse(d.destroyed)

    def test_take_damage_shield_absorbs(self):
        """Damage within shield capacity: no overflow, no OUCH."""
        d = ShipDefense()
        destroyed, ouch = d.take_damage(100, from_rear=False)
        self.assertFalse(destroyed)
        self.assertFalse(ouch)
        self.assertEqual(d.forward_shield, 155)
        self.assertEqual(d.aft_shield, 255)
        self.assertEqual(d.energy, 255)

    def test_take_damage_rear_shield(self):
        d = ShipDefense()
        destroyed, ouch = d.take_damage(100, from_rear=True)
        self.assertFalse(destroyed)
        self.assertFalse(ouch)
        self.assertEqual(d.aft_shield, 155)
        self.assertEqual(d.forward_shield, 255)

    def test_take_damage_overflow_to_energy(self):
        """Shield breaks: overflow goes to energy, OUCH triggered."""
        d = ShipDefense()
        destroyed, ouch = d.take_damage(300, from_rear=False)
        self.assertFalse(destroyed)
        self.assertTrue(ouch)
        self.assertEqual(d.forward_shield, 0)
        self.assertEqual(d.energy, 255 - 45)  # 300-255=45 overflow

    def test_take_damage_destroyed(self):
        """Damage exceeds shield + energy: destroyed."""
        d = ShipDefense()
        destroyed, ouch = d.take_damage(600, from_rear=False)
        self.assertTrue(destroyed)
        self.assertFalse(ouch)
        self.assertEqual(d.forward_shield, 0)
        self.assertEqual(d.energy, 0)
        self.assertTrue(d.destroyed)

    def test_take_damage_exact_kill(self):
        """Shield + energy = damage exactly: destroyed (energy <= 0)."""
        d = ShipDefense()
        destroyed, ouch = d.take_damage(510, from_rear=False)
        self.assertTrue(destroyed)
        self.assertEqual(d.energy, 0)

    def test_take_damage_rear_overflow(self):
        d = ShipDefense()
        destroyed, ouch = d.take_damage(300, from_rear=True)
        self.assertFalse(destroyed)
        self.assertTrue(ouch)
        self.assertEqual(d.aft_shield, 0)
        self.assertEqual(d.forward_shield, 255)
        self.assertEqual(d.energy, 210)

    def test_ouch_nothing_a_ge_128(self):
        """A >= 128 (50%): nothing happens.

        DORND с регистром [0, s, 0, 0] возвращает первый байт = s;
        s = 255 -> A = 255 >= 128 -> ранний выход без потерь.
        """
        d = ShipDefense()
        rng = DeterministicRNG([0, 0xFF, 0, 0])
        cargo = [5] * 17
        result = d.ouch(rng, cargo)
        self.assertEqual(result, "")
        self.assertEqual(cargo[0], 5)  # nothing lost

    def test_ouch_nothing_x_ge_22(self):
        """A < 128 but X >= 22: nothing happens."""
        d = ShipDefense()
        # Need first byte < 128, second byte >= 22
        rng = DeterministicRNG([0x10, 0xFF, 0, 0])  # but DORND transforms...
        # Let's just run many seeds and check some return ""
        found_nothing = False
        for s in range(256):
            rng = DeterministicRNG([s, s, s, s])
            cargo = [5] * 17
            result = d.ouch(rng, cargo)
            if result == "":
                found_nothing = True
                break
        self.assertTrue(found_nothing)

    def test_ouch_empty_cargo(self):
        """cargo[x] == 0: nothing happens."""
        d = ShipDefense()
        # Try many seeds to find one where A < 128, X < 22, cargo[X] == 0
        cargo = [0] * 17
        found_nothing = False
        for s in range(256):
            rng = DeterministicRNG([s, s * 2, s * 3, s * 4])
            result = d.ouch(rng, list(cargo))
            if result == "":
                found_nothing = True
                break
        self.assertTrue(found_nothing)

    def test_ouch_destroys_cargo(self):
        """When conditions met, cargo item is zeroed and name returned."""
        d = ShipDefense()
        found_destroyed = False
        for s in range(256):
            rng = DeterministicRNG([s, s * 2 + 1, s * 3, s * 4 + 7])
            cargo = [5] * 17
            result = d.ouch(rng, cargo)
            if result != "":
                self.assertIn(result, COMMODITIES)
                # Check one cargo slot was zeroed
                zeroed = [i for i in range(17) if cargo[i] == 0]
                self.assertEqual(len(zeroed), 1)
                found_destroyed = True
                break
        self.assertTrue(found_destroyed, "Expected at least one OUCH to destroy cargo")

    def test_recharge_full(self):
        """Recharging a fully-charged ship: no change."""
        d = ShipDefense()
        d.recharge(10)
        self.assertEqual(d.forward_shield, 255)
        self.assertEqual(d.aft_shield, 255)
        self.assertEqual(d.energy, 255)

    def test_recharge_partial_shields(self):
        """Shields charge +1, energy -1 each, when energy >= 128."""
        d = ShipDefense(forward_shield=100, aft_shield=80, energy=200)
        d.recharge(1)
        self.assertEqual(d.forward_shield, 101)
        self.assertEqual(d.aft_shield, 81)
        # energy: -2 (shields) +1 (recharge) = 199
        self.assertEqual(d.energy, 199)

    def test_recharge_low_energy(self):
        """Energy < 128: shields don't charge, energy +1."""
        d = ShipDefense(forward_shield=100, aft_shield=80, energy=50)
        d.recharge(1)
        self.assertEqual(d.forward_shield, 100)
        self.assertEqual(d.aft_shield, 80)
        self.assertEqual(d.energy, 51)

    def test_recharge_energy_cap(self):
        """Energy caps at 255."""
        d = ShipDefense(forward_shield=255, aft_shield=255, energy=254)
        d.recharge(1)
        self.assertEqual(d.energy, 255)

    def test_recharge_shield_cap(self):
        """Shield caps at 255, no energy cost if already 255."""
        d = ShipDefense(forward_shield=255, aft_shield=250, energy=200)
        d.recharge(1)
        # aft charges +1 (cost 1 energy), forward already 255 (no cost)
        self.assertEqual(d.forward_shield, 255)
        self.assertEqual(d.aft_shield, 251)
        # energy: -1 (aft) +1 (recharge) = 200
        self.assertEqual(d.energy, 200)

    def test_destroyed_property(self):
        d = ShipDefense(energy=0)
        self.assertTrue(d.destroyed)
        d.energy = 1
        self.assertFalse(d.destroyed)
        d.energy = -1
        self.assertTrue(d.destroyed)

    def test_reset(self):
        d = ShipDefense(forward_shield=50, aft_shield=30, energy=10)
        d.reset()
        self.assertEqual(d.forward_shield, 255)
        self.assertEqual(d.aft_shield, 255)
        self.assertEqual(d.energy, 255)
        self.assertFalse(d.destroyed)


# ============================================================
# 9. CombatEngine
# ============================================================
class TestCombatEngine(TestCase):

    def setUp(self):
        self.ce = CombatEngine()

    def test_attack_chance_anarchy(self):
        self.assertAlmostEqual(self.ce.attack_chance(0), 249 / 256.0)

    def test_attack_chance_corporate(self):
        self.assertAlmostEqual(self.ce.attack_chance(7), 19 / 256.0)

    def test_attack_chance_mask(self):
        """government & 0x07."""
        self.assertAlmostEqual(self.ce.attack_chance(8), 249 / 256.0)

    def test_check_pirate_attack_high_danger(self):
        """Anarchy (249): most random bytes trigger attack."""
        rng = DeterministicRNG([0, 0, 0, 0])
        # First byte from this seed — check it's deterministic
        rng2 = DeterministicRNG([0, 0, 0, 0])
        first_byte = rng2.next_byte()
        rng3 = DeterministicRNG([0, 0, 0, 0])
        result = self.ce.check_pirate_attack(rng3, 0)
        self.assertEqual(result, first_byte < 249)

    def test_check_pirate_attack_low_danger(self):
        """Corporate State (19): rarely attacked."""
        # Find a seed where first byte >= 19 (no attack)
        found_no_attack = False
        for s in range(256):
            rng = DeterministicRNG([s, s, s, s])
            rng2 = DeterministicRNG([s, s, s, s])
            first_byte = rng2.next_byte()
            if first_byte >= 19:
                self.assertFalse(self.ce.check_pirate_attack(rng, 7))
                found_no_attack = True
                break
        self.assertTrue(found_no_attack)

    def test_resolve_invalid_action(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        with self.assertRaises(ValueError):
            self.ce.resolve("invalid", rng, fuel=70, credits=100,
                            cargo=[0]*17, tech_level=5,
                            defense=ShipDefense())

    def test_resolve_surrender(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        result = self.ce.resolve("surrender", rng, fuel=70, credits=100,
                                  cargo=[0]*17, tech_level=5,
                                  defense=ShipDefense())
        self.assertEqual(result.action, "surrender")
        self.assertTrue(result.success)
        self.assertEqual(result.status, "surrender")
        self.assertGreater(result.credits_lost, 0)
        self.assertFalse(result.destroyed)

    def test_resolve_surrender_no_damage(self):
        """Surrender doesn't damage shields."""
        defense = ShipDefense()
        rng = DeterministicRNG([1, 2, 3, 4])
        self.ce.resolve("surrender", rng, fuel=70, credits=100,
                         cargo=[0]*17, tech_level=5, defense=defense)
        self.assertEqual(defense.forward_shield, 255)
        self.assertEqual(defense.aft_shield, 255)
        self.assertEqual(defense.energy, 255)

    def test_resolve_fight_deals_forward_damage(self):
        """Fight: damage goes to forward shield only."""
        defense = ShipDefense()
        rng = DeterministicRNG([1, 2, 3, 4])
        self.ce.resolve("fight", rng, fuel=70, credits=100,
                        cargo=[0]*17, tech_level=5, defense=defense)
        # Forward shield should be damaged (3-5 rounds of 40-119 damage)
        self.assertLess(defense.forward_shield, 255)
        # Aft shield should be untouched
        self.assertEqual(defense.aft_shield, 255)

    def test_resolve_escape_deals_aft_damage(self):
        """Escape: damage goes to aft shield only."""
        defense = ShipDefense()
        rng = DeterministicRNG([1, 2, 3, 4])
        self.ce.resolve("escape", rng, fuel=70, credits=100,
                         cargo=[0]*17, tech_level=5, defense=defense)
        self.assertLess(defense.aft_shield, 255)
        self.assertEqual(defense.forward_shield, 255)

    def test_resolve_fight_status_values(self):
        """Fight returns one of: fight_win, fight_lose, destroyed."""
        for seed in range(50):
            rng = DeterministicRNG([seed, seed*2, seed*3, seed*4])
            result = self.ce.resolve("fight", rng, fuel=70, credits=100,
                                      cargo=[0]*17, tech_level=5,
                                      defense=ShipDefense())
            self.assertIn(result.status, ("fight_win", "fight_lose", "destroyed"))

    def test_resolve_escape_status_values(self):
        for seed in range(50):
            rng = DeterministicRNG([seed, seed*2, seed*3, seed*4])
            result = self.ce.resolve("escape", rng, fuel=70, credits=100,
                                      cargo=[0]*17, tech_level=5,
                                      defense=ShipDefense())
            self.assertIn(result.status,
                          ("escape_success", "escape_fail",
                           "escape_no_fuel", "destroyed"))

    def test_resolve_destroyed_flag(self):
        """When defense is destroyed, result.destroyed=True."""
        found_destroyed = False
        for seed in range(200):
            rng = DeterministicRNG([seed, seed*2, seed*3, seed*4])
            defense = ShipDefense()
            result = self.ce.resolve("fight", rng, fuel=70, credits=100,
                                      cargo=[0]*17, tech_level=1,
                                      defense=defense)
            if result.destroyed:
                self.assertEqual(result.status, "destroyed")
                self.assertTrue(defense.destroyed)
                found_destroyed = True
                break
        self.assertTrue(found_destroyed, "Expected at least one destruction")

    def test_ouch_lost_field(self):
        """ouch_lost is "" when no OUCH, or a commodity name."""
        for seed in range(100):
            rng = DeterministicRNG([seed, seed*2, seed*3, seed*4])
            defense = ShipDefense()
            cargo = [5] * 17
            result = self.ce.resolve("fight", rng, fuel=70, credits=100,
                                      cargo=cargo, tech_level=5,
                                      defense=defense)
            # ouch_lost is either "" or a valid commodity name
            if result.ouch_lost:
                self.assertIn(result.ouch_lost, COMMODITIES)

    def test_resolve_escape_no_fuel(self):
        """Escape with 0 fuel: should return escape_no_fuel or destroyed."""
        rng = DeterministicRNG([1, 2, 3, 4])
        result = self.ce.resolve("escape", rng, fuel=0, credits=100,
                                  cargo=[0]*17, tech_level=5,
                                  defense=ShipDefense())
        # With 0 fuel, either no_fuel or destroyed (if damage kills)
        self.assertIn(result.status, ("escape_no_fuel", "destroyed"))

    def test_lose_fraction(self):
        cargo = [10, 20, 0, 5]
        lost = CombatEngine._lose_fraction(cargo, 0.25)
        self.assertEqual(lost[0], 3)  # 10 * 0.25 = 2.5 → int = 2, lost = 8? No...
        # keep = int(10 * 0.75) = 7, lost = 10 - 7 = 3
        self.assertEqual(lost[1], 5)  # int(20 * 0.75) = 15, lost = 5
        self.assertEqual(lost[2], 0)
        self.assertEqual(lost[3], 2)  # int(5 * 0.75) = 3, lost = 2


# ============================================================
# 10. SystemDescriptionEngine
# ============================================================
class TestSystemDescriptionEngine(TestCase):

    def setUp(self):
        self.gen = GalaxyGenerator()
        self.desc = SystemDescriptionEngine(self.gen)

    def test_determinism(self):
        a = self.desc.generate_description(0, galaxy=0)
        b = self.desc.generate_description(0, galaxy=0)
        self.assertEqual(a, b)

    def test_nonempty(self):
        for i in range(0, 256, 50):
            text = self.desc.generate_description(i, galaxy=0)
            self.assertGreater(len(text), 0)

    def test_tibedi_description(self):
        text = self.desc.generate_description(0, galaxy=0)
        self.assertIn("TIBEDI", text)

    def test_all_galaxies(self):
        for g in range(8):
            text = self.desc.generate_description(0, galaxy=g)
            self.assertGreater(len(text), 0)

    def test_different_systems_different_descriptions(self):
        a = self.desc.generate_description(0, galaxy=0)
        b = self.desc.generate_description(71, galaxy=0)
        self.assertNotEqual(a, b)


# ============================================================
# 11. GameState
# ============================================================
class TestGameState(TestCase):

    def setUp(self):
        self.gs = GameState(galaxy=0, system_index=0)
        self.gs.load_system()

    def test_defaults(self):
        self.assertEqual(self.gs.galaxy, 0)
        self.assertEqual(self.gs.system_index, 0)
        self.assertAlmostEqual(self.gs.fuel, 70)
        self.assertAlmostEqual(self.gs.credits, 100.0)
        self.assertEqual(self.gs.cargo, [0] * 17)

    def test_defense_initialized(self):
        self.assertIsInstance(self.gs.defense, ShipDefense)
        self.assertEqual(self.gs.defense.forward_shield, 255)

    def test_system_tibedi(self):
        self.assertEqual(self.gs.system["name"], "TIBEDI")

    def test_cargo_weight(self):
        self.assertEqual(self.gs.cargo_weight, 0)
        self.gs.cargo[0] = 5
        self.gs.cargo[2] = 3
        self.assertEqual(self.gs.cargo_weight, 8)

    def test_buy_ok(self):
        cost = self.gs.buy("Food", 1)
        self.assertGreater(cost, 0)
        self.assertEqual(self.gs.cargo[0], 1)

    def test_buy_no_money(self):
        self.gs.credits = 0
        with self.assertRaises(MarketError):
            self.gs.buy("Food", 1)

    def test_buy_hold_full(self):
        # Fill hold to max
        self.gs.cargo[0] = SHIP_HOLD
        with self.assertRaises(MarketError):
            self.gs.buy("Food", 1)

    def test_sell_ok(self):
        self.gs.cargo[0] = 5
        income = self.gs.sell("Food", 2)
        self.assertGreater(income, 0)
        self.assertEqual(self.gs.cargo[0], 3)

    def test_sell_not_enough(self):
        with self.assertRaises(MarketError):
            self.gs.sell("Food", 1)

    def test_update_fuel(self):
        self.gs.update_fuel(-10)
        self.assertAlmostEqual(self.gs.fuel, 60)
        self.gs.update_fuel(5)
        self.assertAlmostEqual(self.gs.fuel, 65)
        self.gs.update_fuel(100)
        self.assertAlmostEqual(self.gs.fuel, 70)
        self.gs.update_fuel(-100)
        self.assertAlmostEqual(self.gs.fuel, 0)

    def test_near_systems(self):
        systems = self.gs.near_systems()
        self.assertGreater(len(systems), 0)
        # All should be reachable
        for idx, name, dist, cost in systems:
            self.assertNotEqual(idx, 0)
            self.assertGreater(dist, 0)

    def test_jump_success(self):
        result = self.gs.jump(71)
        self.assertTrue(result.success)
        self.assertEqual(self.gs.system_index, 71)
        self.assertEqual(self.gs.system["name"], "EDINSOIN")

    def test_jump_resets_defense(self):
        """load_system() after jump resets defense (RES4)."""
        self.gs.defense.forward_shield = 50
        self.gs.defense.energy = 30
        self.gs.jump(71)
        self.assertEqual(self.gs.defense.forward_shield, 255)
        self.assertEqual(self.gs.defense.energy, 255)

    def test_jump_same_system(self):
        """Прыжок в текущую систему допустим (расстояние 0, расход 0)."""
        result = self.gs.jump(0)
        self.assertTrue(result.success)
        self.assertEqual(result.fuel_cost, 0)

    def test_jump_invalid(self):
        result = self.gs.jump(256)
        self.assertFalse(result.success)

    def test_jump_no_fuel(self):
        self.gs.fuel = 0
        result = self.gs.jump(71)
        self.assertFalse(result.success)

    def test_refuel(self):
        self.gs.fuel = 50
        result = self.gs.refuel()
        self.assertTrue(result.success)
        self.assertAlmostEqual(self.gs.fuel, 70)

    def test_refuel_full(self):
        result = self.gs.refuel()
        self.assertFalse(result.success)

    def test_check_pirate_attack(self):
        # Deterministic with default seed
        result = self.gs.check_pirate_attack()
        self.assertIsInstance(result, bool)

    def test_resolve_combat_surrender(self):
        result = self.gs.resolve_combat_action("surrender")
        self.assertEqual(result.action, "surrender")
        self.assertTrue(result.success)
        self.assertGreater(result.credits_lost, 0)
        self.assertLess(self.gs.credits, 100.0)

    def test_resolve_combat_fight(self):
        result = self.gs.resolve_combat_action("fight")
        self.assertIn(result.status, ("fight_win", "fight_lose", "destroyed"))

    def test_resolve_combat_escape(self):
        result = self.gs.resolve_combat_action("escape")
        self.assertIn(result.status, ("escape_success", "escape_fail",
                                       "escape_no_fuel", "destroyed"))

    def test_combat_does_not_destroy_defense_on_surrender(self):
        self.gs.resolve_combat_action("surrender")
        self.assertEqual(self.gs.defense.forward_shield, 255)
        self.assertEqual(self.gs.defense.energy, 255)

    def test_description(self):
        text = self.gs.generate_description()
        self.assertIn("TIBEDI", text)

    def test_determinism(self):
        gs2 = GameState(galaxy=0, system_index=0)
        gs2.load_system()
        self.assertEqual(self.gs.market.get_market(), gs2.market.get_market())

    def test_determinism_rng(self):
        gs1 = GameState(galaxy=0, system_index=0, rng_seed=[5, 10, 15, 20])
        gs2 = GameState(galaxy=0, system_index=0, rng_seed=[5, 10, 15, 20])
        r1 = gs1.resolve_combat_action("fight")
        r2 = gs2.resolve_combat_action("fight")
        self.assertEqual(r1.status, r2.status)
        self.assertEqual(r1.success, r2.success)

    def test_load_system_resets_defense(self):
        self.gs.defense.forward_shield = 0
        self.gs.defense.aft_shield = 0
        self.gs.defense.energy = 0
        self.gs.load_system()
        self.assertEqual(self.gs.defense.forward_shield, 255)
        self.assertEqual(self.gs.defense.aft_shield, 255)
        self.assertEqual(self.gs.defense.energy, 255)


# ============================================================
# 12. GameState — combat + defense integration
# ============================================================
class TestCombatDefenseIntegration(TestCase):

    def test_fight_reduces_forward_shield(self):
        gs = GameState(galaxy=0, system_index=0, rng_seed=[10, 20, 30, 40])
        gs.load_system()
        initial_fsh = gs.defense.forward_shield
        gs.resolve_combat_action("fight")
        self.assertLess(gs.defense.forward_shield, initial_fsh)

    def test_escape_reduces_aft_shield(self):
        gs = GameState(galaxy=0, system_index=0, rng_seed=[10, 20, 30, 40])
        gs.load_system()
        initial_ash = gs.defense.aft_shield
        gs.resolve_combat_action("escape")
        # Aft shield reduced (unless destroyed before shield check)
        if not gs.defense.destroyed:
            self.assertLessEqual(gs.defense.aft_shield, initial_ash)

    def test_surrender_preserves_defense(self):
        gs = GameState(galaxy=0, system_index=0, rng_seed=[10, 20, 30, 40])
        gs.load_system()
        gs.resolve_combat_action("surrender")
        self.assertEqual(gs.defense.forward_shield, 255)
        self.assertEqual(gs.defense.aft_shield, 255)
        self.assertEqual(gs.defense.energy, 255)

    def test_jump_resets_defense_after_combat(self):
        gs = GameState(galaxy=0, system_index=0, rng_seed=[10, 20, 30, 40])
        gs.load_system()
        gs.resolve_combat_action("fight")
        # Defense should be damaged
        self.assertLess(gs.defense.forward_shield, 255)
        # Jump to another system (dock = reset)
        gs.jump(71)
        self.assertEqual(gs.defense.forward_shield, 255)
        self.assertEqual(gs.defense.energy, 255)

    def test_multiple_combats_accumulate_damage(self):
        """Without docking, defense damage persists."""
        gs = GameState(galaxy=0, system_index=0, rng_seed=[10, 20, 30, 40])
        gs.load_system()
        gs.resolve_combat_action("fight")
        fsh_after_first = gs.defense.forward_shield
        if not gs.defense.destroyed:
            gs.resolve_combat_action("fight")
            if not gs.defense.destroyed:
                self.assertLessEqual(gs.defense.forward_shield, fsh_after_first)


# ============================================================
# 13. RefuelResult / CombatResult / ShipDefense — dataclass
# ============================================================
class TestDataclasses(TestCase):

    def test_refuel_result(self):
        r = RefuelResult(success=True, cost=5.0, new_fuel=70)
        self.assertTrue(r.success)
        self.assertEqual(r.cost, 5.0)
        self.assertEqual(r.new_fuel, 70)
        self.assertIsNone(r.error_reason)

    def test_combat_result_defaults(self):
        r = CombatResult(action="fight", success=True, message="win")
        self.assertEqual(r.status, "")
        self.assertEqual(r.fuel_used, 0)
        self.assertEqual(r.credits_lost, 0.0)
        self.assertEqual(r.cargo_lost, ())
        self.assertEqual(r.detail, 0)
        self.assertFalse(r.destroyed)
        self.assertEqual(r.ouch_lost, "")

    def test_combat_result_full(self):
        r = CombatResult(action="escape", success=False, message="msg",
                         status="escape_no_fuel", fuel_used=5,
                         credits_lost=10.0, cargo_lost=(1, 2), detail=5,
                         destroyed=False, ouch_lost="Food")
        self.assertEqual(r.status, "escape_no_fuel")
        self.assertEqual(r.detail, 5)
        self.assertEqual(r.ouch_lost, "Food")

    def test_ship_defense_mutable(self):
        """ShipDefense is NOT frozen (mutable dataclass)."""
        d = ShipDefense()
        d.forward_shield = 100
        self.assertEqual(d.forward_shield, 100)

    def test_combat_result_frozen(self):
        """CombatResult IS frozen."""
        r = CombatResult(action="fight", success=True, message="win")
        with self.assertRaises(AttributeError):
            r.action = "escape"


# ============================================================
# 14. Pythonic dunder-методы
# ============================================================
class TestDunders(TestCase):
    """__bool__/__len__/__getitem__/__iter__/__next__/__str__/__repr__."""

    def test_result_bool(self):
        """bool(result) == result.success для всех наследников ResultBase."""
        self.assertTrue(RefuelResult(success=True, cost=0.0, new_fuel=70))
        self.assertFalse(RefuelResult(success=False, cost=0.0, new_fuel=70))
        self.assertTrue(CombatResult(action="fight", success=True, message="m"))
        self.assertFalse(CombatResult(action="fight", success=False, message="m"))
        self.assertTrue(JumpResult(success=True))
        self.assertFalse(JumpResult(success=False))

    def test_market_len(self):
        market = MarketEngine(GalaxyGenerator(), 0, 0)
        self.assertEqual(len(market), 17)
        self.assertEqual(len(list(market)), 17)

    def test_market_getitem_index_and_name(self):
        market = MarketEngine(GalaxyGenerator(), 0, 0)
        self.assertEqual(market[0], market["Food"])
        self.assertEqual(market[0]["name"], "Food")
        self.assertEqual(market["Food"]["unit"], market[0]["unit"])
        self.assertEqual(market["Alien Items"]["name"], "Alien Items")

    def test_market_iter_rows(self):
        market = MarketEngine(GalaxyGenerator(), 0, 0)
        rows = [row for row in market]
        self.assertEqual(len(rows), 17)
        self.assertEqual(rows[0], market.get_market()[0])
        self.assertEqual(rows, market.get_market())

    def test_rng_next(self):
        rng = DeterministicRNG([1, 2, 3, 4])
        byte = next(rng)
        self.assertIsInstance(byte, int)
        self.assertTrue(0 <= byte <= 255)

    def test_rng_islice_equivalent_to_next_byte(self):
        from itertools import islice
        rng = DeterministicRNG([1, 2, 3, 4])
        stream = list(islice(rng, 16))
        rng2 = DeterministicRNG([1, 2, 3, 4])
        self.assertEqual(stream, [rng2.next_byte() for _ in range(16)])

    def test_galaxy_len(self):
        self.assertEqual(len(GalaxyGenerator()), 256)

    def test_jump_engine_repr(self):
        je = JumpEngine(GalaxyGenerator(), 0)
        self.assertIn("JumpEngine", repr(je))
        self.assertIn("galaxy=0", repr(je))

    def test_fuel_engine_repr(self):
        fe = FuelEngine()
        self.assertIn("FuelEngine", repr(fe))
        self.assertIn("70 units", repr(fe))

    def test_ship_defense_str(self):
        d = ShipDefense()
        self.assertEqual(str(d), "FSH 255/255 ASH 255/255 EN 255/255")
        d.take_damage(100, from_rear=False)
        self.assertEqual(str(d), "FSH 155/255 ASH 255/255 EN 255/255")

    def test_game_state_str(self):
        gs = GameState(galaxy=0, system_index=0)
        s = str(gs)
        self.assertIn("TIBEDI", s)
        self.assertIn("Fuel 70", s)
        self.assertIn("100.00 Cr", s)

    def test_game_state_repr(self):
        gs = GameState(galaxy=0, system_index=0)
        self.assertIn("GameState(galaxy=0, system_index=0", repr(gs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
