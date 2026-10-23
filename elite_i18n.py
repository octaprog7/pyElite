"""
pyElite — модуль локализации (i18n) для CLI-порта.

Три языка: EN (базовый), RU и ES. Все каталоги (EN, RU, ES) содержат
идентичный набор ключей; значения — Unicode-строки с {placeholders} для
str.format().

Имена систем (TIBEDI, EDINSOIN...), правительств и команд (status, market,
buy...) НЕ переводятся: они передаются через **kwargs и подставляются в
шаблон. Названия товаров переводятся ТОЛЬКО для показа и разбора ввода
(COMMODITY_NAMES / commodity_display / resolve_commodity); канонические
имена остаются языком API и хранения. Экономики переводятся в таблицах
описания планеты (DESCRIPTION_TABLES).

Порядок поиска ключа (fallback): текущая локаль -> EN -> сам ключ.

Только стандартная библиотека (typing, dataclasses). Кодировка UTF-8 без BOM.
"""

from typing import Dict, List, NamedTuple, Optional, Tuple

# ---------------------------------------------------------------------------
# Каталоги строк
# ---------------------------------------------------------------------------

EN: Dict[str, str] = {
    # --- Заголовок / выход ---
    "app.welcome": "pyElite — trading and hyperspace jumps. Type help.",
    "app.farewell": "Farewell, Commander.",

    # --- status ---
    "cmd.status.system": "System:      #{index} {name}",
    "cmd.status.economy": "Economy:     {name}",
    "cmd.status.government": "Government:  {name}",
    "cmd.status.fuel": "Fuel:        {fuel}/{max_fuel} units ({fuel_ly:.1f}/7.0 ly)",
    "cmd.status.cargo": "Cargo:       {cargo}/{hold} t",
    "cmd.status.credits": "Credits:     {credits:.2f} Cr",

    # --- status (defense) ---
    "cmd.status.defense": "Defense:    FSH {fsh}/255 ASH {ash}/255 EN {energy}/255",

    # --- market ---
    "cmd.market.title": "Market at system #{index} {name} ({economy})",
    "cmd.market.header": "Item            Unit  Available      Buy, Cr     Sell, Cr",
    "cmd.market.separator": "-----------------------------------------------------",

    # --- near ---
    "cmd.near.title": "Systems in jump range (fuel {fuel} units):",
    "cmd.near.empty": "  No system reachable — refuel first.",
    "cmd.near.header": "  #  Name        Distance  Fuel cost",
    "cmd.near.row": "{index:>3}  {name:<10}{dist_ly:>10.1f} ly  cost: {cost} units ({cost_ly:.1f} ly)",

    # --- buy ---
    "cmd.buy.done": "Bought {qty} {name} for {cost:.2f} Cr. Credits: {credits:.2f} Cr; cargo: {cargo}/{hold} t.",
    "cmd.buy.error": "Error: {exc}",

    # --- sell ---
    "cmd.sell.done": "Sold {qty} {name} for {income:.2f} Cr. Credits: {credits:.2f} Cr; cargo: {cargo}/{hold} t.",
    "cmd.sell.error": "Error: {exc}",

    # --- jump ---
    "cmd.jump.usage": "Usage: jump <system index> (indices from near)",
    "cmd.jump.bad_index": "System index must be an integer: {value!r}",
    "cmd.jump.out_of_range": "System #{target} does not exist (valid range 0-{max}).",
    "cmd.jump.already_here": "You are already in this system.",
    "cmd.jump.too_far": "Too far: {dist_ly:.1f} ly (engine range limit).",
    "cmd.jump.no_fuel": "Not enough fuel: need {cost} units, have {fuel} units.",
    "cmd.jump.complete": "Jump complete. Distance: {dist_ly:.1f} ly; fuel cost: {cost} units; fuel: {fuel} units.",
    "cmd.jump.arrived": "Arrived at system #{index} {name} ({economy}).",

    # --- refuel ---
    "cmd.refuel.full": "Tank already full.",
    "cmd.refuel.confirm_prompt": "In the original, refuelling is always to full tank. Cost: ({max_fuel} - {fuel_now}) x {price} = {cost:.2f} Cr. Refuel? (y/n)",
    "cmd.refuel.cancelled": "Refuelling cancelled.",
    "cmd.refuel.no_credits": "Not enough credits: refuelling {room} units costs {cost:.2f} Cr, have {credits:.2f} Cr.",
    "cmd.refuel.done": "Refuelled {filled} units to full tank for {cost:.2f} Cr.",

    # --- save ---
    "cmd.save.usage": "Usage: save <file>",
    "cmd.save.error": "Save error: {exc}",
    "cmd.save.done": "Saved to {path}: galaxy {galaxy}, system #{index} {name}, {credits:.2f} Cr, fuel {fuel:.0f} units, cargo {cargo}/{hold} t.",

    # --- load ---
    "cmd.load.usage": "Usage: load <file>",
    "cmd.load.not_found": "File not found: {path}",
    "cmd.load.read_error": "File read error: {exc}",
    "cmd.load.invalid_json": "Invalid save file: expected a JSON object.",
    "cmd.load.invalid_data": "Invalid save data: {exc}",
    "cmd.load.done": "Loaded from {path}: galaxy {galaxy}, system #{index} {name}, {credits:.2f} Cr, fuel {fuel:.0f} units, cargo {cargo}/{hold} t.",

    # --- route ---
    "cmd.route.usage": "Usage: route <system index>",
    "cmd.route.bad_index": "System index must be an integer: {value!r}",
    "cmd.route.out_of_range": "System #{target} does not exist (valid range 0-{max}).",
    "cmd.route.unreachable": "Route to system #{target} is unreachable — it is out of jump range (<= 7.0 ly per jump).",
    "cmd.route.header": "Route to #{target} ({target_name}): {hops} hops, {fuel} units fuel, {refuel:.2f} Cr refuelling.",
    "cmd.route.leg": "  {hop}. {from_name} -> {to_name}  ({dist_ly:.1f} ly, {fuel} fuel)",
    "cmd.route.yes": "yes",
    "cmd.route.no": "no",
    "cmd.route.refuel_needed": "  Refuel needed: {refuel:.2f} Cr",
    "cmd.route.refuel_not_needed": "  No refuelling needed.",

    # --- profit ---
    "cmd.profit.no_deals": "No profitable deals found.",
    "cmd.profit.header": "Item           From        To          Profit/unit  Total profit   Fuel  Refuel     Net",
    "cmd.profit.error": "Error: {exc}",

    # --- profit-top ---
    "cmd.profit_top.bad_n": "N must be an integer: {value!r}",
    "cmd.profit_top.negative": "N must be positive.",

    # --- combat ---
    "cmd.combat.no_attack": "No pirate attack — no combat.",

    # --- combat (extended) ---
    "cmd.combat.encounter": "Pirates attack! Choose your action:",
    "cmd.combat.prompt": "  fight | escape | surrender > ",
    "cmd.combat.invalid_action": "Invalid action. Choose: fight | escape | surrender",
    "cmd.combat.no_encounter": "No pirate encounter — safe arrival.",
    "cmd.combat.fight_win": "You fought off the pirates.",
    "cmd.combat.fight_lose": "The pirates overpowered you: cargo and 20% of credits lost.",
    "cmd.combat.escape_success": "Escape jump succeeded ({fuel} units spent).",
    "cmd.combat.escape_fail": "Escape failed: pirates knocked off part of the cargo.",
    "cmd.combat.escape_no_fuel": "Not enough fuel to escape ({need} units needed).",
    "cmd.combat.surrender": "You surrendered: pirates took part of the credits and cargo.",
    "cmd.combat.destroyed": "Your ship has been destroyed! GAME OVER",
    "cmd.combat.ouch": "{item} DESTROYED!",
    "cmd.combat.restart": "Starting over with a new ship at TIBEDI...",
    "cmd.combat.shields_breached": "Shields breached! Damage to energy banks.",

    # --- info ---
    "cmd.info.title": "Planet description:",
    "cmd.info.empty": "No description available for this system.",
    "cmd.help.info": "  info              — planet description (goat soup)",

    # --- help ---
    "cmd.help.title": "Commands:",
    "cmd.help.status": "  status            — status: system, fuel, cargo, credits",
    "cmd.help.market": "  market            — market table of current system",
    "cmd.help.near": "  near              — systems in jump range",
    "cmd.help.buy": "  buy <item> <N>    — buy N units of a commodity",
    "cmd.help.sell": "  sell <item> <N>   — sell N units of a commodity",
    "cmd.help.jump": "  jump <index>      — hyperspace jump (index from near)",
    "cmd.help.refuel": "  refuel [N]        — refuel (without N — full tank)",
    "cmd.help.route": "  route <index>     — shortest route to a system",
    "cmd.help.profit": "  profit [item]    — profitable deals (top-10 or by item)",
    "cmd.help.profit_top": "  profit-top <N>    — top-N deals across all commodities",
    "cmd.help.combat": "  combat <action>   — combat: fight | escape | surrender",
    "cmd.help.save": "  save <file>       — save game to JSON",
    "cmd.help.load": "  load <file>       — load game from JSON",
    "cmd.help.lang": "  lang <code>       — switch interface language (en, ru, es)",
    "cmd.help.quit": "  quit              — quit the game",

    # --- lang ---
    "cmd.lang.current": "Current language: {name} ({code})",
    "cmd.lang.available": "Available: {list}",
    "cmd.lang.invalid": "Unknown language: {lang}. Available: {list}",
    "cmd.lang.switched": "Language switched to {name} ({code}).",

    # --- общие ошибки ---
    "error.unknown_command": "Unknown command: {command}. Type help.",
    "error.generic": "Error: {exc}",

    # --- _parse_item_qty ---
    "parse.usage": "Usage: {verb} <item> <quantity>",
    "parse.not_integer": "Quantity must be an integer: {value!r}",
    "parse.not_positive": "Quantity must be positive.",

    # --- renderer CLI (elite_renderer_cli.py) ---
    "render.jump.progress": "Jump in progress... {pct}%",
    "render.jump.complete": "Jump complete.",
    "render.combat.round": "Round {round_num}/{total_rounds}",
    "render.combat.enemy_damage": "Enemy damage: -{enemy_damage}",
    "render.combat.result_destroyed": "Result: {status} (ship destroyed)",
    "render.combat.result": "Result: {status}",
    "render.combat.attack": "!! PIRATE ATTACK !!",
    "render.combat.actions": "[F]ight  [E]scape  [S]urrender",
    "render.map.title": "Galaxy map — system #{index} {name}",
    "render.flight.title": "== FLIGHT MODE ==",
    "render.flight.system": "System: #{index} {name} (x={x}, y={y})",
    "render.flight.fuel_credits": "Fuel: {fuel:.1f}/{max_fuel}  Credits: {credits:.2f} Cr",
    "render.flight.defense": "FSH: {fsh}  ASH: {ash}  ENERGY: {energy}",
    "render.flight.cargo": "Cargo: {cargo}/{hold} t",

    # --- TUI (elite_tui.py) ---
    "tui.market.col_basis": "Basis",
    "tui.trend.below": "below base",
    "tui.trend.above": "above base",
    "tui.trend.base": "at base",
    "tui.buy.info": "{name}: price {price:.1f} Cr {trend}, max {mx} (limit: {limit}; credits {credits:.1f})",
    "tui.buy.preview": "{name}: {qty} x {price:.1f} = {cost:.2f} Cr, left {rest:.2f} Cr",
    "tui.sell.info": "{name}: price {price:.1f} Cr, in hold {hold}, income {income:.1f} Cr",
    "tui.sell.info_avg": "{name}: price {price:.1f} Cr, in hold {hold}, income {income:.1f} Cr, bought at {avg:.2f} Cr/unit, profit {profit:+.2f} Cr",
    "tui.sell.preview": "{name}: {qty} x {price:.1f} = {income:.2f} Cr",
    "tui.sell.preview_profit": "{name}: {qty} x {price:.1f} = {income:.2f} Cr, profit {profit:+.2f} Cr",
    "tui.sell.done_profit": "Sold {qty} {name} for {income:.2f} Cr (profit {profit:+.2f} Cr)",
    "tui.status.pirates": "PIRATES",
    "tui.buy.limit_credits": "credits",
    "tui.buy.limit_space": "cargo hold",
    "tui.buy.limit_stock": "stock",
    "tui.buy.limit_none": "out of stock",
    "tui.sell.all_confirm": "Will sell {positions} commodity type(s), {qty} units for {total:.2f} Cr. Press «Sell all» again to confirm.",
    "tui.map.col_trend": "Trend",
    "tui.undo.done": "Last trade undone",
    "tui.undo.none": "Nothing to undo",
    "tui.tradelog.title": "SESSION TRADES — F4",
    "tui.tradelog.empty": "No trades yet.",
    "tui.trade.bought": "bought {qty} {name} for {cost:.2f} Cr",
    "tui.trade.sold": "sold {qty} {name} for {income:.2f} Cr",
    "tui.notify.pirates": "PIRATE ATTACK!",
    "tui.notify.destroyed": "SHIP DESTROYED!",
    "tui.need_select": "Select a commodity first!",
    "tui.qty.required": "Enter a quantity!",
    "tui.qty.invalid": "Invalid number!",
    "tui.qty.positive": "Quantity must be > 0!",
    "tui.trade.failed": "Trade failed: {exc}",

    # --- TUI: общие кнопки и колонки ---
    "tui.btn.close": "Close [Esc]",
    "tui.btn.cancel": "Cancel [Esc]",
    "tui.btn.done": "Done [Esc]",
    "tui.btn.buy": "Buy [Enter]",
    "tui.btn.buy_max": "Buy max",
    "tui.btn.sell": "Sell [Enter]",
    "tui.btn.sell_all": "Sell all",
    "tui.btn.attack": "Attack [a]",
    "tui.btn.flee": "Flee [f]",
    "tui.btn.surrender": "Surrender [u]",
    "tui.btn.new_game": "New game [n]",
    "tui.btn.quit": "Quit [q]",
    "tui.btn.save": "Save [Enter]",
    "tui.btn.load": "Load [Enter]",
    "tui.col.commodity": "Commodity",
    "tui.col.price": "Price Cr",
    "tui.col.avail": "Avail",
    "tui.col.in_hold": "In hold",
    "tui.col.hold": "Hold",
    "tui.col.system": "System",
    "tui.col.ly": "ly",
    "tui.col.fuel": "Fuel",
    "tui.col.economy": "Economy",
    "tui.col.gov": "Gov",
    "tui.col.risk": "Risk",
    "tui.col.file": "File",
    "tui.col.size": "Size",
    "tui.col.modified": "Modified",

    # --- TUI: покупка ---
    "tui.buy.title": "MARKET — select a row, enter quantity, Enter (dialog stays open after purchase)",
    "tui.buy.qty_placeholder": "Quantity (e.g. 5)",
    "tui.buy.max_entered": "Max available: {mx} (you entered {qty})",
    "tui.buy.done": "Bought {qty} {name} for {cost:.2f} Cr",
    "tui.buy.unavailable": "{name}: not available for purchase (credits {credits:.1f})",

    # --- TUI: продажа ---
    "tui.sell.title": "HOLD — select cargo, enter quantity, Enter (dialog stays open after sale)",
    "tui.sell.qty_placeholder": "Quantity",
    "tui.sell.empty": "Hold is empty — nothing to sell!",
    "tui.sell.only_hold": "Only {hold} in hold (you entered {qty})",
    "tui.sell.done": "Sold {qty} {name} for {income:.2f} Cr",
    "tui.sell.failed": "Selling {name} failed: {exc}",
    "tui.sell.all_done": "Sold all: +{total:.2f} Cr",
    "tui.sell.all_done_profit": "Sold all: +{total:.2f} Cr (profit {profit:+.2f} Cr)",
    "tui.sell.all_done_info": "All cargo sold: +{total:.2f} Cr",
    "tui.sell.all_done_info_profit": "All cargo sold: +{total:.2f} Cr, profit {profit:+.2f} Cr",

    # --- TUI: прыжок ---
    "tui.jump.title": "GALAXY MAP — select a system (click or Enter)",
    "tui.jump.empty": "No reachable systems",

    # --- TUI: бой ---
    "tui.combat.title": "⚠ PIRATE ATTACK!",
    "tui.combat.info": "System: {name} ({gov})\nShields F:{fsh}/255 A:{ash}/255  Energy: {eng}\nCredits: {credits:.1f} Cr\nCargo: {cargo}/{hold}t",
    "tui.combat.log": "Combat ({action}): {message}",

    # --- TUI: конец игры ---
    "tui.gameover.title": "💀 SHIP DESTROYED 💀",
    "tui.gameover.text": "Game over.",
    "tui.gameover.log": "SHIP DESTROYED!",

    # --- TUI: инфо о системе ---
    "tui.info.title": "{name} (Galaxy {galaxy})",
    "tui.info.body": "Economy: {economy}\nGovernment: {gov}\nTech level: {tech}\nPopulation: {pop:.1f} billion\nShields F:{fsh}/255 A:{ash}/255  Energy: {eng}\n\n{description}",

    # --- TUI: файлы ---
    "tui.file.save_title": "SAVE GAME (.elite)",
    "tui.file.load_title": "LOAD GAME (.elite)",
    "tui.file.name_placeholder": "File name (e.g. mysave.elite)",
    "tui.file.name_required": "Enter a file name!",
    "tui.file.name_invalid": "Invalid name: use a name without paths or slashes!",

    # --- TUI: справка ---
    "tui.help.title": "HELP — ELITE: HARMLESS",
    "tui.help.text": "CONTROLS\n  b — buy commodity          s — sell commodity\n  «Sell all» in the sell dialog — sell the whole hold\n  unconditionally at current system prices\n  Double-click a commodity in the MARKET list — buy dialog\n  for that commodity (the dialog has a «Buy max» button)\n  j — jump to system          i — system description\n  h — this help               r — refuel to full\n  w — wait a turn (shields +1)  q — quit\n  F5 — quick save             F9 — quick load (quicksave.elite)\n  F2 — save to file           F3 — load (*.elite)\n  F4 — session trade log\n  In dialogs: Esc — cancel, Ctrl+Z — undo last trade\n  In combat: a — attack, f — flee, u — surrender\n\nHOW TO PLAY\n  The goal is to earn credits: buy commodities cheap and sell\n  them at a higher price in another system. A jump consumes\n  fuel (0.2 Cr per unit); refuelling is always to a full tank.\n  Market and danger depend on the system government: pirates\n  often attack in anarchies. Attack is risky with weak shields,\n  escape is more successful with a full tank, surrender means\n  losing cargo and part of the credits.\n  «Alien goods» are not available on the market.\n\nSAVES AND LOG\n  quicksave.elite — F5/F9 keys; named saves — *.elite (F2/F3).\n  All game events are written to the elite_events.db database.",

    # --- TUI: главное окно ---
    "tui.panel.market": "MARKET",
    "tui.panel.galaxy": "GALAXY MAP",
    "tui.btn.buy_key": "Buy [b]",
    "tui.btn.sell_key": "Sell [s]",
    "tui.btn.jump_key": "Jump [j]",
    "tui.btn.refuel_key": "Refuel [r]",
    "tui.btn.wait_key": "Wait [w]",
    "tui.btn.help_key": "Help [h]",
    "tui.btn.trades_key": "Trades [F4]",
    "tui.btn.quit_key": "Quit [q]",
    "tui.welcome": "Welcome to pyElite!",
    "tui.start": "Start: {name} (Galaxy {galaxy})",
    "tui.keys_hint": "Keys: b=buy s=sell j=jump i=info h=help r=refuel w=wait q=quit | F5/F9 quick save/load, F2/F3 files (.elite)",

    # --- TUI: статус-бар ---
    "tui.status.bar": "Cr: {credits:.1f}  |  Fuel: {fuel}/{max}  |  Cargo: {cargo}/{hold}t  |  Shields F:{fsh} A:{ash}  Energy: {eng}",

    # --- TUI: действия ---
    "tui.refuel.full": "Tank already full.",
    "tui.refuel.failed": "Refuelling failed: {reason}",
    "tui.refuel.done": "Refuelled to full (-{cost:.2f} Cr)",
    "tui.wait.done": "Turn passed. Shields +1.",
    "tui.save.done": "Saved: {path}",
    "tui.save.failed": "Save failed: {exc}",
    "tui.quicksave.failed": "Quick save failed: {exc}",
    "tui.quicksave.done": "Quick save -> {path}",
    "tui.load.not_found": "File not found: {path}",
    "tui.load.failed": "Load failed: {exc}",
    "tui.load.done": "Loaded: {path} -> {name} ({credits:.1f} Cr)",
    "tui.jump.failed": "Jump failed: {reason}",
    "tui.jump.done": "Jump {old} -> {new} ({dist:.1f} ly, fuel -{cost})",
    "tui.new_game": "New game started!",
}

