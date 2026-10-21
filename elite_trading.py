"""
pyElite — торговая система (логика рынка, портированная на Python 3.10+).

Модуль воспроизводит формирование цен и наличия товаров на рынке в точности
как в ассемблерном коде проекта (6502, C64-версия Elite). Все значения
детерминированы: одна и та же система в одной и той же галактике всегда
даёт один и тот же рынок. Модуль `random` не используется — шум цен
поступает из того же регистра «Twins», что и в генераторе галактик.

Используемые строки/логика из `src`:

1. Таблица товаров (16 записей по 4 byte: базовая цена, flags+gradient,
   базовое количество, маска шума):
   - `src/code_6a00.asm:6405`-`6420` (метки `_90a5`..`_90a8`).
     Флаги: bit 7 = знак gradient (установлен -> цена/количество растут
     с индексом экономики), bits 5-6 = единицы измерения (00 = тонны,
     01 = KG, 10 = г), bits 0-4 = величина gradient.

2. Названия 17 категорий товаров ("FOOD".."ALIEN ITEMS"):
   - `src/text/text_flight.asm:427`-`493` (токены $F3..$C3,
     TKN_FLIGHT_CARGO_TYPES).
   Порядок категорий совпадает с `PLAYER_CARGO`
   (`src/vars_main.asm:210`-`227`).

3. Шум цен — `MARKET_RANDOM`:
   - `src/code_6a00.asm:2128`-`2129` — один шаг `get_random_number`
     (DORND) при прибытии в систему;
   - seed «goat soup» (4 byte регистра DORND) = последние 4 byte seed
     системы (W1_LO..W2_HI): `src/code_28ba.asm:3944`-`3949`;
   - сам DORND: `src/code_6a00.asm:4431`-`4450`. Перенос carry в ROL
     считается равным 0, как в `get_random_number_clc`
     (`src/code_6a00.asm:4424`): цепочка переносов перед вызовом не
     воспроизводима без полной эмуляции, а вариант clc эквивалентен
     по назначению.

4. Наличие товара на рынке:
   - `src/code_6a00.asm:2131`-`2165` (`_7365`): для каждого товара
     quantity = (base_qty + noise (+/-) gradient*economy), при
     отрицательном результате обрезается до 0, затем маска & %00111111;
   - градиентная составляющая = (flags & $1F) * PSYSTEM_ECONOMY
     (`src/code_6a00.asm:2086`-`2102`, `_731a`);
   - экономика берётся «патченная» (анархия/феодализм не могут быть
     «богатыми», `src/code_6a00.asm:588`-`593`);
   - «Alien Items» (17-я категория) в этом порте всегда недоступна:
     MARKET_ALIENS обнуляется в `_731a` (`src/code_6a00.asm:2094`);
     в таблице `_90a6` нет данных для 17-го товара.

5. Цена товара:
   - `src/code_6a00.asm:1951`-`1977` (TT151): цена = base_price + noise
     (+/-) gradient*economy (без обрезания, 8 бит);
   - отображаемая цена = цена * 4 (тысячные/десятые Cr):
     `src/code_6a00.asm:2355`-`2364` (`_74a5`: два asl+rol);
   - денежная единица: 1 единица = 0.1 Cr (стартовые 1000 единиц =
     "100.00 cr", `src/save_data.asm:159`), т.е. цена в Cr = цена*0.4.
   - цена покупки == цена продажи (в Elite рынок односторонний; прибыль —
     это разница между системами).

6. Покупка / продажа:
   - покупка: `src/code_6a00.asm:990`-`1005` — стоимость = qty * price * 4
     единиц, деньги списываются, наличие на рынке уменьшается, груз
     увеличивается;
   - продажа: `src/code_6a00.asm:1174`-`1185` — доход = qty * price * 4,
     деньги зачисляются, груз уменьшается (наличие на рынке НЕ
     увеличивается);
   - деньги: 4-байтовое значение big-endian, `src/code_6a00.asm:2298`-`2345`.

7. Вместимость трюма (`check_cargo_capacity`):
   - `src/code_6a00.asm:24`-`88` — для товаров 0-12 (Food..Minerals)
     суммарные тонны (сумма всего такого груза + покупка) <= SHIP_HOLD (22,
     `src/save_data.asm:169`); для драгоценных предметов
     (Gold/Platinum/Gem-stones/Alien items, индексы 13-16) — не более
     200 единиц каждого вида (`cmp # 200`, `src/code_6a00.asm:85`).

ПРИМЕЧАНИЕ ОБ АРХИТЕКТУРЕ (рефакторинг объединения рынков):

Прежний класс `EliteMarket` (stateful: собственные `_cash_units`/`_cargo`,
методы `buy()`/`sell()`/`sync_state()`) удалён. Его место занял
`elite_core.MarketEngine` — stateless движок цен/наличия с единственной
мутацией `commit_buy()` (уменьшение `_available`, привязано к инстансу:
место + сессия стыковки). Деньги и груз игрока живут в `GameState`
(как core `elite_core.GameState`, так и CLI `game_loop.GameState`),
который владеет инстансом `MarketEngine` и вызывает `commit_buy` после
успешной покупки. Продажа доступность рынка НЕ увеличивает (как в
оригинале). При `load_system()`/прыжке создаётся свежий `MarketEngine` —
мутации `_available` сбрасываются.
"""

from __future__ import annotations

from elite_core import (
    COMMODITIES,
    GalaxyGenerator,
    GameState,
    MarketEngine,
    SHIP_HOLD,
)


if __name__ == "__main__":
    gen = GalaxyGenerator()
    market = MarketEngine(gen, system_number=0, galaxy_number=0)

    print("Market of system #0, galaxy 0 "
          f"(economy: {market.system['economy_name']}, "
          f"government: {market.system['government_name']})\n")

    print(f"{'Item':<15} {'Unit':<4} {'Available':>8} "
          f"{'Buy, Cr':>11} {'Sell, Cr':>11}")
    print("-" * 54)
    for row in market:
        print(
            f"{row['name']:<15} {row['unit']:<4} {row['available']:>8} "
            f"{row['price_buy_cr']:>11.2f} {row['price_sell_cr']:>11.2f}"
        )

    # example transaction: state lives in GameState, the market only
    # commits availability via commit_buy()
    gs = GameState(galaxy=0, system_index=0)
    print("\nExample transaction:")
    print(f"  cash before: {gs.credits:.2f} Cr")
    cost = gs.buy("food", 5)
    print(f"  bought 5 Food for {cost:.2f} Cr "
          f"(remaining on market: {gs.market.available(0)})")
    income = gs.sell("food", 3)
    print(f"  sold 3 Food for {income:.2f} Cr")
    print(f"  cash after: {gs.credits:.2f} Cr, "
          f"cargo: {gs.cargo[0]} Food, total tonnes: "
          f"{gs.cargo_weight}/{SHIP_HOLD}")

    # determinism: recreating the market gives the same prices
    market2 = MarketEngine(gen, system_number=0, galaxy_number=0)
    assert [r["price_buy_cr"] for r in market.get_market()] == \
           [r["price_buy_cr"] for r in market2.get_market()]
    print("\n(determinism confirmed: prices are identical on market rebuild)")