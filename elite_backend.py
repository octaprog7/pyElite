"""
elite_backend.py — абстрактные бекенды (графика + звук) для pyElite.

Протоколы Renderer и AudioBackend (PEP 544, typing.Protocol с
@runtime_checkable) задают контракт для взаимозаменяемых реализаций:

  * PygameRenderer  / PygameAudio   — pygame-ce (GUI);
  * CLIRenderer                     — текстовый вывод в терминал (без pygame);
  * NullAudio                       — no-op аудио (headless / CI).

Ядро (elite_core.py) НЕ знает, какой бекенд под капотом: game_loop_gui.py
принимает объекты, реализующие протоколы из этого модуля; сборка бекендов
происходит в точке входа через фабрики create_renderer()/create_audio().

Типы elite_core и elite_i18n импортируются только для аннотаций. Модуль не
зависит от pygame и numpy; импорт pygame-реализаций — ленивый (в фабриках).

Лицензия: GPL v3.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from elite_core import (
    CombatResult,
    GameState,
    JumpResult,
    MarketRow,
    RefuelResult,
    ShipDefense,
    SystemRow,
)
from elite_i18n import I18n

__all__ = [
    "RenderState",
    "SfxName",
    "MusicName",
    "GameEvent",
    "Renderer",
    "AudioBackend",
    "create_renderer",
    "create_audio",
]


# --------------------------------------------------------------------------
# Игровые состояния и имена эффектов
# --------------------------------------------------------------------------


class RenderState(enum.Enum):
    """Режим отрисовки (game state)."""

    DOCKED = "docked"
    FLIGHT = "flight"
    COMBAT = "combat"
    MAP = "map"
    JUMP = "jump"


class SfxName(enum.Enum):
    """Имена звуковых эффектов."""

    LASER = "laser"
    HIT_SHIELD = "hit_shield"
    HIT_HULL = "hit_hull"
    EXPLOSION = "explosion"
    JUMP = "jump"
    DOCK = "dock"
    BUY = "buy"
    SELL = "sell"
    WARNING = "warning"
    CLICK = "click"
    SELECT = "select"


class MusicName(enum.Enum):
    """Имена фонового эмбиента."""

    AMBIENT_STATION = "ambient_station"
    AMBIENT_SPACE = "ambient_space"
    AMBIENT_COMBAT = "ambient_combat"


# --------------------------------------------------------------------------
# Абстрактные события ввода
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class GameEvent:
    """Абстрактное событие ввода, не зависящее от бекенда.

    kind: "quit" | "key" | "mouse_click" | "mouse_motion" | "text_input".
    key: имена клавиш — нижний регистр, без префиксов ("escape", "return",
    "f", "e", "s", "m", "f11", ...).
    """

    kind: str
    key: str | None = None
    text: str | None = None
    mouse_pos: tuple[int, int] | None = None
    mouse_button: int | None = None


# --------------------------------------------------------------------------
# Протокол Renderer
# --------------------------------------------------------------------------


@runtime_checkable
class Renderer(Protocol):
    """Контракт графического бекенда (pygame, терминал, ...)."""

    def init(self) -> None:
        """Инициализация бекенда. Вызывается ОДИН раз перед render()."""

    def set_state(self, state: RenderState) -> None:
        """Переключение режима отрисовки."""

    def render(self, game_state: GameState, i18n: I18n) -> None:
        """Главная точка отрисовки кадра по текущему режиму."""

    def render_jump_progress(
        self, game_state: GameState, i18n: I18n, progress: float
    ) -> None:
        """Кадр анимации прыжка. progress 0.0 → 1.0."""

    def render_combat_round(
        self,
        game_state: GameState,
        i18n: I18n,
        round_num: int,
        total_rounds: int,
        enemy_damage: int,
        result: CombatResult | None,
    ) -> None:
        """Кадр одного раунда боя. result — финальный CombatResult или None."""

    def poll_events(self) -> list[GameEvent]:
        """Опрос событий ввода; возвращает список GameEvent."""

    def tick(self) -> int:
        """Тик кадра. Возвращает FPS (в CLI — 0)."""

    def shutdown(self) -> None:
        """Корректное завершение бекенда."""

    @property
    def is_active(self) -> bool:
        """True, если бекенд активен (окно не закрыто / терминал жив)."""

    def get_jump_target(self) -> int | None:
        """Индекс выбранной на карте системы для прыжка (или None)."""

    def show_message(self, msg: str) -> None:
        """Получить сообщение от game loop для отображения на экране."""


# --------------------------------------------------------------------------
# Протокол AudioBackend
# --------------------------------------------------------------------------


@runtime_checkable
class AudioBackend(Protocol):
    """Контракт аудио-бекенда."""

    def init(self) -> None:
        """Инициализация аудио. НЕ вызывать на уровне модуля!"""

    def play_sfx(self, name: SfxName) -> None:
        """Воспроизвести звуковой эффект."""

    def play_music(self, name: MusicName, loops: int = -1) -> None:
        """Фоновая музыка; loops=-1 — бесконечно."""

    def stop_music(self) -> None:
        """Остановить музыку."""

    def stop_all(self) -> None:
        """Остановить музыку и все каналы."""

    def set_music_volume(self, vol: float) -> None:
        """Громкость музыки 0.0–1.0."""

    def set_sfx_volume(self, vol: float) -> None:
        """Громкость SFX 0.0–1.0."""

    def toggle_mute(self) -> None:
        """Переключить mute."""

    @property
    def muted(self) -> bool:
        """True, если звук заглушён."""

    @property
    def available(self) -> bool:
        """True, если аудио доступно (есть звуковая карта)."""

    def shutdown(self) -> None:
        """Освободить ресурсы аудио."""


# --------------------------------------------------------------------------
# Фабрики (ленивый импорт реализаций — без циклических зависимостей)
# --------------------------------------------------------------------------


def create_renderer(backend: str = "pygame", **kwargs) -> Renderer:
    """Создать рендерер по имени бекенда.

    backend="pygame" → PygameRenderer(**kwargs),
    backend="cli"    → CLIRenderer(**kwargs).
    """
    if backend == "pygame":
        from elite_renderer_pygame import PygameRenderer

        return PygameRenderer(**kwargs)
    if backend == "cli":
        from elite_renderer_cli import CLIRenderer

        return CLIRenderer(**kwargs)
    raise ValueError(
        f"unknown renderer backend: {backend!r} "
        f"(available: 'pygame', 'cli')"
    )


def create_audio(backend: str = "pygame", **kwargs) -> AudioBackend:
    """Создать аудио-бекенд по имени.

    backend="pygame" → PygameAudio(**kwargs),
    backend="null"   → NullAudio().
    """
    if backend == "pygame":
        from elite_audio_pygame import PygameAudio

        return PygameAudio(**kwargs)
    if backend == "null":
        from elite_audio_null import NullAudio

        return NullAudio(**kwargs)
    raise ValueError(
        f"unknown audio backend: {backend!r} "
        f"(available: 'pygame', 'null')"
    )