RU: Dict[str, str] = {
    # --- Заголовок / выход ---
    "app.welcome": "pyElite — торговля и гиперпрыжки. Введите help.",
    "app.farewell": "До встречи, командир.",

    # --- status ---
    "cmd.status.system": "Система:     №{index} {name}",
    "cmd.status.economy": "Экономика:   {name}",
    "cmd.status.government": "Правительство: {name}",
    "cmd.status.fuel": "Топливо:     {fuel}/{max_fuel} ед. ({fuel_ly:.1f}/7.0 св. лет)",
    "cmd.status.cargo": "Груз:        {cargo}/{hold} т",
    "cmd.status.credits": "Кредиты:     {credits:.2f} Cr",

    # --- status (defense) ---
    "cmd.status.defense": "Защита:     FSH {fsh}/255 ASH {ash}/255 EN {energy}/255",

    # --- market ---
    "cmd.market.title": "Рынок системы №{index} {name} ({economy})",
    "cmd.market.header": "Товар           Ед.   В наличии       Покупка, Cr  Продажа, Cr",
    "cmd.market.separator": "-----------------------------------------------------",

    # --- near ---
    "cmd.near.title": "Системы в радиусе прыжка (топливо {fuel} ед.):",
    "cmd.near.empty": "  Ни одна система не достижима — заправьтесь.",
    "cmd.near.header": "  #  Имя         Расстояние  Расход",
    "cmd.near.row": "{index:>3}  {name:<10}{dist_ly:>10.1f} св. лет  расход: {cost} ед. ({cost_ly:.1f} св. лет)",

    # --- buy ---
    "cmd.buy.done": "Куплено {qty} {name} за {cost:.2f} Cr. Кредиты: {credits:.2f} Cr; груз: {cargo}/{hold} т.",
    "cmd.buy.error": "Ошибка: {exc}",

    # --- sell ---
    "cmd.sell.done": "Продано {qty} {name} за {income:.2f} Cr. Кредиты: {credits:.2f} Cr; груз: {cargo}/{hold} т.",
    "cmd.sell.error": "Ошибка: {exc}",

    # --- jump ---
    "cmd.jump.usage": "Использование: jump <индекс системы> (индексы из near)",
    "cmd.jump.bad_index": "Индекс системы должен быть целым числом: {value!r}",
    "cmd.jump.out_of_range": "Система №{target} не существует (допустимо 0-{max}).",
    "cmd.jump.already_here": "Вы уже в этой системе.",
    "cmd.jump.too_far": "Слишком далеко: {dist_ly:.1f} св. лет (предел движка).",
    "cmd.jump.no_fuel": "Не хватает топлива: нужно {cost} ед., есть {fuel} ед.",
    "cmd.jump.complete": "Прыжок выполнен. Расстояние: {dist_ly:.1f} св. лет; расход: {cost} ед.; топливо: {fuel} ед.",
    "cmd.jump.arrived": "Прибыли в систему №{index} {name} ({economy}).",

    # --- refuel ---
    "cmd.refuel.full": "Бак уже полон.",
    "cmd.refuel.confirm_prompt": "В оригинале заправка только до полного. Стоимость: ({max_fuel} - {fuel_now}) x {price} = {cost:.2f} Cr. Заправить? (y/n)",
    "cmd.refuel.cancelled": "Заправка отменена.",
    "cmd.refuel.no_credits": "Не хватает кредитов: заправка {room} ед. стоит {cost:.2f} Cr, есть {credits:.2f} Cr.",
    "cmd.refuel.done": "Заправлено {filled} ед. до полного бака за {cost:.2f} Cr.",

    # --- save ---
    "cmd.save.usage": "Использование: save <файл>",
    "cmd.save.error": "Ошибка сохранения: {exc}",
    "cmd.save.done": "Сохранено в {path}: галактика {galaxy}, система №{index} {name}, {credits:.2f} Cr, топливо {fuel:.0f} ед., груз {cargo}/{hold} т.",

    # --- load ---
    "cmd.load.usage": "Использование: load <файл>",
    "cmd.load.not_found": "Файл не найден: {path}",
    "cmd.load.read_error": "Ошибка чтения файла: {exc}",
    "cmd.load.invalid_json": "Некорректный файл сохранения: ожидается JSON-объект.",
    "cmd.load.invalid_data": "Некорректное сохранение: {exc}",
    "cmd.load.done": "Загружено из {path}: галактика {galaxy}, система №{index} {name}, {credits:.2f} Cr, топливо {fuel:.0f} ед., груз {cargo}/{hold} т.",

    # --- route ---
    "cmd.route.usage": "Использование: route <индекс системы>",
    "cmd.route.bad_index": "Индекс системы должен быть целым числом: {value!r}",
    "cmd.route.out_of_range": "Система №{target} не существует (допустимо 0-{max}).",
    "cmd.route.unreachable": "Маршрут к системе №{target} невозможен — вне радиуса прыжка (<= 7.0 св. лет за прыжок).",
    "cmd.route.header": "Маршрут к №{target} ({target_name}): {hops} прыжков, {fuel} ед. топлива, {refuel:.2f} Cr заправка.",
    "cmd.route.leg": "  {hop}. {from_name} -> {to_name}  ({dist_ly:.1f} св. лет, {fuel} топлива)",
    "cmd.route.yes": "да",
    "cmd.route.no": "нет",
    "cmd.route.refuel_needed": "  Заправка: {refuel:.2f} Cr",
    "cmd.route.refuel_not_needed": "  Заправка не требуется.",

    # --- profit ---
    "cmd.profit.no_deals": "Выгодных сделок не найдено.",
    "cmd.profit.header": "Товар          Откуда      Куда        Прибыль/ед.  Прибыль итого  Топливо  Заправка  Чистая",
    "cmd.profit.error": "Ошибка: {exc}",

    # --- profit-top ---
    "cmd.profit_top.bad_n": "N должно быть целым числом: {value!r}",
    "cmd.profit_top.negative": "N должно быть больше нуля.",

    # --- combat ---
    "cmd.combat.no_attack": "Пираты не атакуют — боя нет.",

    # --- combat (extended) ---
    "cmd.combat.encounter": "Пираты атакуют! Выберите действие:",
    "cmd.combat.prompt": "  fight | escape | surrender > ",
    "cmd.combat.invalid_action": "Недопустимое действие. Выберите: fight | escape | surrender",
    "cmd.combat.no_encounter": "Пиратов нет — прибытие безопасное.",
    "cmd.combat.fight_win": "Вы отбились от пиратов.",
    "cmd.combat.fight_lose": "Пираты одолели: потеряны груз и 20% кредитов.",
    "cmd.combat.escape_success": "Побег удался ({fuel} ед. топлива потрачено).",
    "cmd.combat.escape_fail": "Побег не удался: пираты сбили часть груза.",
    "cmd.combat.escape_no_fuel": "Недостаточно топлива для побега (нужно {need} ед.).",
    "cmd.combat.surrender": "Вы сдались: пираты забрали часть кредитов и груза.",
    "cmd.combat.destroyed": "Ваш корабль уничтожен! ИГРА ОКОНЧЕНА",
    "cmd.combat.ouch": "{item} УНИЧТОЖЕН(О)!",
    "cmd.combat.restart": "Новый корабль, начинаем заново с ТИБЕДИ...",
    "cmd.combat.shields_breached": "Щиты пробиты! Урон по энергобанкам.",

    # --- info ---
    "cmd.info.title": "Описание планеты:",
    "cmd.info.empty": "Описание для этой системы недоступно.",
    "cmd.help.info": "  info              — описание планеты (goat soup)",

    # --- help ---
    "cmd.help.title": "Команды:",
    "cmd.help.status": "  status            — статус: система, топливо, груз, кредиты",
    "cmd.help.market": "  market            — таблица рынка текущей системы",
    "cmd.help.near": "  near              — системы в радиусе прыжка",
    "cmd.help.buy": "  buy <item> <N>    — купить N единиц товара",
    "cmd.help.sell": "  sell <item> <N>   — продать N единиц товара",
    "cmd.help.jump": "  jump <index>      — гиперпрыжок (индекс из near)",
    "cmd.help.refuel": "  refuel [N]        — заправка (без N — до полного бака)",
    "cmd.help.route": "  route <index>     — кратчайший маршрут к системе",
    "cmd.help.profit": "  profit [item]    — выгодные сделки (топ-10 или по товару)",
    "cmd.help.profit_top": "  profit-top <N>    — топ-N сделок по всем товарам",
    "cmd.help.combat": "  combat <action>   — бой: fight | escape | surrender",
    "cmd.help.save": "  save <file>       — сохранить игру в JSON",
    "cmd.help.load": "  load <file>       — загрузить игру из JSON",
    "cmd.help.lang": "  lang <code>       — переключить язык интерфейса (en, ru, es)",
    "cmd.help.quit": "  quit              — выйти из игры",

    # --- lang ---
    "cmd.lang.current": "Текущий язык: {name} ({code})",
    "cmd.lang.available": "Доступно: {list}",
    "cmd.lang.invalid": "Неизвестный язык: {lang}. Доступно: {list}",
    "cmd.lang.switched": "Язык переключён на {name} ({code}).",

    # --- общие ошибки ---
    "error.unknown_command": "Неизвестная команда: {command}. Введите help.",
    "error.generic": "Ошибка: {exc}",

    # --- _parse_item_qty ---
    "parse.usage": "Использование: {verb} <товар> <количество>",
    "parse.not_integer": "Количество должно быть целым числом: {value!r}",
    "parse.not_positive": "Количество должно быть больше нуля.",

    # --- renderer CLI (elite_renderer_cli.py) ---
    "render.jump.progress": "Прыжок в процессе... {pct}%",
    "render.jump.complete": "Прыжок завершён.",
    "render.combat.round": "Раунд {round_num}/{total_rounds}",
    "render.combat.enemy_damage": "Урон по врагу: -{enemy_damage}",
    "render.combat.result_destroyed": "Результат: {status} (корабль уничтожен)",
    "render.combat.result": "Результат: {status}",
    "render.combat.attack": "!! ПИРАТСКАЯ АТАКА !!",
    "render.combat.actions": "[F]бой  [E]побег  [S]сдаться",
    "render.map.title": "Карта галактики — система №{index} {name}",
    "render.flight.title": "== РЕЖИМ ПОЛЁТА ==",
    "render.flight.system": "Система: №{index} {name} (x={x}, y={y})",
    "render.flight.fuel_credits": "Топливо: {fuel:.1f}/{max_fuel}  Кредиты: {credits:.2f} Cr",
    "render.flight.defense": "FSH: {fsh}  ASH: {ash}  ENERGY: {energy}",
    "render.flight.cargo": "Груз: {cargo}/{hold} т",

    # --- TUI (elite_tui.py) ---
    "tui.market.col_basis": "Базис",
    "tui.trend.below": "▼ дешевле базы",
    "tui.trend.above": "▲ дороже базы",
    "tui.trend.base": "≈ у базы",
    "tui.buy.info": "{name}: цена {price:.1f} Cr {trend}, макс. {mx} (лимит: {limit}; кредиты {credits:.1f})",
    "tui.buy.preview": "{name}: {qty} × {price:.1f} = {cost:.2f} Cr, останется {rest:.2f} Cr",
    "tui.sell.info": "{name}: цена {price:.1f} Cr, в трюме {hold}, доход {income:.1f} Cr",
    "tui.sell.info_avg": "{name}: цена {price:.1f} Cr, в трюме {hold}, доход {income:.1f} Cr, закупка {avg:.2f} Cr/шт, прибыль {profit:+.2f} Cr",
    "tui.sell.preview": "{name}: {qty} × {price:.1f} = {income:.2f} Cr",
    "tui.sell.preview_profit": "{name}: {qty} × {price:.1f} = {income:.2f} Cr, прибыль {profit:+.2f} Cr",
    "tui.sell.done_profit": "Продано {qty} {name} за {income:.2f} Cr (прибыль {profit:+.2f} Cr)",
    "tui.status.pirates": "ПИРАТЫ",
    "tui.buy.limit_credits": "кредиты",
    "tui.buy.limit_space": "трюм",
    "tui.buy.limit_stock": "наличие",
    "tui.buy.limit_none": "нет в наличии",
    "tui.sell.all_confirm": "Будет продано позиций: {positions}, единиц: {qty} на {total:.2f} Cr. Нажмите «Продать все» ещё раз для подтверждения.",
    "tui.map.col_trend": "Тренд",
    "tui.undo.done": "Последняя сделка отменена",
    "tui.undo.none": "Нечего отменять",
    "tui.tradelog.title": "СДЕЛКИ СЕССИИ — F4",
    "tui.tradelog.empty": "Сделок пока не было.",
    "tui.trade.bought": "куплено {qty} {name} за {cost:.2f} Cr",
    "tui.trade.sold": "продано {qty} {name} за {income:.2f} Cr",
    "tui.notify.pirates": "ПИРАТЫ НАПАДАЮТ!",
    "tui.notify.destroyed": "КОРАБЛЬ УНИЧТОЖЕН!",
    "tui.need_select": "Сначала выберите товар!",
    "tui.qty.required": "Введите количество!",
    "tui.qty.invalid": "Некорректное число!",
    "tui.qty.positive": "Количество должно быть > 0!",
    "tui.trade.failed": "Сделка не удалась: {exc}",

    # --- TUI: общие кнопки и колонки ---
    "tui.btn.close": "Закрыть [Esc]",
    "tui.btn.cancel": "Отмена [Esc]",
    "tui.btn.done": "Готово [Esc]",
    "tui.btn.buy": "Купить [Enter]",
    "tui.btn.buy_max": "Купить на все",
    "tui.btn.sell": "Продать [Enter]",
    "tui.btn.sell_all": "Продать все",
    "tui.btn.attack": "Атака [a]",
    "tui.btn.flee": "Побег [f]",
    "tui.btn.surrender": "Сдача [u]",
    "tui.btn.new_game": "Новая игра [n]",
    "tui.btn.quit": "Выход [q]",
    "tui.btn.save": "Сохранить [Enter]",
    "tui.btn.load": "Загрузить [Enter]",
    "tui.col.commodity": "Товар",
    "tui.col.price": "Цена Cr",
    "tui.col.avail": "Наличие",
    "tui.col.in_hold": "В трюме",
    "tui.col.hold": "Трюм",
    "tui.col.system": "Система",
    "tui.col.ly": "Св.л.",
    "tui.col.fuel": "Топливо",
    "tui.col.economy": "Экономика",
    "tui.col.gov": "Правитель",
    "tui.col.risk": "Риск",
    "tui.col.file": "Файл",
    "tui.col.size": "Размер",
    "tui.col.modified": "Изменён",

    # --- TUI: покупка ---
    "tui.buy.title": "MARKET — выберите строку, введите количество, Enter (диалог не закрывается после покупки)",
    "tui.buy.qty_placeholder": "Количество (например 5)",
    "tui.buy.max_entered": "Макс. доступно: {mx} (вы ввели {qty})",
    "tui.buy.done": "Куплено {qty} {name} за {cost:.2f} Cr",
    "tui.buy.unavailable": "{name}: недоступно для покупки (кредиты {credits:.1f})",

    # --- TUI: продажа ---
    "tui.sell.title": "ТРЮМ — выберите груз, введите количество, Enter (диалог не закрывается после продажи)",
    "tui.sell.qty_placeholder": "Количество",
    "tui.sell.empty": "Трюм пуст — нечего продавать!",
    "tui.sell.only_hold": "В трюме только {hold} (вы ввели {qty})",
    "tui.sell.done": "Продано {qty} {name} за {income:.2f} Cr",
    "tui.sell.failed": "Продажа {name} не удалась: {exc}",
    "tui.sell.all_done": "Продано всё: +{total:.2f} Cr",
    "tui.sell.all_done_profit": "Продано всё: +{total:.2f} Cr (прибыль {profit:+.2f} Cr)",
    "tui.sell.all_done_info": "Весь груз продан: +{total:.2f} Cr",
    "tui.sell.all_done_info_profit": "Весь груз продан: +{total:.2f} Cr, прибыль {profit:+.2f} Cr",

    # --- TUI: прыжок ---
    "tui.jump.title": "КАРТА ГАЛАКТИКИ — выберите систему (клик или Enter)",
    "tui.jump.empty": "Нет достижимых систем",

    # --- TUI: бой ---
    "tui.combat.title": "⚠ АТАКА ПИРАТОВ!",
    "tui.combat.info": "Система: {name} ({gov})\nЩиты F:{fsh}/255 A:{ash}/255  Энергия: {eng}\nКредиты: {credits:.1f} Cr\nГруз: {cargo}/{hold}t",
    "tui.combat.log": "Бой ({action}): {message}",

    # --- TUI: конец игры ---
    "tui.gameover.title": "💀 КОРАБЛЬ УНИЧТОЖЕН 💀",
    "tui.gameover.text": "Игра окончена.",
    "tui.gameover.log": "КОРАБЛЬ УНИЧТОЖЕН!",

    # --- TUI: инфо о системе ---
    "tui.info.title": "{name} (Галактика {galaxy})",
    "tui.info.body": "Экономика: {economy}\nПравительство: {gov}\nТех. уровень: {tech}\nНаселение: {pop:.1f} млрд\nЩиты F:{fsh}/255 A:{ash}/255  Энергия: {eng}\n\n{description}",

    # --- TUI: файлы ---
    "tui.file.save_title": "СОХРАНИТЬ ИГРУ (.elite)",
    "tui.file.load_title": "ЗАГРУЗИТЬ ИГРУ (.elite)",
    "tui.file.name_placeholder": "Имя файла (например mysave.elite)",
    "tui.file.name_required": "Введите имя файла!",
    "tui.file.name_invalid": "Недопустимое имя: укажите имя без путей и слэшей!",

    # --- TUI: справка ---
    "tui.help.title": "СПРАВКА — ELITE: HARMLESS",
    "tui.help.text": "УПРАВЛЕНИЕ\n  b — купить товар           s — продать товар\n  «Продать все» в диалоге продажи — продать весь груз\n  безусловно по ценам текущей звёздной системы\n  Двойной клик по товару в списке «РЫНОК» — диалог покупки\n  этого товара (в диалоге есть кнопка «Купить на все»)\n  j — прыжок в систему       i — описание системы\n  h — эта справка            r — заправка до полного\n  w — ждать ход (щиты +1)    q — выход\n  F5 — быстрый сейв          F9 — быстрый лоад (quicksave.elite)\n  F2 — сохранение в файл     F3 — загрузка (*.elite)\n  F4 — журнал сделок сессии\n  В диалогах: Esc — отмена, Ctrl+Z — отменить последнюю сделку\n  В бою: a — атака, f — побег, u — сдача\n\nКАК ИГРАТЬ\n  Цель — заработать кредиты: покупайте товары дёшево и продавайте\n  дороже в другой системе. Прыжок расходует топливо (0.2 Cr за\n  единицу); заправка — всегда до полного бака.\n  Рынок и опасность зависят от правительства системы: в анархиях\n  часто нападают пираты. Атака рискованна при слабых щитах, побег\n  успешнее с полным баком, сдача — потеря груза и части кредитов.\n  «Товары чужих» недоступны на рынке.\n\nСОХРАНЕНИЯ И ЖУРНАЛ\n  quicksave.elite — клавиши F5/F9; именованные сейвы — *.elite\n  (F2/F3). Все события игры пишутся в базу elite_events.db.",

    # --- TUI: главное окно ---
    "tui.panel.market": "РЫНОК",
    "tui.panel.galaxy": "КАРТА ГАЛАКТИКИ",
    "tui.btn.buy_key": "Купить [b]",
    "tui.btn.sell_key": "Продать [s]",
    "tui.btn.jump_key": "Прыжок [j]",
    "tui.btn.refuel_key": "Заправка [r]",
    "tui.btn.wait_key": "Ждать [w]",
    "tui.btn.help_key": "Справка [h]",
    "tui.btn.trades_key": "Сделки [F4]",
    "tui.btn.quit_key": "Выход [q]",
    "tui.welcome": "Добро пожаловать в pyElite!",
    "tui.start": "Старт: {name} (Галактика {galaxy})",
    "tui.keys_hint": "Клавиши: b=купить s=продать j=прыжок i=инфо h=справка r=заправка w=ждать q=выход | F5/F9 quick save/load, F2/F3 файлы (.elite)",

    # --- TUI: статус-бар ---
    "tui.status.bar": "Cr: {credits:.1f}  |  Топливо: {fuel}/{max}  |  Груз: {cargo}/{hold}t  |  Щиты F:{fsh} A:{ash}  Энергия: {eng}",

    # --- TUI: действия ---
    "tui.refuel.full": "Бак уже полон.",
    "tui.refuel.failed": "Заправка не удалась: {reason}",
    "tui.refuel.done": "Заправка до полного (-{cost:.2f} Cr)",
    "tui.wait.done": "Прошёл ход. Щиты +1.",
    "tui.save.done": "Сохранено: {path}",
    "tui.save.failed": "Сохранение не удалось: {exc}",
    "tui.quicksave.failed": "Быстрый сейв не удался: {exc}",
    "tui.quicksave.done": "Быстрый сейв -> {path}",
    "tui.load.not_found": "Файл не найден: {path}",
    "tui.load.failed": "Загрузка не удалась: {exc}",
    "tui.load.done": "Загружено: {path} -> {name} ({credits:.1f} Cr)",
    "tui.jump.failed": "Прыжок не удался: {reason}",
    "tui.jump.done": "Прыжок {old} -> {new} ({dist:.1f} св.л., топливо -{cost})",
    "tui.new_game": "Новая игра началась!",
}

