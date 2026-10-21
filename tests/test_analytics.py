"""
test_analytics.py — тесты EventLogger (elite_analytics).

Проверяются: схема БД (колонка player_id), запись транзакций с
player_id, миграция старых БД (старые записи получают player_id=0),
а также фильтр по player_id в load_events (analyze_endings).

Лицензия: GPL v3.
"""

from __future__ import annotations

import sqlite3

import pytest

from elite_analytics import EventLogger


def test_event_logger_default_player_id(tmp_path):
    """player_id по умолчанию = 0; транзакции пишутся с ним."""
    logger = EventLogger(str(tmp_path / "events.db"))
    assert logger.player_id == 0
    logger.log_transaction(
        galaxy=0, system_index=1, system_name="A", action="buy",
        item="Food", quantity=1, unit_price=10.0, total_cost=10.0,
        fuel_before=70, fuel_after=70, credits_before=100.0,
        credits_after=90.0, cargo_weight_before=0, cargo_weight_after=1,
        details="test")
    rows = logger.all_rows()
    assert len(rows) == 1
    assert rows[0]["player_id"] == 0
    logger.close()


def test_event_logger_player_id_set(tmp_path):
    """Транзакции логгера помечаются заданным player_id."""
    logger = EventLogger(str(tmp_path / "events.db"), player_id=7)
    assert logger.player_id == 7
    logger.log_transaction(
        galaxy=0, system_index=1, system_name="A", action="sell",
        item="Food", quantity=1, unit_price=12.0, total_cost=12.0,
        fuel_before=70, fuel_after=70, credits_before=90.0,
        credits_after=102.0, cargo_weight_before=1, cargo_weight_after=0,
        details="test")
    rows = logger.all_rows()
    assert len(rows) == 1
    assert rows[0]["player_id"] == 7
    logger.close()


def test_event_logger_migrates_old_db(tmp_path):
    """Старая БД без player_id: колонка добавляется, старые строки = 0."""
    path = str(tmp_path / "old_events.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE transactions ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT NOT NULL, galaxy INTEGER NOT NULL,"
        "  system_index INTEGER NOT NULL, system_name TEXT NOT NULL,"
        "  action TEXT NOT NULL, item TEXT, quantity INTEGER,"
        "  unit_price REAL, total_cost REAL, fuel_before INTEGER,"
        "  fuel_after INTEGER, credits_before REAL, credits_after REAL,"
        "  cargo_weight_before INTEGER, cargo_weight_after INTEGER,"
        "  details TEXT)")
    conn.execute(
        "INSERT INTO transactions (timestamp, galaxy, system_index, "
        "system_name, action) VALUES ('2026-01-01T00:00:00+00:00', 0, 1, "
        "'OLD', 'jump')")
    conn.commit()
    conn.close()

    logger = EventLogger(path, player_id=3)   # миграция при открытии
    rows = logger.all_rows()
    assert len(rows) == 1
    assert rows[0]["player_id"] == 0          # старая запись -> игрок 0
    logger.log_transaction(
        galaxy=0, system_index=2, system_name="NEW", action="refuel",
        item=None, quantity=10, unit_price=0.2, total_cost=2.0,
        fuel_before=60, fuel_after=70, credits_before=5.0,
        credits_after=3.0, cargo_weight_before=0, cargo_weight_after=0,
        details="test")
    rows = logger.all_rows()
    assert rows[-1]["player_id"] == 3         # новая запись -> игрок 3
    cols = [d[1] for d in logger._conn.execute(
        "PRAGMA table_info(transactions)").fetchall()]
    assert "player_id" in cols
    logger.close()


def test_analyze_endings_load_events_filter(tmp_path):
    """load_events фильтрует по player_id (None — все записи)."""
    from analyze_endings import load_events

    path = str(tmp_path / "events.db")
    logger = EventLogger(path, player_id=0)
    for i in range(3):
        logger.log_transaction(
            galaxy=0, system_index=i, system_name=f"S{i}", action="jump",
            item=None, quantity=None, unit_price=None, total_cost=None,
            fuel_before=70, fuel_after=60, credits_before=100.0,
            credits_after=100.0, cargo_weight_before=0,
            cargo_weight_after=0, details=None)
    logger.close()

    logger2 = EventLogger(path, player_id=2)
    logger2.log_transaction(
        galaxy=0, system_index=9, system_name="S9", action="jump",
        item=None, quantity=None, unit_price=None, total_cost=None,
        fuel_before=70, fuel_after=60, credits_before=100.0,
        credits_after=100.0, cargo_weight_before=0, cargo_weight_after=0,
        details=None)
    logger2.close()

    all_rows = load_events(path, None)
    assert len(all_rows) == 4
    rows_p0 = load_events(path, 0)
    assert len(rows_p0) == 3
    assert all(r["player_id"] == 0 for r in rows_p0)
    rows_p2 = load_events(path, 2)
    assert len(rows_p2) == 1
    assert rows_p2[0]["system_index"] == 9


