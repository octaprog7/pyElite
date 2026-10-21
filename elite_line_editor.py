"""
elite_line_editor.py — кроссплатформенный line editor с историей команд.

Стиль Midnight Commander: собственный редактор строки поверх raw terminal I/O,
без readline/ncurses/prompt_toolkit — только стандартная библиотека Python 3.10+.

Поддерживаемые клавиши:
  Enter                       — завершить ввод
  Up / Down                   — навигация по истории команд
  Left / Right                — движение курсора
  Home / End                  — начало / конец строки
  Backspace / Delete          — удаление слева / справа от курсора
  Ctrl-A / Ctrl-E             — начало / конец строки (как Home/End)
  Ctrl-B / Ctrl-F             — курсор влево / вправо (бонус, как в readline)
  Ctrl-K                      — удалить от курсора до конца строки
  Ctrl-U                      — удалить от начала строки до курсора
  Ctrl-W                      — удалить слово слева от курсора
  Ctrl-D                      — EOF (в пустой строке) или удалить символ справа
  Ctrl-C                      — прервать ввод (вернуть пустую строку)
  Escape                      — очистить текущую строку (как в MC)

Платформы:
  * Unix (Linux/macOS): raw-режим через ``tty.setraw`` + ``termios``;
    посимвольное чтение через ``os.read(fd, 1)`` с поддержкой многобайтового
    UTF-8; одиночный Escape распознаётся по таймауту (select).
  * Windows: ``msvcrt.getch()`` — посимвольное чтение без переключения
    терминала в raw-режим; специальные клавиши маппятся на CSI-последовательности.
  * non-tty (CI, pipe, redirect): если ``sys.stdin.isatty()`` == False,
    ``readline()`` работает как обычный ``input(prompt)`` — без raw-режима.

История:
  Хранится в памяти (self._history, новые команды в конце) и опционально
  персистится в history_file (одна команда на строку, UTF-8). Путь
  history_file трактуется как есть: относительный — от текущего рабочего
  каталога (рядом с game_loop.py при запуске из репозитория), абсолютный —
  как указано. По умолчанию история только в памяти (history_file=None).

Лицензия: GPL v3.
"""

from __future__ import annotations

import os
import select
import sys

try:
    import termios
    import tty

    _HAS_TERMIOS = True
except ImportError:  # Windows или платформа без termios
    _HAS_TERMIOS = False

_IS_WINDOWS: bool = os.name == "nt"

# Таймаут ожидания продолжения ESC-последовательности (сек). Если после ESC
# данные не пришли — это одиночный Escape (очистка строки, как в MC).
ESC_SEQ_TIMEOUT: float = 0.1

# Специальные клавиши Windows -> CSI-последовательности (как в MC):
#   H=Up, P=Down, K=Left, M=Right, G=Home, O=End, S=Delete.
_WIN_KEY_MAP: dict[bytes, str] = {
    b"H": "A",   # Up
    b"P": "B",   # Down
    b"K": "D",   # Left
    b"M": "C",   # Right
    b"G": "H",   # Home
    b"O": "F",   # End
    b"S": "3~",  # Delete
}


# --------------------------------------------------------------------------
# Низкоуровневый ввод (raw terminal I/O)
# --------------------------------------------------------------------------


def _os_read(fd: int, n: int) -> bytes:
    """Прочитать до n байт из fd (raw-режим). Возвращает b'' при EOF."""
    try:
        data = os.read(fd, n)
    except OSError:
        return b""
    return data if data is not None else b""


def _data_ready(fd: int, timeout: float) -> bool:
    """True, если в fd появились данные в течение timeout (select)."""
    try:
        readable, _, _ = select.select([fd], [], [], timeout)
    except (OSError, ValueError):
        return False
    return bool(readable)