ES: Dict[str, str] = {
    # --- Заголовок / выход ---
    "app.welcome": "pyElite — comercio y saltos hiperespaciales. Escribe help.",
    "app.farewell": "Hasta la vista, Comandante.",

    # --- status ---
    "cmd.status.system": "Sistema:      #{index} {name}",
    "cmd.status.economy": "Economía:     {name}",
    "cmd.status.government": "Gobierno:     {name}",
    "cmd.status.fuel": "Combustible:  {fuel}/{max_fuel} ud. ({fuel_ly:.1f}/7.0 a.l.)",
    "cmd.status.cargo": "Carga:        {cargo}/{hold} t",
    "cmd.status.credits": "Créditos:     {credits:.2f} Cr",

    # --- status (defense) ---
    "cmd.status.defense": "Defensa:    FSH {fsh}/255 ASH {ash}/255 EN {energy}/255",

    # --- market ---
    "cmd.market.title": "Mercado en sistema #{index} {name} ({economy})",
    "cmd.market.header": "Artículo        Ud.   Disponible    Compra, Cr   Venta, Cr",
    "cmd.market.separator": "-----------------------------------------------------",

    # --- near ---
    "cmd.near.title": "Sistemas en alcance de salto (combustible {fuel} ud.):",
    "cmd.near.empty": "  Ningún sistema alcanzable — repostar primero.",
    "cmd.near.header": "  #  Nombre      Distancia  Combustible",
    "cmd.near.row": "{index:>3}  {name:<10}{dist_ly:>10.1f} a.l.  coste: {cost} ud. ({cost_ly:.1f} a.l.)",

    # --- buy ---
    "cmd.buy.done": "Comprado {qty} {name} por {cost:.2f} Cr. Créditos: {credits:.2f} Cr; carga: {cargo}/{hold} t.",
    "cmd.buy.error": "Error: {exc}",

    # --- sell ---
    "cmd.sell.done": "Vendido {qty} {name} por {income:.2f} Cr. Créditos: {credits:.2f} Cr; carga: {cargo}/{hold} t.",
    "cmd.sell.error": "Error: {exc}",

    # --- jump ---
    "cmd.jump.usage": "Uso: jump <índice de sistema> (índices de near)",
    "cmd.jump.bad_index": "El índice de sistema debe ser un entero: {value!r}",
    "cmd.jump.out_of_range": "El sistema #{target} no existe (rango válido 0-{max}).",
    "cmd.jump.already_here": "Ya estás en este sistema.",
    "cmd.jump.too_far": "Demasiado lejos: {dist_ly:.1f} a.l. (límite del motor).",
    "cmd.jump.no_fuel": "Combustible insuficiente: necesita {cost} ud., hay {fuel} ud.",
    "cmd.jump.complete": "Salto completado. Distancia: {dist_ly:.1f} a.l.; coste: {cost} ud.; combustible: {fuel} ud.",
    "cmd.jump.arrived": "Llegada al sistema #{index} {name} ({economy}).",

    # --- refuel ---
    "cmd.refuel.full": "Depósito ya lleno.",
    "cmd.refuel.confirm_prompt": "En el original, el repostaje siempre llena el depósito. Coste: ({max_fuel} - {fuel_now}) x {price} = {cost:.2f} Cr. ¿Repostar? (y/n)",
    "cmd.refuel.cancelled": "Repostaje cancelado.",
    "cmd.refuel.no_credits": "Créditos insuficientes: repostar {room} ud. cuesta {cost:.2f} Cr, hay {credits:.2f} Cr.",
    "cmd.refuel.done": "Repuesto {filled} ud. hasta llenar el depósito por {cost:.2f} Cr.",

    # --- save ---
    "cmd.save.usage": "Uso: save <archivo>",
    "cmd.save.error": "Error de guardado: {exc}",
    "cmd.save.done": "Guardado en {path}: galaxia {galaxy}, sistema #{index} {name}, {credits:.2f} Cr, combustible {fuel:.0f} ud., carga {cargo}/{hold} t.",

    # --- load ---
    "cmd.load.usage": "Uso: load <archivo>",
    "cmd.load.not_found": "Archivo no encontrado: {path}",
    "cmd.load.read_error": "Error de lectura: {exc}",
    "cmd.load.invalid_json": "Archivo de guardado inválido: se esperaba un objeto JSON.",
    "cmd.load.invalid_data": "Datos de guardado inválidos: {exc}",
    "cmd.load.done": "Cargado de {path}: galaxia {galaxy}, sistema #{index} {name}, {credits:.2f} Cr, combustible {fuel:.0f} ud., carga {cargo}/{hold} t.",

    # --- route ---
    "cmd.route.usage": "Uso: route <índice de sistema>",
    "cmd.route.bad_index": "El índice de sistema debe ser un entero: {value!r}",
    "cmd.route.out_of_range": "El sistema #{target} no existe (rango válido 0-{max}).",
    "cmd.route.unreachable": "Ruta al sistema #{target} inalcanzable — fuera del alcance de salto (<= 7.0 a.l. por salto).",
    "cmd.route.header": "Ruta a #{target} ({target_name}): {hops} saltos, {fuel} ud. combustible, {refuel:.2f} Cr repostaje.",
    "cmd.route.leg": "  {hop}. {from_name} -> {to_name}  ({dist_ly:.1f} a.l., {fuel} combustible)",
    "cmd.route.yes": "sí",
    "cmd.route.no": "no",
    "cmd.route.refuel_needed": "  Repostaje necesario: {refuel:.2f} Cr",
    "cmd.route.refuel_not_needed": "  No requiere repostaje.",

    # --- profit ---
    "cmd.profit.no_deals": "No se encontraron ofertas rentables.",
    "cmd.profit.header": "Artículo       Origen      Destino     Beneficio/ud. Beneficio total  Combust.  Repostaje  Neto",
    "cmd.profit.error": "Error: {exc}",

    # --- profit-top ---
    "cmd.profit_top.bad_n": "N debe ser un entero: {value!r}",
    "cmd.profit_top.negative": "N debe ser positivo.",

    # --- combat ---
    "cmd.combat.no_attack": "Sin ataque pirata — sin combate.",

    # --- combat (extended) ---
    "cmd.combat.encounter": "¡Piratas atacan! Elige tu acción:",
    "cmd.combat.prompt": "  fight | escape | surrender > ",
    "cmd.combat.invalid_action": "Acción inválida. Elige: fight | escape | surrender",
    "cmd.combat.no_encounter": "Sin encuentro pirata — llegada segura.",
    "cmd.combat.fight_win": "Repeliste a los piratas.",
    "cmd.combat.fight_lose": "Los piratas te vencieron: perdiste carga y 20% de créditos.",
    "cmd.combat.escape_success": "Escape exitoso ({fuel} ud. de combustible gastadas).",
    "cmd.combat.escape_fail": "Escape fallido: los piratas derribaron parte de la carga.",
    "cmd.combat.escape_no_fuel": "Combustible insuficiente para escapar (necesitas {need} ud.).",
    "cmd.combat.surrender": "Te rendiste: los piratas tomaron parte de los créditos y la carga.",
    "cmd.combat.destroyed": "¡Tu nave ha sido destruida! GAME OVER",
    "cmd.combat.ouch": "¡{item} DESTRUIDO!",
    "cmd.combat.restart": "Nueva nave, empezando de nuevo en TIBEDI...",
    "cmd.combat.shields_breached": "¡Escudos perforados! Daño a los bancos de energía.",

    # --- info ---
    "cmd.info.title": "Descripción del planeta:",
    "cmd.info.empty": "No hay descripción para este sistema.",
    "cmd.help.info": "  info              — descripción del planeta (goat soup)",

    # --- help ---
    "cmd.help.title": "Comandos:",
    "cmd.help.status": "  status            — estado: sistema, combustible, carga, créditos",
    "cmd.help.market": "  market            — tabla de mercado del sistema actual",
    "cmd.help.near": "  near              — sistemas en alcance de salto",
    "cmd.help.buy": "  buy <item> <N>    — comprar N unidades de un artículo",
    "cmd.help.sell": "  sell <item> <N>   — vender N unidades de un artículo",
    "cmd.help.jump": "  jump <index>      — salto hiperespacial (índice de near)",
    "cmd.help.refuel": "  refuel [N]        — repostar (sin N — depósito lleno)",
    "cmd.help.route": "  route <index>     — ruta más corta a un sistema",
    "cmd.help.profit": "  profit [item]    — ofertas rentables (top-10 o por artículo)",
    "cmd.help.profit_top": "  profit-top <N>    — top-N ofertas de todos los artículos",
    "cmd.help.combat": "  combat <action>   — combate: fight | escape | surrender",
    "cmd.help.save": "  save <file>       — guardar partida en JSON",
    "cmd.help.load": "  load <file>       — cargar partida de JSON",
    "cmd.help.lang": "  lang <code>       — cambiar idioma de interfaz (en, ru, es)",
    "cmd.help.quit": "  quit              — salir del juego",

    # --- lang ---
    "cmd.lang.current": "Idioma actual: {name} ({code})",
    "cmd.lang.available": "Disponibles: {list}",
    "cmd.lang.invalid": "Idioma desconocido: {lang}. Disponibles: {list}",
    "cmd.lang.switched": "Idioma cambiado a {name} ({code}).",

    # --- errores comunes ---
    "error.unknown_command": "Comando desconocido: {command}. Escribe help.",
    "error.generic": "Error: {exc}",

    # --- _parse_item_qty ---
    "parse.usage": "Uso: {verb} <artículo> <cantidad>",
    "parse.not_integer": "La cantidad debe ser un entero: {value!r}",
    "parse.not_positive": "La cantidad debe ser positiva.",

    # --- renderer CLI (elite_renderer_cli.py) ---
    "render.jump.progress": "Salto en curso... {pct}%",
    "render.jump.complete": "Salto completado.",
    "render.combat.round": "Ronda {round_num}/{total_rounds}",
    "render.combat.enemy_damage": "Daño al enemigo: -{enemy_damage}",
    "render.combat.result_destroyed": "Resultado: {status} (nave destruida)",
    "render.combat.result": "Resultado: {status}",
    "render.combat.attack": "¡¡ ATAQUE PIRATA !!",
    "render.combat.actions": "[F]luchar  [E]scapar  [S]rendirse",
    "render.map.title": "Mapa de la galaxia — sistema #{index} {name}",
    "render.flight.title": "== MODO VUELO ==",
    "render.flight.system": "Sistema: #{index} {name} (x={x}, y={y})",
    "render.flight.fuel_credits": "Combustible: {fuel:.1f}/{max_fuel}  Créditos: {credits:.2f} Cr",
    "render.flight.defense": "FSH: {fsh}  ASH: {ash}  ENERGY: {energy}",
    "render.flight.cargo": "Carga: {cargo}/{hold} t",

    # --- TUI (elite_tui.py) ---
    "tui.market.col_basis": "Base",
    "tui.trend.below": "▼ por debajo de la base",
    "tui.trend.above": "▲ por encima de la base",
    "tui.trend.base": "≈ en la base",
    "tui.buy.info": "{name}: precio {price:.1f} Cr {trend}, máx. {mx} (límite: {limit}; créditos {credits:.1f})",
    "tui.buy.preview": "{name}: {qty} × {price:.1f} = {cost:.2f} Cr, quedan {rest:.2f} Cr",
    "tui.sell.info": "{name}: precio {price:.1f} Cr, en bodega {hold}, ingreso {income:.1f} Cr",
    "tui.sell.info_avg": "{name}: precio {price:.1f} Cr, en bodega {hold}, ingreso {income:.1f} Cr, comprado a {avg:.2f} Cr/ud, beneficio {profit:+.2f} Cr",
    "tui.sell.preview": "{name}: {qty} × {price:.1f} = {income:.2f} Cr",
    "tui.sell.preview_profit": "{name}: {qty} × {price:.1f} = {income:.2f} Cr, beneficio {profit:+.2f} Cr",
    "tui.sell.done_profit": "Vendido {qty} {name} por {income:.2f} Cr (beneficio {profit:+.2f} Cr)",
    "tui.status.pirates": "PIRATAS",
    "tui.buy.limit_credits": "créditos",
    "tui.buy.limit_space": "bodega",
    "tui.buy.limit_stock": "existencias",
    "tui.buy.limit_none": "agotado",
    "tui.sell.all_confirm": "Se venderán {positions} tipos ({qty} ud.) por {total:.2f} Cr. Pulse «Vender todo» de nuevo para confirmar.",
    "tui.map.col_trend": "Tend.",
    "tui.undo.done": "Última operación cancelada",
    "tui.undo.none": "Nada que cancelar",
    "tui.tradelog.title": "OPERACIONES DE SESIÓN — F4",
    "tui.tradelog.empty": "Aún no hay operaciones.",
    "tui.trade.bought": "comprado {qty} {name} por {cost:.2f} Cr",
    "tui.trade.sold": "vendido {qty} {name} por {income:.2f} Cr",
    "tui.notify.pirates": "¡ATAQUE PIRATA!",
    "tui.notify.destroyed": "¡NAVE DESTRUIDA!",
    "tui.need_select": "¡Seleccione un producto primero!",
    "tui.qty.required": "¡Introduzca una cantidad!",
    "tui.qty.invalid": "¡Número no válido!",
    "tui.qty.positive": "¡La cantidad debe ser > 0!",
    "tui.trade.failed": "Operación fallida: {exc}",

    # --- TUI: botones y columnas comunes ---
    "tui.btn.close": "Cerrar [Esc]",
    "tui.btn.cancel": "Cancelar [Esc]",
    "tui.btn.done": "Listo [Esc]",
    "tui.btn.buy": "Comprar [Enter]",
    "tui.btn.buy_max": "Comprar al máximo",
    "tui.btn.sell": "Vender [Enter]",
    "tui.btn.sell_all": "Vender todo",
    "tui.btn.attack": "Atacar [a]",
    "tui.btn.flee": "Huir [f]",
    "tui.btn.surrender": "Rendirse [u]",
    "tui.btn.new_game": "Nueva partida [n]",
    "tui.btn.quit": "Salir [q]",
    "tui.btn.save": "Guardar [Enter]",
    "tui.btn.load": "Cargar [Enter]",
    "tui.col.commodity": "Producto",
    "tui.col.price": "Precio Cr",
    "tui.col.avail": "Disp.",
    "tui.col.in_hold": "En bodega",
    "tui.col.hold": "Bodega",
    "tui.col.system": "Sistema",
    "tui.col.ly": "a.l.",
    "tui.col.fuel": "Comb.",
    "tui.col.economy": "Economía",
    "tui.col.gov": "Gob.",
    "tui.col.risk": "Riesgo",
    "tui.col.file": "Archivo",
    "tui.col.size": "Tamaño",
    "tui.col.modified": "Modificado",

    # --- TUI: compra ---
    "tui.buy.title": "MERCADO — seleccione una fila, introduzca la cantidad, Enter (el diálogo no se cierra tras la compra)",
    "tui.buy.qty_placeholder": "Cantidad (p. ej. 5)",
    "tui.buy.max_entered": "Máx. disponible: {mx} (ha introducido {qty})",
    "tui.buy.done": "Comprado {qty} {name} por {cost:.2f} Cr",
    "tui.buy.unavailable": "{name}: no disponible para compra (créditos {credits:.1f})",

    # --- TUI: venta ---
    "tui.sell.title": "BODEGA — seleccione la carga, introduzca la cantidad, Enter (el diálogo no se cierra tras la venta)",
    "tui.sell.qty_placeholder": "Cantidad",
    "tui.sell.empty": "¡La bodega está vacía — no hay nada que vender!",
    "tui.sell.only_hold": "Solo {hold} en bodega (ha introducido {qty})",
    "tui.sell.done": "Vendido {qty} {name} por {income:.2f} Cr",
    "tui.sell.failed": "Venta de {name} fallida: {exc}",
    "tui.sell.all_done": "Vendido todo: +{total:.2f} Cr",
    "tui.sell.all_done_profit": "Vendido todo: +{total:.2f} Cr (beneficio {profit:+.2f} Cr)",
    "tui.sell.all_done_info": "Toda la carga vendida: +{total:.2f} Cr",
    "tui.sell.all_done_info_profit": "Toda la carga vendida: +{total:.2f} Cr, beneficio {profit:+.2f} Cr",

    # --- TUI: salto ---
    "tui.jump.title": "MAPA GALÁCTICO — seleccione un sistema (clic o Enter)",
    "tui.jump.empty": "No hay sistemas alcanzables",

    # --- TUI: combate ---
    "tui.combat.title": "⚠ ¡ATAQUE PIRATA!",
    "tui.combat.info": "Sistema: {name} ({gov})\nEscudos F:{fsh}/255 A:{ash}/255  Energía: {eng}\nCréditos: {credits:.1f} Cr\nCarga: {cargo}/{hold}t",
    "tui.combat.log": "Combate ({action}): {message}",

    # --- TUI: fin del juego ---
    "tui.gameover.title": "💀 NAVE DESTRUIDA 💀",
    "tui.gameover.text": "Fin del juego.",
    "tui.gameover.log": "¡NAVE DESTRUIDA!",

    # --- TUI: info del sistema ---
    "tui.info.title": "{name} (Galaxia {galaxy})",
    "tui.info.body": "Economía: {economy}\nGobierno: {gov}\nNivel tecnológico: {tech}\nPoblación: {pop:.1f} mil millones\nEscudos F:{fsh}/255 A:{ash}/255  Energía: {eng}\n\n{description}",

    # --- TUI: archivos ---
    "tui.file.save_title": "GUARDAR PARTIDA (.elite)",
    "tui.file.load_title": "CARGAR PARTIDA (.elite)",
    "tui.file.name_placeholder": "Nombre de archivo (p. ej. mysave.elite)",
    "tui.file.name_required": "¡Introduzca un nombre de archivo!",
    "tui.file.name_invalid": "¡Nombre no válido: use un nombre sin rutas ni barras!",

    # --- TUI: ayuda ---
    "tui.help.title": "AYUDA — ELITE: HARMLESS",
    "tui.help.text": "CONTROLES\n  b — comprar producto        s — vender producto\n  «Vender todo» en el diálogo de venta — vender toda la bodega\n  incondicionalmente a los precios del sistema actual\n  Doble clic en un producto de la lista MERCADO — diálogo de compra\n  de ese producto (el diálogo tiene el botón «Comprar al máximo»)\n  j — saltar a un sistema     i — descripción del sistema\n  h — esta ayuda              r — repostar al máximo\n  w — esperar turno (escudos +1)  q — salir\n  F5 — guardado rápido        F9 — carga rápida (quicksave.elite)\n  F2 — guardar en archivo     F3 — cargar (*.elite)\n  F4 — registro de operaciones de la sesión\n  En diálogos: Esc — cancelar, Ctrl+Z — deshacer la última operación\n  En combate: a — atacar, f — huir, u — rendirse\n\nCÓMO JUGAR\n  El objetivo es ganar créditos: compre productos baratos y véndalos\n  más caros en otro sistema. El salto consume combustible (0.2 Cr por\n  unidad); el repostaje siempre llena el depósito.\n  El mercado y el peligro dependen del gobierno del sistema: en las\n  anarquías atacan a menudo los piratas. Atacar es arriesgado con\n  escudos débiles, huir es más fácil con el depósito lleno, rendirse\n  significa perder la carga y parte de los créditos.\n  Los «productos alienígenas» no están disponibles en el mercado.\n\nGUARDADOS Y REGISTRO\n  quicksave.elite — teclas F5/F9; guardados con nombre — *.elite\n  (F2/F3). Todos los eventos del juego se escriben en la base\n  elite_events.db.",

    # --- TUI: ventana principal ---
    "tui.panel.market": "MERCADO",
    "tui.panel.galaxy": "MAPA GALÁCTICO",
    "tui.btn.buy_key": "Comprar [b]",
    "tui.btn.sell_key": "Vender [s]",
    "tui.btn.jump_key": "Saltar [j]",
    "tui.btn.refuel_key": "Repostar [r]",
    "tui.btn.wait_key": "Esperar [w]",
    "tui.btn.help_key": "Ayuda [h]",
    "tui.btn.trades_key": "Operaciones [F4]",
    "tui.btn.quit_key": "Salir [q]",
    "tui.welcome": "¡Bienvenido a pyElite!",
    "tui.start": "Inicio: {name} (Galaxia {galaxy})",
    "tui.keys_hint": "Teclas: b=comprar s=vender j=saltar i=info h=ayuda r=repostar w=esperar q=salir | F5/F9 guardado/carga rápida, F2/F3 archivos (.elite)",

    # --- TUI: barra de estado ---
    "tui.status.bar": "Cr: {credits:.1f}  |  Comb.: {fuel}/{max}  |  Carga: {cargo}/{hold}t  |  Escudos F:{fsh} A:{ash}  Energía: {eng}",

    # --- TUI: acciones ---
    "tui.refuel.full": "El depósito ya está lleno.",
    "tui.refuel.failed": "Repostaje fallido: {reason}",
    "tui.refuel.done": "Repostado al máximo (-{cost:.2f} Cr)",
    "tui.wait.done": "Turno pasado. Escudos +1.",
    "tui.save.done": "Guardado: {path}",
    "tui.save.failed": "Guardado fallido: {exc}",
    "tui.quicksave.failed": "Guardado rápido fallido: {exc}",
    "tui.quicksave.done": "Guardado rápido -> {path}",
    "tui.load.not_found": "Archivo no encontrado: {path}",
    "tui.load.failed": "Carga fallida: {exc}",
    "tui.load.done": "Cargado: {path} -> {name} ({credits:.1f} Cr)",
    "tui.jump.failed": "Salto fallido: {reason}",
    "tui.jump.done": "Salto {old} -> {new} ({dist:.1f} a.l., combustible -{cost})",
    "tui.new_game": "¡Nueva partida iniciada!",
}

