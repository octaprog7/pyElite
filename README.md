# pyElite — Python text-based port of Elite

**English** | [**Русский (README_RU.md)**](README_RU.md)

A deterministic port of the game math of Elite (BBC Micro / C64, 1984) to
Python 3.10+. It reproduces galaxy generation (256 systems × 8 galaxies), the
commodity market, hyperjumps, the ship defense system, pirate combat
encounters and planet descriptions ("goat soup"). All calculations are
deterministic; the `random` module is not used.

Original: Elite (Ian Bell & David Braben, 1984, BBC Micro / C64).
Sources: disassembly from bbcelite.com (OOPS, OUCH, SHD, RESET, DORND,
TT111, TT24 and others).

Requirements: Python 3.10+. The CLI needs no external dependencies; the
TUI requires Textual (`pip install -e ".[tui]"`). UTF-8 encoding.

Target group: gamers born in 1970 or earlier.

## Architecture

Module dependencies (no cycles):

| Module | Description |
|--------|-------------|
| [`elite_core.py`](elite_core.py) | Source of constants, types, `MarketError`, `commodity_index()`, `ShipDefense`, `CombatEngine`, `GameState`, `DeterministicRNG`, `GalaxyGenerator`, `MarketEngine`, `JumpEngine`, `FuelEngine`, `SystemDescriptionEngine`. Imports only from `elite_galaxy_generator` and the stdlib. |
| [`elite_galaxy_generator.py`](elite_galaxy_generator.py) | Galaxy generation (`EliteGalaxyGenerator`, `GalaxyGenerator`). Imports from the stdlib. |
| [`elite_trading.py`](elite_trading.py) | Imports constants/types from `elite_core`; `EliteGalaxyGenerator` from `elite_galaxy_generator`. Class `EliteMarket`. |
| [`elite_jumps.py`](elite_jumps.py) | Imports `FUEL_TANK_CAPACITY`, `ENGINE_MAX_RANGE_UNITS`, `JumpResult` from `elite_core`; `EliteGalaxyGenerator` from `elite_galaxy_generator`. Class `Hyperdrive`. |
| [`elite_analytics.py`](elite_analytics.py) | `EventLogger` (SQLite, records tagged with `player_id`), `ProfitAnalyzer`, `RouteFinder` (BFS over the system graph). |
| [`elite_autopilot.py`](elite_autopilot.py) | Autonomous bot: `Autopilot` (turn planning, trading, combat), `TradeRoute`, `BotMemory` (SQLite self-learning memory: Q-learning, UCB1, Bayesian), `PLAYER_ID`. Imports from `elite_core` and `elite_analytics`. |
| [`elite_i18n.py`](elite_i18n.py) | `I18n` (EN, RU, ES), 100 keys × 3 languages. |
| [`elite_backend.py`](elite_backend.py) | Backend abstractions: `Renderer`/`AudioBackend` protocols, `GameEvent`, factories `create_renderer()`/`create_audio()` (shipped backends: "cli", "null"). |
| [`elite_renderer_cli.py`](elite_renderer_cli.py) | CLI renderer (`CLIRenderer`) — text output for the game loop. |
| [`elite_audio_null.py`](elite_audio_null.py) | Null audio backend (`NullAudio`) — no sound output. |
| [`elite_tui.py`](elite_tui.py) | Full-screen TUI on Textual (`EliteTUI`): market, jumps, combat, saves (F2/F3/F5/F9). Requires `textual`. |
| [`elite_line_editor.py`](elite_line_editor.py) | Line editor with history (used by the CLI loop). |
| [`game_loop.py`](game_loop.py) | CLI game loop. Imports from `elite_core`, `elite_trading`, `elite_jumps`, `elite_analytics`, `elite_i18n`. Classes `GameState` (local), `GameLogger`, `GameLoop`. |
| [`analyze_endings.py`](analyze_endings.py) | Analysis of bot game-ending causes from `elite_events.db` (piracy_drain, dead_end, stall, user_stop...), filtered by `--player-id`. |
| [`tests/test_elite_core.py`](tests/test_elite_core.py) | Core tests: `DeterministicRNG`, constants, `commodity_index`, `GalaxyGenerator`, `MarketEngine`, `JumpEngine`, `FuelEngine`, `ShipDefense`, `CombatEngine`, `SystemDescriptionEngine`, `GameState`. |
| [`tests/test_elite_i18n.py`](tests/test_elite_i18n.py) | Localization tests: key sync, placeholders, fallback, formatting, Unicode. |
| [`tests/test_autopilot.py`](tests/test_autopilot.py) | Autopilot tests: turn planning, routes, BotMemory (Q/UCB1/Bayesian), `player_id` separation, calibration (CREDIT_FLOOR, MIN_FUEL_RESERVE, DANGER_SKIP_THRESHOLD), bankruptcy. |
| [`tests/test_analytics.py`](tests/test_analytics.py) | `EventLogger` tests: schema with `player_id`, old DB migration, `load_events` filter. |