def _decode_char(fd: int, first: bytes) -> str:
    """Декодировать обычный символ; дочитать продолжения многобайтового UTF-8."""
    b0 = first[0]
    if b0 < 0x80:
        return first.decode("utf-8", errors="replace")
    if 0xC2 <= b0 <= 0xDF:
        need = 1
    elif 0xE0 <= b0 <= 0xEF:
        need = 2
    elif 0xF0 <= b0 <= 0xF4:
        need = 3
    else:
        return first.decode("utf-8", errors="replace")
    rest = b""
    while len(rest) < need:
        chunk = _os_read(fd, 1)
        if not chunk:
            break
        rest += chunk
    return (first + rest).decode("utf-8", errors="replace")


def _read_key_windows() -> str:
    """Прочитать один keypress через msvcrt (Windows)."""
    import msvcrt  # доступен только на Windows

    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):  # special/function key
        ch2 = msvcrt.getch()
        # H=up, P=down, K=left, M=right, G=home, O=end, S=delete
        return "\x1b[" + _WIN_KEY_MAP.get(ch2, "?")
    return ch.decode("utf-8", errors="replace")


def _read_key_unix(fd: int) -> str:
    """Прочитать один keypress в raw-режиме (Unix/macOS).

    Обычные символы (включая многобайтовый UTF-8) возвращаются как есть;
    управляющие последовательности — в форме '\\x1b[...' (стрелки, Home/End,
    Delete). Одиночный Escape распознаётся по таймауту ESC_SEQ_TIMEOUT.
    """
    first = _os_read(fd, 1)
    if not first:
        return ""
    if first != b"\x1b":
        return _decode_char(fd, first)
    # Возможно, ESC — начало управляющей последовательности.
    if not _data_ready(fd, ESC_SEQ_TIMEOUT):
        return "\x1b"  # одиночный Escape (в MC — очистка строки)
    seq = first + _os_read(fd, 1)
    if seq[-1:] == b"[":
        seq += _os_read(fd, 1)
        if seq[-1:].isdigit():
            seq += _os_read(fd, 1)
    return seq.decode("utf-8", errors="replace")


def _read_key(fd: int | None = None) -> str:
    """Прочитать один keypress (диспетчер по платформе)."""
    if _IS_WINDOWS:
        return _read_key_windows()
    if fd is None:
        fd = sys.stdin.fileno()
    return _read_key_unix(fd)


def _make_raw(fd: int) -> object:
    """Включить raw-режим терминала (Unix). Вернуть прежние атрибуты."""
    if not _HAS_TERMIOS:
        return None
    old: object = termios.tcgetattr(fd)
    tty.setraw(fd)
    return old


def _restore_terminal(fd: int, old: object) -> None:
    """Восстановить прежний режим терминала (Unix)."""
    if _HAS_TERMIOS and old is not None:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# --------------------------------------------------------------------------
# LineEditor
# --------------------------------------------------------------------------