# ---------------------------------------------------------------------------
# Метаданные локалей
# ---------------------------------------------------------------------------

AVAILABLE_LOCALES: List[str] = ["en", "ru", "es"]

LOCALE_DISPLAY_NAMES: Dict[str, str] = {
    "en": "English",
    "ru": "Русский",
    "es": "Español",
}


# ---------------------------------------------------------------------------
# Таблицы описания планеты («goat soup») — RU и ES
# ---------------------------------------------------------------------------
# Английские таблицы каноничны и живут в elite_core
# (SystemDescriptionEngine.TEMPLATES / SLOT_GROUPS). Переводы 1:1 по размеру
# и порядку групп: один и тот же seed даёт дословно соответствующее описание.
# В каждой фразе набор плейсхолдеров (<NAME>, <ECONOMY>, <ADJ1>, <ADJ2>,
# <ADJ3>, <GEO>, <ANIMAL>, <KILLER>, <DRINK>, <NOUN>) совпадает с
# английским шаблоном той же позиции — от этого набора зависит число
# потребляемых случайных байтов (детерминизм).

class DescriptionTables(NamedTuple):
    """Локализованные таблицы «goat soup» (шаблоны, группы слов, экономики)."""

    templates: Tuple[Tuple[Tuple[str, ...], ...], ...]
    groups: Dict[str, Tuple[str, ...]]
    economies: Tuple[str, ...]   # 8 согласованых с шаблоном вставок <ECONOMY>