## Modules (in detail)

### elite_core.py — core

* **DeterministicRNG** — PRNG from the original (BBC: DORND, "Twins" register).
  Methods: `next_byte()`, `next_range(lo, hi)`, `next_word()`, `pick(thresholds)`.
* **Constants** — `SEED_GALAXY_0`, `NAME_PAIRS`, `ECONOMIES`, `GOVERNMENTS`,
  `COMMODITIES`, `MARKET_TABLE`, `UNIT_BY_FLAGS`, `DANGER_TABLE`,
  `SHIP_HOLD` (22), `PRECIOUS_LIMIT` (200), `FUEL_TANK_CAPACITY` (70),
  `FUEL_PRICE_PER_UNIT_CR` (0.2), `ENGINE_MAX_RANGE_UNITS` (256),
  `SHIP_DEFENSE_MAX` (255), `STARTING_CASH_UNITS` (1000).
* **Types** — `Cargo` (`list[int]`, 17 categories), `SystemRow`, `MarketRow`,
  `JumpResult`, `RefuelResult`, `CombatResult`.
* **`MarketError(ValueError)`** — trading operation error.
* **`commodity_index(item: str | int) -> int`** — commodity index by name
  (case-insensitive, prefix match) or number.
* **`ShipDefense`** — three-layer defense (FSH, ASH, ENERGY, 0–255).
* **`CombatEngine`** — `check_pirate_attack()`, `resolve(action, ...)`.
* **`GameState`** — `galaxy`, `system_index`, `fuel`, `credits`, `cargo`,
  `defense`, `rng`, `generator`, `market`, `jump_engine`, `fuel_engine`,
  `combat_engine`, `description_engine`. Methods: `buy()`, `sell()`, `jump()`,
  `refuel()`, `check_pirate_attack()`, `resolve_combat_action()`,
  `near_systems()`, `generate_description()`, `load_system()`
  (rebuild market + `defense.reset()`).

### elite_galaxy_generator.py — galaxy generation

* **`EliteGalaxyGenerator`** — `generate_galaxy(n) -> list[SystemRow]`,
  256 systems × 8 galaxies. Fields: `x`, `y`, `economy`, `government`,
  `tech_level`, `population`, `productivity`, `radius`, `name`,
  `economy_name`, `government_name`.
* **`GalaxyGenerator`** — alias/wrapper around `EliteGalaxyGenerator`.
* **Seed** — `tuple[int, int, int, int, int, int]` (6 bytes, little-endian).

### elite_trading.py — market

* **`EliteMarket`** — `buy(item, qty) -> cost_cr`, `sell(item, qty) -> income_cr`,
  `get_market() -> list[MarketRow]`, `total_tonnes() -> int`.
* Internal money is in "units" (1 unit = 0.1 Cr); public methods return Cr.

