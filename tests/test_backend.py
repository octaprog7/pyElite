"""
test_backend.py — тесты elite_backend: enums, GameEvent, протоколы, фабрики.

Лицензия: GPL v3.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import elite_backend as backend
from elite_backend import (
    AudioBackend,
    GameEvent,
    MusicName,
    Renderer,
    RenderState,
    SfxName,
    create_audio,
    create_renderer,
)


# --------------------------------------------------------------------------
# 1. Enum
# --------------------------------------------------------------------------


def test_render_state_values():
    assert {s.value for s in RenderState} == {
        "docked", "flight", "combat", "map", "jump"}


def test_sfx_name_values():
    assert {s.value for s in SfxName} == {
        "laser", "hit_shield", "hit_hull", "explosion", "jump", "dock",
        "buy", "sell", "warning", "click", "select"}


def test_music_name_values():
    assert {m.value for m in MusicName} == {
        "ambient_station", "ambient_space", "ambient_combat"}


def test_enum_counts():
    assert len(RenderState) == 5
    assert len(SfxName) == 11
    assert len(MusicName) == 3


# --------------------------------------------------------------------------
# 2. GameEvent
# --------------------------------------------------------------------------


def test_game_event_frozen():
    ev = GameEvent(kind="key", key="f")
    with pytest.raises(FrozenInstanceError):
        ev.kind = "quit"  # type: ignore[misc]


def test_game_event_fields():
    ev = GameEvent(kind="mouse_click", mouse_pos=(10, 20), mouse_button=1)
    assert ev.kind == "mouse_click"
    assert ev.mouse_pos == (10, 20)
    assert ev.mouse_button == 1
    assert ev.key is None and ev.text is None


def test_game_event_eq():
    assert GameEvent(kind="key", key="m") == GameEvent(kind="key", key="m")
    assert GameEvent(kind="key", key="m") != GameEvent(kind="key", key="n")


# --------------------------------------------------------------------------
# 3. Протоколы (@runtime_checkable)
#
# Примечание: в Python >= 3.12 runtime_checkable проверяет атрибуты КЛАССА,
# поэтому MagicMock (у которого атрибуты только через __getattr__) не
# проходит isinstance — используем маленькие fake-реализации.
# --------------------------------------------------------------------------


class FakeRenderer:
    """Реализация протокола Renderer (минимальная)."""

    def init(self) -> None:
        pass

    def set_state(self, state) -> None:
        pass

    def render(self, game_state, i18n) -> None:
        pass

    def render_jump_progress(self, game_state, i18n, progress) -> None:
        pass

    def render_combat_round(self, game_state, i18n, round_num, total_rounds,
                            enemy_damage, result) -> None:
        pass

    def poll_events(self):
        return []

    def tick(self) -> int:
        return 0

    def shutdown(self) -> None:
        pass

    @property
    def is_active(self) -> bool:
        return True

    def get_jump_target(self):
        return None

    def show_message(self, msg: str) -> None:
        pass


class FakeAudio:
    """Реализация протокола AudioBackend (минимальная)."""

    def init(self) -> None:
        pass

    def play_sfx(self, name) -> None:
        pass

    def play_music(self, name, loops: int = -1) -> None:
        pass

    def stop_music(self) -> None:
        pass

    def stop_all(self) -> None:
        pass

    def set_music_volume(self, vol: float) -> None:
        pass

    def set_sfx_volume(self, vol: float) -> None:
        pass

    def toggle_mute(self) -> None:
        pass

    @property
    def muted(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return True

    def shutdown(self) -> None:
        pass


def test_renderer_runtime_checkable():
    assert isinstance(FakeRenderer(), Renderer)


def test_audio_backend_runtime_checkable():
    assert isinstance(FakeAudio(), AudioBackend)


def test_protocol_negative():
    class NotARenderer:
        pass

    assert not isinstance(NotARenderer(), Renderer)
    assert not isinstance(NotARenderer(), AudioBackend)


# --------------------------------------------------------------------------
# 4. Фабрики
# --------------------------------------------------------------------------


def test_create_renderer_cli():
    renderer = create_renderer("cli")
    from elite_renderer_cli import CLIRenderer
    assert isinstance(renderer, CLIRenderer)
    assert isinstance(renderer, Renderer)


def test_create_audio_null():
    audio = create_audio("null")
    from elite_audio_null import NullAudio
    assert isinstance(audio, NullAudio)
    assert isinstance(audio, AudioBackend)


def test_create_renderer_unknown_raises():
    with pytest.raises(ValueError):
        create_renderer("bogus")
    with pytest.raises(ValueError):
        create_audio("bogus")