_RU_TEMPLATES: Tuple[Tuple[Tuple[str, ...], ...], ...] = (
    (("<NAME> — мир с <ECONOMY> экономикой.",),
     ("Его <GEO> <ADJ2> знамениты.",),
     ("<ADJ1> аборигены <NAME> напоминают <ANIMAL>.",)),
    (("Гордость <NAME> — <ADJ1> <NOUN>.",),
     ("Жители — <KILLER> охотники на <ANIMAL>.",),
     ("Туристам по вкусу местный <DRINK>.",)),
    (("На <NAME> сохранились <ADJ3> следы древней цивилизации.",),
     ("Его <GEO> <ADJ2> популярны у туристов.",),
     ("Здесь живут <ADJ1> пастухи, разводящие <ANIMAL>.",)),
    (("На <NAME> орудуют <KILLER> браконьеры, охотящиеся на <ANIMAL>.",),
     ("Местные <NOUN> <ADJ2> популярны.",),
     ("Местные <GEO> — <ADJ3>.",)),
    (("Достопримечательности этой системы — <ADJ3>.",),
     ("Слава о здешних <GEO> и охоте на <ANIMAL> уникальна.",),
     ("Местный <DRINK> <ADJ2> хорош.",)),
)

_RU_GROUPS: Dict[str, Tuple[str, ...]] = {
    "<ADJ1>": ("знаменитые", "прославленные", "известные",
               "примечательные", "легендарные"),
    "<ADJ2>": ("чрезвычайно", "отчасти", "по-настоящему", "вполне"),
    "<ADJ3>": ("удивительные", "забавные", "странные", "необычные",
               "причудливые", "грандиозные", "необъятные", "розовые",
               "древние"),
    "<GEO>": ("плантации", "горы", "паркоматы", "пылевые облака",
              "айсберги", "скальные образования", "вулканы", "леса",
              "океаны"),
    "<ANIMAL>": ("землероек", "зверей", "бизонов", "змей", "волков",
                 "леопардов", "котов", "обезьян", "козлов", "рыб",
                 "древовидов", "крабов", "омаров", "поэтов",
                 "выпускников искусств", "яков", "улиток", "слизней",
                 "ос", "молей", "гусениц", "муравьёв"),
    "<KILLER>": ("свирепые", "беспощадные", "злобные", "смертоносные",
                 "жестокие"),
    "<DRINK>": ("сок", "бренди", "вода", "брага", "горглбластер"),
    "<NOUN>": ("блендеры для еды", "туристы", "поэмы", "дискотеки",
               "кухни", "ночные тусовки", "казино", "ситкомы"),
}