### elite_jumps.py — hyperjumps

* **`Hyperdrive`** — `distance_units(a, b) -> int`,
  `calculate_fuel_cost(a, b) -> int`, `can_jump(current, target, fuel) -> JumpResult`,
  `execute_jump(...) -> JumpResult`.
* **`_square_root(r, q)`** — integer sqrt from the assembly (long division,
  8 iterations, $9978).

### elite_analytics.py — analytics

* **`EventLogger`** — SQLite log of jumps, trades, refuels, combats. Each
  record is tagged with `player_id` (bot version; `__init__(db_path,
  player_id=0)`). Old DBs are migrated automatically: the
  `player_id INTEGER NOT NULL DEFAULT 0` column is added via
  `ALTER TABLE`, and all historical records get `player_id=0`.
* **`ProfitAnalyzer`** — `find_best_deals()`, `find_best_deals_all_items()`.
* **`RouteFinder`** — `find_route_with_fuel()` — BFS over the system graph,
  edges ≤ 7.0 light years.

### elite_autopilot.py — autonomous bot

An automatic player: it trades, jumps, refuels and makes combat decisions
directly through the `elite_core.GameState` API (no CLI parsing). Everything
is deterministic; the `random` module is used only inside `BotMemory`
(epsilon-greedy Q-learning).

Planning priorities (`Autopilot._plan_turn`): sell at a good price →
deliver cargo → anti-stall → buy along the best route → refuel →
exploratory jump → desperate jump → dead_end/restart.

**Calibration (constants in `elite_autopilot.py`):**

* `CREDIT_FLOOR = 50.0` — if credits are low and there is no profitable
  route, the bot ends the game with `dead_end` (restarting with 100 Cr is
  better than a slow death from refuels and pirate attacks).
* `MIN_FUEL_RESERVE = 5` — minimum fuel reserve for a jump; enables a jump
  chain of 70 → 38 → 6 without refueling (with reserve=10 the bot would
  refuel after every jump ≥ 3 ly).
* `DANGER_SKIP_THRESHOLD = 0.2` — hard filter: systems with P(attack) ≥ 0.2
  are skipped entirely in all target-selection methods (explore, sell,
  desperate). Systems where at least 1 of 5 visits ends in an attack are
  excluded from routes.
* `EARLY_GAME_CREDITS = 500`, `MID_GAME_CREDITS = 2000` — progressive
  strategy: early game trades only Food/Textiles/Minerals with jumps up to
  5 ly; mid and late game unlock Liquor/Wines, Computers, Machinery and
  precious metals.

**Self-learning memory (`BotMemory`, SQLite `bot_memory.db`):**

* Q-learning — combat action selection fight/flee/surrender (epsilon-greedy,
  epsilon decays 0.15 → 0.02 over ~500 rounds);
* UCB1 (multi-armed bandit) — explore/exploit balance for trade routes;
* Bayesian (Beta distribution) — system danger estimation from the actual
  attack frequency with a government-based prior.

**Bot version data separation (`player_id`):**

A new bot version = a new `PLAYER_ID` (`PLAYER_ID = 2` in
`elite_autopilot.py`). Data from different versions is stored in the same DB
files but is never mixed:

* `bot_memory.db` — tables `combat_q`, `route_stats`, `system_stats` have
  `PRIMARY KEY (player_id, ...)`; the `meta` table has no `player_id`
  (the `total_rounds` counter is global: epsilon-decay and UCB1 do not
  depend on the version);
* `elite_events.db` — every `EventLogger` transaction is tagged with
  `player_id`;
* old DBs are migrated automatically on first open: all historical data
  gets `player_id=0`.

Run: `python3 elite_autopilot.py` (single run) or `./bot_autoplay.sh`
(infinite restarts, Ctrl-C to stop). Event log: `elite_events.db`;
self-learning memory: `bot_memory.db`.