class LineEditor:
    """Кроссплатформенный line editor с историей команд.

    Стиль Midnight Commander: raw terminal I/O, без readline/ncurses.
    Поддерживает навигацию по истории (Up/Down), движение курсора
    (Left/Right/Home/End), удаление (Backspace/Delete) и редакторные
    комбинации (Ctrl-A, Ctrl-E, Ctrl-K, Ctrl-U, Ctrl-W).
    """

    def __init__(
        self,
        prompt: str = "> ",
        history_file: str | None = None,
        max_history: int = 1000,
    ) -> None:
        self.prompt: str = prompt
        self.history_file: str | None = history_file
        self.max_history: int = max_history
        self._history: list[str] = []
        self._history_pos: int | None = None
        self._saved_input: str = ""
        self._load_history()

    # ------------------------------------------------------------- I/O

    @staticmethod
    def _write(text: str) -> None:
        """Вывести текст в stdout без перевода строки."""
        sys.stdout.write(text)

    @staticmethod
    def _flush() -> None:
        sys.stdout.flush()

    def _is_tty(self) -> bool:
        """True, если stdin — интерактивный терминал (иначе fallback на input)."""
        try:
            return bool(sys.stdin.isatty())
        except (AttributeError, OSError, ValueError):
            return False

    def _stdin_fileno(self) -> int:
        """Файловый дескриптор stdin (для raw-режима и чтения клавиш)."""
        return sys.stdin.fileno()

    # ------------------------------------------------------------- rendering

    def _render(self, prompt: str, buffer: str, cursor: int) -> None:
        """Перерисовать строку: \\r + очистка + prompt + buffer + курсор.

        Курсор после вывода находится в конце буфера; откатываем его назад
        на (len(buffer) - cursor) позиций через CSI '\\x1b[{n}D'.
        """
        out = "\r\x1b[K" + prompt + buffer
        back = len(buffer) - cursor
        if back > 0:
            out += f"\x1b[{back}D"
        self._write(out)
        self._flush()

    # ------------------------------------------------------------- history

    def _add_history(self, line: str) -> None:
        """Добавить команду в историю (без пустых строк и дубликатов подряд)."""
        if not line:
            return
        if self._history and self._history[-1] == line:
            return
        self._history.append(line)
        overflow = len(self._history) - self.max_history
        if overflow > 0:
            del self._history[:overflow]
        if self.history_file:
            self._save_history()

    def _load_history(self) -> None:
        """Загрузить историю из history_file (UTF-8, одна команда на строку)."""
        if not self.history_file:
            return
        path = os.path.expanduser(self.history_file)
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.rstrip("\r\n")
                    if line and (not self._history or self._history[-1] != line):
                        self._history.append(line)
        except OSError:
            return
        overflow = len(self._history) - self.max_history
        if overflow > 0:
            del self._history[:overflow]

    def _save_history(self) -> None:
        """Сохранить историю в history_file (перезаписывает файл)."""
        if not self.history_file:
            return
        path = os.path.expanduser(self.history_file)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for line in self._history:
                    fh.write(line + "\n")
        except OSError:
            pass

    def _history_up(self, buffer: str, cursor: int) -> tuple[str, int]:
        """Стрелка вверх: предыдущая команда (текущий ввод сохраняется)."""
        if not self._history:
            return buffer, cursor
        if self._history_pos is None:
            self._saved_input = buffer
            self._history_pos = len(self._history) - 1
        elif self._history_pos > 0:
            self._history_pos -= 1
        line = self._history[self._history_pos]
        return line, len(line)

    def _history_down(self, buffer: str, cursor: int) -> tuple[str, int]:
        """Стрелка вниз: следующая команда; за концом — сохранённый ввод."""
        if self._history_pos is None:
            return buffer, cursor
        if self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            line = self._history[self._history_pos]
            return line, len(line)
        # Достигли конца истории — вернуть незавершённый ввод пользователя.
        self._history_pos = None
        saved = self._saved_input
        self._saved_input = ""
        return saved, len(saved)

    # ------------------------------------------------------------- readline

    def readline(self, prompt: str | None = None) -> str:
        """Прочитать строку с редактированием и историей.

        Возвращает строку (без завершающего \\n).
        Пустая строка при EOF (Ctrl-D в начале строки) или Ctrl-C.

        В non-tty режиме (pipe, redirect, CI) — fallback на ``input(prompt)``:
        там EOF/Ctrl-C тоже превращаются в пустую строку.
        """
        prompt = prompt if prompt is not None else self.prompt
        if not self._is_tty():
            try:
                return input(prompt)
            except (EOFError, KeyboardInterrupt):
                return ""
        return self._readline_tty(prompt)

    def _readline_tty(self, prompt: str) -> str:
        """Интерактивное чтение строки в raw-режиме (tty)."""
        fd = self._stdin_fileno()
        buffer = ""
        cursor = 0
        self._history_pos = None
        self._saved_input = ""

        self._write(prompt)
        self._flush()

        old: object | None = None
        if not _IS_WINDOWS:
            old = _make_raw(fd)
        result: str | None = None
        try:
            while result is None:
                try:
                    ch = _read_key(fd)
                except StopIteration:
                    ch = ""  # поток клавиш исчерпан (защита для тестов)
                if not ch:
                    # EOF (конец потока ввода)
                    result = buffer
                    continue
                if ch in ("\r", "\n"):
                    self._add_history(buffer)
                    result = buffer
                    continue
                if ch == "\x03":  # Ctrl-C — прервать ввод
                    result = ""
                    continue
                if ch == "\x04":  # Ctrl-D — EOF в пустой строке, иначе Delete
                    if not buffer:
                        result = ""
                        continue
                    buffer = buffer[:cursor] + buffer[cursor + 1:]
                    self._render(prompt, buffer, cursor)
                    continue
                if ch in ("\x7f", "\x08"):  # Backspace
                    if cursor > 0:
                        buffer = buffer[:cursor - 1] + buffer[cursor:]
                        cursor -= 1
                        self._render(prompt, buffer, cursor)
                    continue
                if ch == "\x1b[3~":  # Delete — удалить символ справа
                    if cursor < len(buffer):
                        buffer = buffer[:cursor] + buffer[cursor + 1:]
                        self._render(prompt, buffer, cursor)
                    continue
                if ch in ("\x1b[D", "\x02"):  # Left / Ctrl-B
                    if cursor > 0:
                        cursor -= 1
                        self._render(prompt, buffer, cursor)
                    continue
                if ch in ("\x1b[C", "\x06"):  # Right / Ctrl-F
                    if cursor < len(buffer):
                        cursor += 1
                        self._render(prompt, buffer, cursor)
                    continue
                if ch == "\x1b[A":  # Up — предыдущая команда
                    buffer, cursor = self._history_up(buffer, cursor)
                    self._render(prompt, buffer, cursor)
                    continue
                if ch == "\x1b[B":  # Down — следующая команда
                    buffer, cursor = self._history_down(buffer, cursor)
                    self._render(prompt, buffer, cursor)
                    continue
                if ch in ("\x1b[H", "\x1b[1~") or ch == "\x01":  # Home / Ctrl-A
                    if cursor:
                        cursor = 0
                        self._render(prompt, buffer, cursor)
                    continue
                if ch in ("\x1b[F", "\x1b[4~") or ch == "\x05":  # End / Ctrl-E
                    if cursor != len(buffer):
                        cursor = len(buffer)
                        self._render(prompt, buffer, cursor)
                    continue
                if ch == "\x0b":  # Ctrl-K — удалить до конца строки
                    if cursor < len(buffer):
                        buffer = buffer[:cursor]
                        self._render(prompt, buffer, cursor)
                    continue
                if ch == "\x15":  # Ctrl-U — удалить от начала до курсора
                    if cursor:
                        buffer = buffer[cursor:]
                        cursor = 0
                        self._render(prompt, buffer, cursor)
                    continue
                if ch == "\x17":  # Ctrl-W — удалить слово слева
                    start = cursor
                    while start > 0 and buffer[start - 1] == " ":
                        start -= 1
                    while start > 0 and buffer[start - 1] != " ":
                        start -= 1
                    if start != cursor:
                        buffer = buffer[:start] + buffer[cursor:]
                        cursor = start
                        self._render(prompt, buffer, cursor)
                    continue
                if ch == "\x1b":  # одиночный Escape — очистить строку (MC)
                    if buffer:
                        buffer = ""
                        cursor = 0
                        self._render(prompt, buffer, cursor)
                    continue
                # Обычный печатный символ (в т.ч. многобайтовый UTF-8).
                if ch >= " ":
                    buffer = buffer[:cursor] + ch + buffer[cursor:]
                    cursor += 1
                    self._render(prompt, buffer, cursor)
        finally:
            if not _IS_WINDOWS:
                _restore_terminal(fd, old)

        # Терминал восстановлен (cooked-режим) — перевод строки завершает ввод.
        self._write("\n")
        self._flush()
        return result