_RU_ECONOMIES: Tuple[str, ...] = (
    "Богатой промышленной", "Развитой промышленной", "Бедной промышленной",
    "Преимущественно промышленной", "Преимущественно аграрной",
    "Богатой аграрной", "Развитой аграрной", "Бедной аграрной",
)

_ES_TEMPLATES: Tuple[Tuple[Tuple[str, ...], ...], ...] = (
    (("<NAME> es un mundo <ECONOMY>.",),
     ("Es <ADJ2> famoso por su <GEO>.",),
     ("Los nativos son <ADJ1>; se parecen a <ANIMAL>.",)),
    (("La fama de <NAME> se debe a sus <ADJ1> <NOUN>.",),
     ("La gente son cazadores <KILLER> de <ANIMAL>.",),
     ("A los turistas les encanta el <DRINK> local.",)),
    (("En <NAME> se conserva un <ADJ3> vestigio de civilización.",),
     ("Su <GEO> es <ADJ2> popular.",),
     ("Aquí viven pastores <ADJ1> que crían <ANIMAL>.",)),
    (("En <NAME> actúan cazadores furtivos <KILLER> que persiguen "
      "<ANIMAL>.",),
     ("Los <NOUN> locales son <ADJ2> populares.",),
     ("Su <GEO> es <ADJ3>.",)),
    (("Este sistema es <ADJ3>.",),
     ("La fama de su <GEO> y de la caza de <ANIMAL> es única.",),
     ("El <DRINK> local es <ADJ2> bueno.",)),
)