### analyze_endings.py — game-ending analysis

Summary of bot game-ending causes from `elite_events.db` (destroyed,
piracy_drain, dead_end, stall, user_stop, unknown), per-game details, top
dangerous systems and trends.

```bash
python3 analyze_endings.py                  # all players
python3 analyze_endings.py elite_events.db  # specified DB file
python3 analyze_endings.py --player-id 2    # only bot version 2 records
```

`--player-id N` filters transactions by the `player_id` column; without the
flag — all versions (the report header shows `Player ID: ALL`).

### elite_i18n.py — localization

* **`I18n`** — `tr(key, **kwargs)`, `set_locale(lang)`, `available_locales()`.
* 100 keys × 3 languages (EN, RU, ES). Fallback: locale → EN → key.
* Brazilian Portuguese (pt-BR) — available on request.

### game_loop.py — CLI

* **`GameLoop`** — interactive loop, command parsing, handler dispatch.
* **`GameState`** (local class) — `galaxy`, `system_index`, `fuel`,
  `credits`, `cargo`, `defense`, `hyperdrive`, `market`. Connects to
  `CoreGameState` via `_core_state()`.
* **`GameLogger`** — CSV log (`log/game_log.csv`).
* 15 commands (see below).

## CLI commands

| Command              | Arguments              | Description                              |
|----------------------|------------------------|------------------------------------------|
| `status`             | —                      | System, fuel, cargo, credits, defense    |
| `market`             | —                      | Commodity price and availability table   |
| `near`               | —                      | Systems within jump range                |
| `buy <item> <qty>`   | name/index, quantity   | Buy a commodity                          |
| `sell <item> <qty>`  | name/index, quantity   | Sell a commodity                         |
| `jump <index>`       | system index (0–255)   | Hyperjump + pirate attack check          |
| `refuel`             | —                      | Refuel to full tank (0.2 Cr/unit)        |
| `route <index>`      | system index           | Shortest route (BFS)                     |
| `profit [item]`      | commodity name (opt.)  | Top-10 profitable deals                  |
| `profit-top [N]`     | number (opt.)          | Top-N deals across all commodities       |
| `combat <action>`    | fight/escape/surrender | Fight pirates (manual)                   |
| `info`               | —                      | Current planet description               |
| `save <file>`        | file path              | Save to JSON                             |
| `load <file>`        | file path              | Load from JSON                           |
| `lang [code]`        | en/ru/es (opt.)        | Switch interface language                |
| `help`               | —                      | List of commands                         |
| `quit`               | —                      | Exit                                     |

Starting position: galaxy 0, system #0 TIBEDI, fuel 70 units (7.0 light
years), credits 100.0 Cr, empty hold (22 t).

## Ship defense model

Three-layer defense (BBC Elite: FSH, ASH, ENERGY), each 0–255:

* **Forward Shield (FSH)** — bow shield, absorbs damage from the front (fight).
* **Aft Shield (ASH)** — stern shield, absorbs damage from behind (escape).
* **Energy (ENERGY)** — energy bank, absorbs shield overflow.

**OOPS (damage handling):**

1. `shield -= damage`; if `shield >= 0` — the shield held.
2. if `shield < 0` — `shield = 0`, the excess goes to `ENERGY`.
3. `ENERGY -= overflow`; if `ENERGY <= 0` — the ship is destroyed (GAME OVER).
4. `ENERGY > 0` — call OUCH.

**OUCH (cargo loss, ~4.5% chance):**

* DORND → A, X; `A >= 128` (50%) → nothing; `X >= 22` (91%) → nothing;
  `cargo[X] == 0` → nothing; otherwise `cargo[X] = 0` (destroy the commodity).
* Equipment (indices 17–21) is not implemented.

**SHD (shield recharge):**

* Shields +1 (costs 1 energy unit), only if `ENERGY >= 128` (>50%).
* Energy +1 per round.

