# pyElite v0.1.0 — Deterministic Python port of Elite (1984)

**pyElite** is a faithful, fully deterministic port of the game math of **Elite** (BBC Micro / C64, 1984) to Python 3.10+. No `random` module — every galaxy, market price, jump and combat outcome is reproducible from the seed.

## What's new in this release

- **Full TUI localization** — the Textual interface is now completely translated into **English, Russian and Spanish** (233 strings × 3 languages): dialogs, tables, status bar, help screen, combat and game-over screens, save/load dialogs, action logs.
- **`--lang` command-line option** — choose the interface language at launch:

  ```bash
  python elite_tui.py --lang en    # English
  python elite_tui.py --lang es    # Spanish
  python elite_tui.py --lang ru    # Russian (default)
  ```

- **Screenshots** of the TUI main window (EN/ES) added to the README.
- **Windows launchers** — the text version is cross-platform; added `run_cli.bat`, `run_tui.bat` and `bot_autopilot.bat` (UTF-8 console, `.venv\Scripts\python.exe` auto-detection).

## Features

- **Galaxy generation** — 256 systems × 8 galaxies, reproduced from the original assembly (DORND, TT111, TT24).
- **Commodity market** — 17 commodities, deterministic prices per system, buy/sell with profit tracking.
- **Hyperspace jumps** — fuel costs, jump range limits, route planning.
- **Ship defense** — three-layer shields (FSH/ASH/ENERGY, 0–255).
- **Pirate combat** — attack / flee / surrender, deterministic outcomes.
- **Planet descriptions** ("goat soup") — localized per interface language.
- **Two interfaces**:
  - **CLI** (`./run_cli.sh`) — interactive command loop, no external dependencies.
  - **TUI** (`./run_tui.sh`) — full-screen Textual app: market, galaxy map, dialogs, quick save/load (F5/F9), named saves (F2/F3), session trade log (F4).
- **Autopilot bot** (`./bot_autoplay.sh`) — autonomous trading bot with self-learning memory (Q-learning, UCB1, Bayesian) stored in SQLite.
- **Analytics** — `EventLogger` (SQLite event log), `ProfitAnalyzer`, `RouteFinder` (BFS over the system graph).
- **Saves** — JSON `.elite` files with full state (position, fuel, credits, cargo, shields, PRNG state, market availability).

## Requirements

- Python 3.10+
- CLI: no external dependencies
- TUI: `pip install -e ".[tui]"` (Textual)

## Quick start

```bash
./run_cli.sh                 # interactive CLI
./run_tui.sh                 # full-screen TUI (requires textual)
./run_tui.sh --lang en       # TUI in English
./bot_autoplay.sh            # infinite autopilot runs (Ctrl-C to stop)
.venv/bin/python -m pytest   # 571 tests
```

On Windows the same launchers exist as `.bat` files:

```bat
run_cli.bat                  @ interactive CLI
run_tui.bat --lang en        @ TUI in English
bot_autopilot.bat            @ infinite autopilot runs (Ctrl-C to stop)
```

## License

GNU GPL v3 — see [LICENSE](LICENSE).