_ES_GROUPS: Dict[str, Tuple[str, ...]] = {
    "<ADJ1>": ("legendarios", "célebres", "conocidos", "ilustres",
               "afamados"),
    "<ADJ2>": ("sumamente", "ligeramente", "verdaderamente", "bastante"),
    "<ADJ3>": ("antiguo", "divertido", "extraño", "inusual", "peculiar",
               "grandioso", "inmenso", "rosa", "insólito"),
    "<GEO>": ("volcán", "bosque", "océano", "iceberg", "parquímetro",
              "monolito", "cráter", "cañón", "desierto"),
    "<ANIMAL>": ("musarañas", "bestias", "bisontes", "serpientes", "lobos",
                 "leopardos", "gatos", "monos", "cabras", "peces",
                 "arborícolas", "cangrejoides", "langostoides", "poetas",
                 "artistas", "yaks", "caracoles", "babosas", "avispas",
                 "polillas", "larvas", "hormigas"),
    "<KILLER>": ("feroces", "despiadados", "malvados", "letales",
                 "crueles"),
    "<DRINK>": ("zumo", "brandy", "agua", "brebaje", "gargle blaster"),
    "<NOUN>": ("robots de cocina", "turistas", "poemas",
               "salones de baile", "sabores", "antros nocturnos",
               "casinos", "culebrones"),
}

