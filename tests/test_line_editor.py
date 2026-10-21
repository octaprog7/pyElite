"""
test_line_editor.py — тесты кроссплатформенного line editor (elite_line_editor).

Мок посимвольного ввода: модульная функция elite_line_editor._read_key()
заменяется на генератор заранее заготовленной последовательности клавиш,
а _make_raw/_restore_terminal — на no-op. Реальный терминал не требуется.

Также проверяется интеграция LineEditor в game_loop.GameLoop (run(),
cmd_refuel()) — ввод идёт через editor.readline(), а не input().

Лицензия: GPL v3.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

import elite_line_editor as ele
from elite_line_editor import LineEditor

# Клавиши-последовательности (как их отдаёт терминал/msvcrt)
UP = "\x1b[A"
DOWN = "\x1b[B"
LEFT = "\x1b[D"
RIGHT = "\x1b[C"
HOME = "\x1b[H"
END = "\x1b[F"
DELETE = "\x1b[3~"


def read_keys(editor: LineEditor, keys: list[str]) -> str:
    """Прочитать одну строку через mock посимвольного ввода (без терминала).

    `keys` — заранее заготовленная последовательность keypress-ов; каждый
    вызов _read_key() возвращает следующий элемент. Последовательность
    должна заканчиваться Enter, Ctrl-D или Ctrl-C.
    """
    it = iter(keys)

    def fake_read_key(fd: int | None = None) -> str:
        return next(it)

    with (
        patch.object(ele, "_read_key", fake_read_key),
        patch.object(ele, "_make_raw", lambda fd: None),
        patch.object(ele, "_restore_terminal", lambda fd, old: None),
        patch.object(LineEditor, "_is_tty", lambda self: True),
        patch.object(LineEditor, "_stdin_fileno", lambda self: 0),
    ):
        return editor.readline()


def enter(cmd: str) -> list[str]:
    """Последовательность клавиш: команда + Enter."""
    return list(cmd) + ["\r"]


# --------------------------------------------------------------------------
# 1. История в памяти
# --------------------------------------------------------------------------


def test_history_in_memory():
    ed = LineEditor()
    for cmd in ("status", "market", "jump 7"):
        assert read_keys(ed, enter(cmd)) == cmd
    assert ed._history == ["status", "market", "jump 7"]
    # Up x3: последняя, предыдущая, первая
    assert read_keys(ed, [UP, UP, UP, "\r"]) == "status"


def test_history_up_down_order():
    ed = LineEditor()
    for cmd in ("one", "two", "three"):
        read_keys(ed, enter(cmd))
    assert read_keys(ed, [UP, "\r"]) == "three"
    # Up, Up, Down → снова "three"
    assert read_keys(ed, [UP, UP, DOWN, "\r"]) == "three"


def test_history_navigation_with_pending_input():
    ed = LineEditor()
    for cmd in ("status", "market"):
        read_keys(ed, enter(cmd))
    # Начали печатать "junk", потом Up/Up/Down/Down — вернётся "junk".
    keys = list("junk") + [UP, UP, DOWN, DOWN, "\r"]
    assert read_keys(ed, keys) == "junk"


def test_history_up_with_empty_history():
    ed = LineEditor()
    assert read_keys(ed, [UP, "\r"]) == ""


def test_history_down_without_navigation():
    ed = LineEditor()
    read_keys(ed, enter("a"))
    assert read_keys(ed, [DOWN, "b", "\r"]) == "b"


# --------------------------------------------------------------------------
# 2. Дубликаты и ограничение размера
# --------------------------------------------------------------------------


def test_history_duplicates_skipped():
    ed = LineEditor()
    read_keys(ed, enter("status"))
    read_keys(ed, enter("status"))
    assert ed._history == ["status"]


def test_history_empty_lines_skipped():
    ed = LineEditor()
    read_keys(ed, ["\r"])
    read_keys(ed, enter("go"))
    read_keys(ed, ["\r"])
    assert ed._history == ["go"]


def test_max_history():
    ed = LineEditor(max_history=3)
    for i in range(5):
        read_keys(ed, enter(f"cmd{i}"))
    assert ed._history == ["cmd2", "cmd3", "cmd4"]


# --------------------------------------------------------------------------
# 3. Non-tty fallback
# --------------------------------------------------------------------------


def test_non_tty_fallback_uses_input(monkeypatch):
    calls: list[tuple] = []

    def fake_input(*args: object) -> str:
        calls.append(args)
        return "echoed"

    monkeypatch.setattr(LineEditor, "_is_tty", lambda self: False)
    monkeypatch.setattr("builtins.input", fake_input)
    ed = LineEditor()
    assert ed.readline("> ") == "echoed"
    assert calls == [("> ",)]


def test_non_tty_fallback_default_prompt(monkeypatch):
    calls: list[tuple] = []

    def fake_input(*args: object) -> str:
        calls.append(args)
        return "ok"

    monkeypatch.setattr(LineEditor, "_is_tty", lambda self: False)
    monkeypatch.setattr("builtins.input", fake_input)
    ed = LineEditor(prompt="=> ")
    assert ed.readline() == "ok"
    assert calls == [("=> ",)]


def test_non_tty_eof_returns_empty(monkeypatch):
    def fake_input(*args: object) -> str:
        raise EOFError

    monkeypatch.setattr(LineEditor, "_is_tty", lambda self: False)
    monkeypatch.setattr("builtins.input", fake_input)
    assert LineEditor().readline("> ") == ""


def test_non_tty_ctrl_c_returns_empty(monkeypatch):
    def fake_input(*args: object) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(LineEditor, "_is_tty", lambda self: False)
    monkeypatch.setattr("builtins.input", fake_input)
    assert LineEditor().readline("> ") == ""


# --------------------------------------------------------------------------
# 4. Персистентность истории
# --------------------------------------------------------------------------


def test_history_persistence(tmp_path):
    hist = tmp_path / ".elite_history"
    ed1 = LineEditor(history_file=str(hist))
    read_keys(ed1, enter("foo"))
    read_keys(ed1, enter("bar"))
    assert hist.read_text(encoding="utf-8") == "foo\nbar\n"
    # Новый редактор на том же файле — история загружена.
    ed2 = LineEditor(history_file=str(hist))
    assert ed2._history == ["foo", "bar"]


def test_history_load_dedupes_and_trims(tmp_path):
    hist = tmp_path / "h.txt"
    hist.write_text("a\nb\nb\nc\n", encoding="utf-8")
    ed = LineEditor(history_file=str(hist), max_history=2)
    assert ed._history == ["b", "c"]


def test_history_file_has_no_empty_lines(tmp_path):
    hist = tmp_path / "h.txt"
    ed = LineEditor(history_file=str(hist))
    read_keys(ed, ["\r"])
    # Пустой ввод не попадает ни в историю, ни в файл.
    assert not hist.exists() or hist.read_text(encoding="utf-8") == ""


def test_history_not_saved_without_file():
    ed = LineEditor()  # history_file=None
    read_keys(ed, enter("tmp"))
    read_keys(ed, enter("data"))
    assert ed._history == ["tmp", "data"]


# --------------------------------------------------------------------------
# 5. Редактирование строки
# --------------------------------------------------------------------------


def test_backspace():
    ed = LineEditor()
    assert read_keys(ed, ["a", "b", "\x7f", "\r"]) == "a"


def test_backspace_alt_code():
    ed = LineEditor()
    assert read_keys(ed, ["a", "b", "\x08", "\r"]) == "a"


def test_left_right_arrow():
    ed = LineEditor()
    # "abc", Left, Left, X → "aXbc"
    assert read_keys(ed, list("abc") + [LEFT, LEFT, "X", "\r"]) == "aXbc"


def test_home_end():
    ed = LineEditor()
    assert read_keys(ed, list("abc") + [HOME, "X", END, "Y", "\r"]) == "XabcY"


def test_home_end_variants():
    ed = LineEditor()
    # \x1b[1~ / \x1b[4~ — альтернативные Home/End
    assert read_keys(ed, ["a", "b", "\x1b[1~", "X", "\x1b[4~", "Y", "\r"]) == "XabY"


def test_ctrl_a_e():
    ed = LineEditor()
    assert read_keys(ed, ["a", "b", "\x01", "X", "\x05", "Y", "\r"]) == "XabY"


def test_ctrl_k():
    ed = LineEditor()
    # "abcdef", Left, Left (курсор между d и e), Ctrl-K → "abcd"
    assert read_keys(ed, list("abcdef") + [LEFT, LEFT, "\x0b", "\r"]) == "abcd"


def test_ctrl_u():
    ed = LineEditor()
    # "abcdef", Left, Left (курсор после d), Ctrl-U → "ef"
    assert read_keys(ed, list("abcdef") + [LEFT, LEFT, "\x15", "\r"]) == "ef"


def test_ctrl_w():
    ed = LineEditor()
    # "buy food", Ctrl-W → удалить слово слева от курсора → "buy "
    assert read_keys(ed, list("buy food") + ["\x17", "\r"]) == "buy "


def test_delete_key():
    ed = LineEditor()
    assert read_keys(ed, list("abc") + [HOME, DELETE, "\r"]) == "bc"


def test_ctrl_d_deletes_char_right():
    ed = LineEditor()
    assert read_keys(ed, list("abc") + [HOME, "\x04", "\r"]) == "bc"


def test_ctrl_d_eof_on_empty_line():
    ed = LineEditor()
    assert read_keys(ed, ["\x04"]) == ""
    assert ed._history == []


def test_ctrl_c_interrupt():
    ed = LineEditor()
    assert read_keys(ed, ["a", "b", "\x03"]) == ""
    assert ed._history == []


def test_escape_clears_line():
    ed = LineEditor()
    assert read_keys(ed, list("abc") + ["\x1b", "\r"]) == ""


def test_unicode_characters():
    ed = LineEditor()
    assert read_keys(ed, list("привет") + ["\r"]) == "привет"


def test_full_edit_session():
    ed = LineEditor()
    # "hello world" -> Backspace x5 -> "hello " -> Home -> "say " -> End
    keys = list("hello world") + ["\x7f"] * 5 + [HOME] + list("say ") + [END, "\r"]
    assert read_keys(ed, keys) == "say hello "


# --------------------------------------------------------------------------
# 6. Интеграция в game_loop.GameLoop
# --------------------------------------------------------------------------


def make_loop(tmp_path) -> "object":
    from game_loop import GameLoop, GameLogger

    loop = GameLoop(logger=GameLogger(tmp_path / "log.csv"))
    loop.events = MagicMock()  # не писать в elite_events.db
    return loop


def test_game_loop_run_reads_via_editor(tmp_path):
    loop = make_loop(tmp_path)
    fake = MagicMock()
    fake.readline.side_effect = ["status", "quit"]
    loop.editor = fake
    loop.run()
    assert fake.readline.call_args_list == [call("> "), call("> ")]


def test_cmd_refuel_confirms_via_editor(tmp_path):
    loop = make_loop(tmp_path)
    fake = MagicMock()
    fake.readline.return_value = "y"
    loop.editor = fake
    loop.state.fuel = 0.0
    loop.cmd_refuel(["full"])
    assert fake.readline.call_args_list == [call("> ")]
    assert loop.state.fuel == 70.0  # заправка до полного бака выполнена


def test_cmd_refuel_empty_answer_cancels(tmp_path):
    loop = make_loop(tmp_path)
    fake = MagicMock()
    fake.readline.return_value = ""  # EOF / Ctrl-C
    loop.editor = fake
    loop.state.fuel = 0.0
    loop.cmd_refuel(["full"])
    assert fake.readline.called
    assert loop.state.fuel == 0.0  # заправка отменена


@pytest.mark.parametrize("answer", ["n", "no", "нет", "maybe"])
def test_cmd_refuel_negative_answer_cancels(tmp_path, answer):
    loop = make_loop(tmp_path)
    fake = MagicMock()
    fake.readline.return_value = answer
    loop.editor = fake
    loop.state.fuel = 0.0
    loop.cmd_refuel(["full"])
    assert loop.state.fuel == 0.0


def test_encounter_reads_via_editor(tmp_path, monkeypatch):
    from elite_core import GameState as CoreGameState

    monkeypatch.setattr(CoreGameState, "check_pirate_attack", lambda self: True)
    loop = make_loop(tmp_path)
    fake = MagicMock()
    fake.readline.side_effect = ["fight"]  # первый ответ — валидный
    loop.editor = fake
    attacked = loop._encounter()
    assert attacked is True
    assert fake.readline.call_args_list == [
        call(loop.i18n.tr("cmd.combat.prompt"))
    ]


def test_encounter_eof_defaults_to_fight(tmp_path, monkeypatch):
    from elite_core import GameState as CoreGameState

    monkeypatch.setattr(CoreGameState, "check_pirate_attack", lambda self: True)
    loop = make_loop(tmp_path)
    fake = MagicMock()
    fake.readline.side_effect = [""]  # EOF -> fight по умолчанию
    loop.editor = fake
    attacked = loop._encounter()
    # Пустой ввод — это валидный выбор "fight": повторный запрос не нужен.
    assert attacked is True
    assert fake.readline.call_count == 1