**RESET (recharge on docking):**

* `FSH = ASH = ENERGY = 255` (RES4: `LDA #$FF; STA FSH,X`).

## Combat system

Trigger: after every jump a pirate attack is checked automatically
(`check_pirate_attack`: DORND < `DANGER[government]`). If attacked, the
player chooses an action interactively (fight / escape / surrender).

Actions:

* **fight** — 3–5 rounds of damage to the forward shield (40–119 units/round);
  win chance = `(0x80 + tech_level * 8) / 256`;
  loss — 25% of cargo + 20% of credits.
* **escape** — 1–2 rounds of damage to the aft shield (30–80 units/round);
  costs 1–10 fuel units; succeeds if `DORND < min(255, fuel * 3)`;
  failure — 15% of cargo.
* **surrender** — no damage; loses 10–50% of credits + 25% of cargo.

Death: `ENERGY <= 0` → GAME OVER → restart with basic equipment (galaxy 0,
TIBEDI, fuel 70, credits 100, empty hold, full defense).

Recharge: on docking (`load_system`) — `defense.reset()`
(FSH = ASH = ENERGY = 255).

## Tests

The text-part suite is pytest: 456 passed, 1 skipped (`tests/`).
GUI/pygame tests are not part of this repository.

```bash
.venv/bin/python -m pytest           # all tests
.venv/bin/python -m pytest -q        # concise output
.venv/bin/python -m pytest tests/test_autopilot.py   # autopilot only
```

Coverage: core (`tests/test_elite_core.py` — RNG, market, jumps, defense,
combat, GameState), localization (`tests/test_elite_i18n.py`), autopilot
(`tests/test_autopilot.py` — planning, routes, BotMemory, player_id
separation, calibration, bankruptcy), EventLogger (`tests/test_analytics.py`
— schema, player_id, migration), CLI loop, backend, renderers (CLI),
audio (null), TUI, line editor.

## Quick start

```bash
./run_cli.sh                 # interactive CLI
./run_tui.sh                 # full-screen TUI (requires textual)
./bot_autoplay.sh            # infinite autopilot runs (Ctrl-C to stop)
.venv/bin/python -m pytest   # tests
```

All files must be in the same directory (next to `elite_galaxy_generator.py`
and `elite_analytics.py`, which are required for imports).

## Sources

* Original: Elite (Ian Bell & David Braben, 1984, BBC Micro / Acorn Electron /
  Commodore 64).
* Disassembly: bbcelite.com — routines OOPS, OUCH, SHD, RESET, DEATH, DORND,
  TT111, TT24, TT22, square_root ($9978), goat soup.
* Source files: `src/code_6a00.asm`, `src/code_28ba.asm`,
  `src/save_data.asm`, `src/text/text_docked.asm`, `src/text/text_flight.asm`,
  `src/vars_main.asm`, `src/vars_ships.asm`, `src/vars_zeropage.asm`,
  `src/math/math_square.asm`.

## License and copyright

"Elite" is copyright David Braben & Ian Bell, Acornsoft (BBC / Electron
versions), Firebird / British Telecom (C64 version), 1984–1985, all rights
reserved. The name "Elite" is used in this project for historical, educational
and archival purposes only.

The original Python code of this project (architecture, CLI, TUI, i18n,
analytics, tests) is distributed under GNU GPL v3 — see [LICENSE](LICENSE).

Game data and mechanics derived from the original Elite (system, commodity,
economy and government tables, "goat soup" planet descriptions, the DORND
PRNG and others) remain the intellectual property of their respective
copyright holders and are NOT covered by the GPL v3 license. They are
included in this project solely for educational and non-commercial purposes,
with attribution to their sources (bbcelite.com, Ian Bell's source releases).

This project contains no original ROM images, binaries, graphics, music or
sound from the game. The project is non-commercial: distribution and use are
permitted for non-commercial purposes only.