_ES_ECONOMIES: Tuple[str, ...] = (
    "industrial rico", "industrial normal", "industrial pobre",
    "principalmente industrial", "principalmente agrícola",
    "agrícola rico", "agrícola normal", "agrícola pobre",
)

DESCRIPTION_TABLES: Dict[str, DescriptionTables] = {
    "ru": DescriptionTables(_RU_TEMPLATES, _RU_GROUPS, _RU_ECONOMIES),
    "es": DescriptionTables(_ES_TEMPLATES, _ES_GROUPS, _ES_ECONOMIES),
}


def desc_tables(lang: str) -> DescriptionTables:
    """Таблицы описания планеты для локали; ValueError для неизвестной.

    "en" не входит: английские таблицы каноничны и берутся из ядра."""
    try:
        return DESCRIPTION_TABLES[lang]
    except KeyError:
        raise ValueError(
            f"no description tables for locale {lang!r}") from None


# ---------------------------------------------------------------------------
# Названия товаров (только отображение и разбор ввода игрока)
# ---------------------------------------------------------------------------
# Канонические имена (COMMODITIES в elite_core) — единственный язык API,
# БД событий и сейвов. Локализованные имена используются ТОЛЬКО при показе
# интерфейса и при разборе ввода игрока. Порядок и число (17) строк
# совпадают с COMMODITIES.

COMMODITY_NAMES: Dict[str, Tuple[str, ...]] = {
    "ru": (
        "Еда", "Ткани", "Радиоактивы", "Рабы", "Спиртное",
        "Роскошь", "Наркотики", "Компьютеры", "Машины", "Сплавы",
        "Оружие", "Меха", "Минералы", "Золото", "Платина",
        "Драгоценные камни", "Товары Чужих",
    ),
    "es": (
        "Comida", "Textiles", "Radiactivos", "Esclavos", "Licores",
        "Lujo", "Narcóticos", "Ordenadores", "Maquinaria", "Aleaciones",
        "Armas", "Pieles", "Minerales", "Oro", "Platino", "Gemas",
        "Artículos alienígenas",
    ),
}


def commodity_display(index: int, lang: str = "en") -> Optional[str]:
    """Локализованное название товара по индексу (только для показа).

    None — перевода нет ("en", неизвестная локаль или индекс): вызывающий
    код показывает каноническое имя."""
    names = COMMODITY_NAMES.get(lang)
    if names is not None and 0 <= index < len(names):
        return names[index]
    return None


def resolve_commodity(name: str, lang: str) -> int:
    """Индекс товара по локализованному имени (без учёта регистра,
    prefix-матчинг); -1 если у локали нет каталога или имя не найдено."""
    names = COMMODITY_NAMES.get(lang)
    if not names:
        return -1
    key = str(name).strip().lower()
    for i, loc in enumerate(names):
        low = loc.lower()
        if low == key or low.startswith(key):
            return i
    return -1


# ---------------------------------------------------------------------------
# Класс I18n
# ---------------------------------------------------------------------------

class I18n:
    """
    Локализатор CLI-игры «pyElite».

    Поддерживает три языка: "en" (базовый), "ru" и "es". Каталог текущей
    локали выбирается автоматически; при отсутствии ключа используется EN,
    затем — сам ключ (fallback).
    """

    #: Карта код локали -> каталог строк.
    _CATALOGS: Dict[str, Dict[str, str]] = {"en": EN, "ru": RU, "es": ES}

    def __init__(self, locale: str = "en") -> None:
        """Создаёт I18n с указанной локалью (по умолчанию "en")."""
        self._locale: str = "en"
        self.set_locale(locale)

    @property
    def locale(self) -> str:
        """Текущий код локали ("en", "ru" или "es")."""
        return self._locale

    def tr(self, key: str, **kwargs) -> str:
        """
        Возвращает строку по ключу с подстановкой {kwargs} через str.format().

        Порядок поиска (fallback): текущая локаль -> EN -> сам ключ.
        Если для подстановки не хватает параметров, возвращается шаблон
        без изменений (игра не падает из-за отсутствующего параметра).
        """
        text: str = self._CATALOGS[self._locale].get(key) or EN.get(key) or key
        if not kwargs:
            return text
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError, AttributeError):
            return text

    def set_locale(self, lang: str) -> None:
        """
        Переключает язык интерфейса.

        Допустимые значения: "en", "ru", "es". При любом другом — ValueError.
        """
        if lang not in self._CATALOGS:
            raise ValueError(
                f"unknown locale: {lang!r} (available: {', '.join(AVAILABLE_LOCALES)})"
            )
        self._locale = lang

    def available_locales(self) -> list[str]:
        """Список доступных кодов локалей: ["en", "ru", "es"]."""
        return list(AVAILABLE_LOCALES)

    def locale_display_name(self, lang: str) -> str:
        """
        Отображаемое имя локали: "en" -> "English", "ru" -> "Русский",
        "es" -> "Español". Для неизвестного кода возвращается сам код.
        """
        return LOCALE_DISPLAY_NAMES.get(lang, lang)


# ---------------------------------------------------------------------------
# Демо: переключение EN <-> RU <-> ES
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    i18n = I18n("en")
    print("available_locales:", i18n.available_locales())
    print()

    for code in ("en", "ru", "es"):
        i18n.set_locale(code)
        print(f"=== {i18n.locale_display_name(code)} ({code}) ===")
        print(i18n.tr("app.welcome"))
        print(i18n.tr("cmd.status.system", index=7, name="TIBEDI"))
        print(i18n.tr("cmd.combat.no_attack"))
        print()
