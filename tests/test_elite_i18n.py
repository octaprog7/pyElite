"""
test_elite_i18n.py — тесты для модуля локализации elite_i18n.py.

Покрывает: синхронность ключей, placeholder-ы, fallback, форматирование,
переключение языков, обработку ошибок, Unicode, детерминированность,
smoke-тест всех ключей.

Запуск: python test_elite_i18n.py
Зависимости: только стандартная библиотека (re, sys) + elite_i18n.
"""

import os
import re
import sys

# Добавить корень проекта (rework/) в sys.path для standalone-запуска:
# python tests/test_elite_i18n.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elite_i18n import (
    I18n, EN, RU, ES,
    AVAILABLE_LOCALES, LOCALE_DISPLAY_NAMES,
)

passed = 0
failed = 0
errors: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  \u2705 {name}")
    else:
        failed += 1
        msg = f"  \u274c {name}" + (f" — {detail}" if detail else "")
        print(msg)
        errors.append(msg)


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def extract_placeholders(text: str) -> set[str]:
    return set(re.findall(r'\{([^}]+)\}', text))


def main() -> None:
    # ============================================================
    # 1. Синхронность ключей
    # ============================================================
    section("1. Синхронность ключей (EN / RU / ES)")

    en_keys = set(EN.keys())
    ru_keys = set(RU.keys())
    es_keys = set(ES.keys())

    check("EN и RU: одинаковый набор ключей", en_keys == ru_keys,
          f"Только в EN: {en_keys - ru_keys}; только в RU: {ru_keys - en_keys}")
    check("EN и ES: одинаковый набор ключей", en_keys == es_keys,
          f"Только в EN: {en_keys - es_keys}; только в ES: {es_keys - en_keys}")
    check("RU и ES: одинаковый набор ключей", ru_keys == es_keys,
          f"Только в RU: {ru_keys - es_keys}; только в ES: {es_keys - ru_keys}")
    check("Количество ключей = 100", len(en_keys) == 100, f"Фактически: {len(en_keys)}")
    check("Все значения EN — строки", all(isinstance(v, str) for v in EN.values()))
    check("Все значения RU — строки", all(isinstance(v, str) for v in RU.values()))
    check("Все значения ES — строки", all(isinstance(v, str) for v in ES.values()))
    check("Нет пустых значений в EN", all(v.strip() for v in EN.values()))
    check("Нет пустых значений в RU", all(v.strip() for v in RU.values()))
    check("Нет пустых значений в ES", all(v.strip() for v in ES.values()))

    # ============================================================
    # 2. Placeholder-ы
    # ============================================================
    section("2. Placeholder-ы ({...} в значениях)")

    mismatches = []
    for key in en_keys:
        en_ph = extract_placeholders(EN[key])
        ru_ph = extract_placeholders(RU[key])
        es_ph = extract_placeholders(ES[key])
        if not (en_ph == ru_ph == es_ph):
            mismatches.append(f"  {key}: EN={en_ph}, RU={ru_ph}, ES={es_ph}")

    check("Placeholder-ы совпадают во всех языках", len(mismatches) == 0,
          "\n".join(mismatches) if mismatches else "")

    keys_with_ph = sum(1 for k in en_keys if extract_placeholders(EN[k]))
    print(f"  \u2139\ufe0f  Ключей с placeholder-ами: {keys_with_ph} из {len(en_keys)}")

    # ============================================================
    # 3. Fallback
    # ============================================================
    section("3. Fallback (локаль -> EN -> ключ)")

    i18n = I18n("en")
    check("Несуществующий ключ возвращает сам ключ",
          i18n.tr("nonexistent.key") == "nonexistent.key")

    i18n.set_locale("ru")
    check("Несуществующий ключ в RU -> fallback на сам ключ",
          i18n.tr("nonexistent.key") == "nonexistent.key")
    check("RU ключ возвращает русское значение",
          "торговля" in i18n.tr("app.welcome").lower())

    i18n.set_locale("es")
    check("ES ключ возвращает испанское значение",
          "comercio" in i18n.tr("app.welcome").lower())

    # ============================================================
    # 4. Форматирование
    # ============================================================
    section("4. Форматирование str.format()")

    i18n.set_locale("en")

    result = i18n.tr("cmd.status.fuel", fuel=50, max_fuel=70, fuel_ly=5.0)
    check("Формат :.1f в cmd.status.fuel", "5.0" in result, f"Получено: {result}")

    result = i18n.tr("cmd.status.credits", credits=100.5)
    check("Формат :.2f в cmd.status.credits", "100.50" in result, f"Получено: {result}")

    result = i18n.tr("cmd.near.row", index=5, name="TIBEDI", dist_ly=3.5, cost=10, cost_ly=1.0)
    check("Формат :>3 в cmd.near.row", "  5" in result, f"Получено: {result}")

    check("Ключ без placeholder-ов", i18n.tr("app.farewell") == "Farewell, Commander.")

    try:
        i18n.tr("cmd.status.fuel")
        check("tr() без kwargs не падает", True)
    except Exception as e:
        check("tr() без kwargs не падает", False, str(e))

    try:
        i18n.tr("app.farewell", extra="unused")
        check("tr() с лишними kwargs не падает", True)
    except Exception as e:
        check("tr() с лишними kwargs не падает", False, str(e))

    try:
        i18n.tr("cmd.jump.no_fuel", cost=10)
        check("tr() с недостающими kwargs не падает", True)
    except Exception as e:
        check("tr() с недостающими kwargs не падает", False, str(e))

    # ============================================================
    # 5. Переключение языков
    # ============================================================
    section("5. set_locale() и available_locales()")

    i18n = I18n("en")
    check("Начальная локаль — en", i18n.locale == "en")

    i18n.set_locale("ru")
    check("set_locale('ru')", i18n.locale == "ru")

    i18n.set_locale("es")
    check("set_locale('es')", i18n.locale == "es")

    i18n.set_locale("en")
    check("set_locale('en')", i18n.locale == "en")

    locales = i18n.available_locales()
    check("available_locales() возвращает 3 языка", len(locales) == 3, f"Получено: {locales}")
    check("available_locales() содержит 'en'", "en" in locales)
    check("available_locales() содержит 'ru'", "ru" in locales)
    check("available_locales() содержит 'es'", "es" in locales)

    check("locale_display_name('en') == 'English'", i18n.locale_display_name("en") == "English")
    check("locale_display_name('ru') == 'Русский'", i18n.locale_display_name("ru") == "Русский")
    check("locale_display_name('es') == 'Español'", i18n.locale_display_name("es") == "Español")
    check("locale_display_name('xx') возвращает 'xx'", i18n.locale_display_name("xx") == "xx")

    # ============================================================
    # 6. Обработка ошибок
    # ============================================================
    section("6. Обработка ошибок")

    for bad_locale in ("zh", "", "fr", "de", "jp"):
        try:
            I18n(bad_locale)
            check(f"I18n('{bad_locale}') -> ValueError", False, "Не было исключения")
        except ValueError:
            check(f"I18n('{bad_locale}') -> ValueError", True)

    try:
        i18n.set_locale("zh")
        check("set_locale('zh') -> ValueError", False, "Не было исключения")
    except ValueError as e:
        check("set_locale('zh') -> ValueError", True)
        check("ValueError содержит 'zh'", "zh" in str(e))

    # ============================================================
    # 7. Unicode — акценты в ES
    # ============================================================
    section("7. Unicode — акценты в ES")

    i18n.set_locale("es")

    check("ES welcome содержит 'comercio'", "comercio" in i18n.tr("app.welcome"))
    check("ES welcome содержит 'saltos'", "saltos" in i18n.tr("app.welcome"))

    fuel_str = i18n.tr("cmd.status.fuel", fuel=50, max_fuel=70, fuel_ly=5.0)
    check("ES cmd.status.fuel содержит 'Combustible'", "Combustible" in fuel_str)

    all_es_text = " ".join(ES.values())
    check("ES содержит á", "á" in all_es_text)
    check("ES содержит é", "é" in all_es_text)
    check("ES содержит í", "í" in all_es_text)
    check("ES contiene ó", "ó" in all_es_text)
    check("ES содержит ú", "ú" in all_es_text)
    check("ñ в LOCALE_DISPLAY_NAMES['es']", "ñ" in LOCALE_DISPLAY_NAMES["es"])

    try:
        for val in ES.values():
            val.encode("utf-8")
        check("Все ES-значения кодируются в UTF-8", True)
    except UnicodeEncodeError as e:
        check("Все ES-значения кодируются в UTF-8", False, str(e))

    # ============================================================
    # 8. Детерминированность
    # ============================================================
    section("8. Детерминированность")

    i18n.set_locale("en")
    r1 = i18n.tr("cmd.status.system", index=7, name="TIBEDI")
    r2 = i18n.tr("cmd.status.system", index=7, name="TIBEDI")
    check("Одинаковые вызовы — одинаковый результат", r1 == r2)

    before = i18n.tr("app.welcome")
    i18n.set_locale("ru")
    i18n.set_locale("es")
    i18n.set_locale("en")
    after = i18n.tr("app.welcome")
    check("Переключение EN->RU->ES->EN сохраняет значение", before == after)

    r1 = i18n.tr("cmd.status.system", index=1, name="TIBEDI")
    r2 = i18n.tr("cmd.status.system", index=2, name="EDINSOIN")
    check("Разные параметры — разные результаты", r1 != r2)

    # ============================================================
    # 9. Smoke-тест: все ключи с placeholder-ами
    # ============================================================
    section("9. Smoke-тест: все ключи с placeholder-ами во всех языках")

    test_kwargs = {
        "index": 7, "name": "TIBEDI", "economy": "Rich Agri", "government": "Democracy",
        "fuel": 50, "max_fuel": 70, "fuel_ly": 5.0, "cargo": 10, "hold": 22,
        "credits": 100.50, "qty": 5, "cost": 25.0, "income": 30.0,
        "dist_ly": 3.5, "cost_ly": 0.5, "value": "abc", "target": 3, "max": 255,
        "price": 0.2, "fuel_now": 50, "room": 20, "filled": 20,
        "path": "/tmp/save.json", "galaxy": 0, "exc": "test error",
        "command": "foobar", "verb": "buy", "list": "en, ru, es",
        "lang": "de", "code": "en", "display": "English",
        "hops": 3, "refuel": 3.20, "hop": 1, "from_name": "TIBEDI",
        "to_name": "EDINSOIN", "target_name": "EDINSOIN", "n": 10,
    }

    crash_count = 0
    crash_details = []

    for lang in ("en", "ru", "es"):
        i18n.set_locale(lang)
        for key in en_keys:
            phs = extract_placeholders(EN[key])
            if not phs:
                continue
            kwargs = {}
            for ph in phs:
                ph_name = ph.split(":")[0].split("!")[0]
                if ph_name in test_kwargs:
                    kwargs[ph_name] = test_kwargs[ph_name]
            try:
                i18n.tr(key, **kwargs)
            except Exception as e:
                crash_count += 1
                crash_details.append(f"  {lang}.{key}: {e}")

    check("Smoke-тест: 0 крашей во всех языках", crash_count == 0,
          "\n".join(crash_details[:10]) if crash_details else "")

    # ============================================================
    # 10. cmd.help.lang упоминает все 3 языка
    # ============================================================
    section("10. cmd.help.lang упоминает все 3 языка")

    for lang in ("en", "ru", "es"):
        i18n.set_locale(lang)
        val = i18n.tr("cmd.help.lang")
        check(f"{lang}: cmd.help.lang упоминает 'es'", "es" in val, f"Получено: {val}")

    # ============================================================
    # ИТОГ
    # ============================================================
    section("ИТОГ")
    print(f"\n  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Total:  {passed + failed}")
    if failed == 0:
        print("\n  \U0001f389 Все тесты прошли!")
    else:
        print(f"\n  \u26a0\ufe0f  {failed} тестов не прошли:")
        for e in errors:
            print(e)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