# --------------------------------------------------------------------------
# Аудит схемы: session_id, структурированные поля прыжка, индексы,
# валидация action, одноразовый снапшот capture()
# --------------------------------------------------------------------------


def _log_dummy(logger: EventLogger, action: str = "buy") -> None:
    """Одна тестовая транзакция с корректным action."""
    logger.log_transaction(
        galaxy=0, system_index=1, system_name="A", action=action,
        item=None, quantity=None, unit_price=None, total_cost=None,
        fuel_before=70, fuel_after=70, credits_before=100.0,
        credits_after=100.0, cargo_weight_before=0, cargo_weight_after=0,
        details=None)


def test_session_id_stamped(tmp_path):
    """Каждая запись помечается session_id партии; new_session() меняет его."""
    logger = EventLogger(str(tmp_path / "events.db"))
    first = logger.session_id
    _log_dummy(logger)
    second = logger.new_session()
    assert second != first
    assert logger.session_id == second
    _log_dummy(logger)
    logger.close()

    logger2 = EventLogger(str(tmp_path / "events.db"), player_id=0)
    rows = logger2.all_rows()
    assert rows[0]["session_id"] == first
    assert rows[1]["session_id"] == second
    logger2.close()


def test_session_id_explicit(tmp_path):
    """Явный session_id восстанавливает историю партии после перезапуска."""
    logger = EventLogger(str(tmp_path / "events.db"), session_id="run-42")
    assert logger.session_id == "run-42"
    _log_dummy(logger)
    assert logger.all_rows()[0]["session_id"] == "run-42"
    logger.close()


def test_migration_adds_session_and_jump_columns(tmp_path):
    """Старая БД: миграция добавляет session_id/target_system/distance_ly."""
    path = str(tmp_path / "old_events.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE transactions ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT NOT NULL, galaxy INTEGER NOT NULL,"
        "  system_index INTEGER NOT NULL, system_name TEXT NOT NULL,"
        "  action TEXT NOT NULL, details TEXT)")
    conn.commit()
    conn.close()

    logger = EventLogger(path)
    cols = [d[1] for d in logger._conn.execute(
        "PRAGMA table_info(transactions)").fetchall()]
    for col in ("player_id", "session_id", "target_system", "distance_ly"):
        assert col in cols
    logger.close()


def test_indexes_exist(tmp_path):
    """Схема создаёт индексы по action, player_id и session_id."""
    logger = EventLogger(str(tmp_path / "events.db"))
    names = {row[0] for row in logger._conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()}
    assert {"idx_transactions_action", "idx_transactions_player",
            "idx_transactions_session"} <= names
    logger.close()


def test_log_jump_structured_fields(tmp_path):
    """log_jump заполняет target_system и distance_ly (не только details)."""
    from elite_core import GameState

    st = GameState(galaxy=0, system_index=0)
    st.load_system()
    logger = EventLogger(str(tmp_path / "events.db"))
    result = st.jump(71)   # TIBEDI -> EDINSOIN
    assert result
    logger.log_jump(st, 71, str(st.system["name"]),
                    float(result.distance_ly), int(result.fuel_cost))
    row = logger.all_rows()[0]
    assert row["action"] == "jump"
    assert row["target_system"] == 71
    assert row["distance_ly"] == pytest.approx(result.distance_ly)
    logger.close()


def test_log_combat_snapshot_is_single_use(tmp_path):
    """capture(): before из снапшота; повторный log_combat без capture()
    получает fallback before=after с пометкой в details."""
    from elite_core import GameState

    st = GameState(galaxy=0, system_index=0)
    st.load_system()
    logger = EventLogger(str(tmp_path / "events.db"))

    st.credits = 77.0
    logger.capture(st)
    logger.log_combat(st, "surrender", "first battle")
    st.credits = 10.0
    logger.log_combat(st, "surrender", "second battle without capture")
    rows = logger.all_rows()
    logger.close()

    assert rows[0]["credits_before"] == pytest.approx(77.0)
    # Устаревший снапшот НЕ «протёк»: before = текущее состояние (10.0)
    assert rows[1]["credits_before"] == pytest.approx(10.0)
    assert "no capture() snapshot" in rows[1]["details"]


def test_unknown_action_skipped(tmp_path, capsys):
    """log_transaction с недопустимым action: запись пропускается, stderr."""
    logger = EventLogger(str(tmp_path / "events.db"))
    logger.log_transaction(
        galaxy=0, system_index=1, system_name="A", action="typo_action",
        details="oops")
    logger.log_transaction(
        galaxy=0, system_index=1, system_name="A", action="buy",
        details="fine")
    rows = logger.all_rows()
    logger.close()

    assert len(rows) == 1
    assert rows[0]["action"] == "buy"
    assert "unknown action" in capsys.readouterr().err