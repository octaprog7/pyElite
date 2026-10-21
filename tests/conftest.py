"""
conftest.py — общие фикстуры для тестов pyElite.

Headless SDL для pygame-тестов: dummy-драйверы видео и аудио устанавливаются
ДО импорта pygame (тесты работают в CI без дисплея и звуковой карты).

Лицензия: GPL v3.
"""

from __future__ import annotations

import os

# Headless SDL (должно быть до импорта pygame)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest
from unittest.mock import MagicMock

from elite_core import GameState
from elite_i18n import I18n


@pytest.fixture
def game_state() -> GameState:
    """Свежий GameState, галактика 0, система 0 (TIBEDI)."""
    gs = GameState(galaxy=0, system_index=0)
    gs.load_system()
    return gs


@pytest.fixture
def i18n() -> I18n:
    """I18n с локалью по умолчанию (en)."""
    return I18n()


@pytest.fixture
def mock_renderer():
    """Mock рендерер, реализующий протокол Renderer (CLI-подобный)."""
    r = MagicMock()
    r.is_active = True
    r.screen = None  # CLI-подобный (нет pygame surface)
    r.get_jump_target.return_value = None
    r.poll_events.return_value = []
    r.tick.return_value = 60
    return r


@pytest.fixture
def mock_audio():
    """Mock аудио, реализующий протокол AudioBackend."""
    a = MagicMock()
    a.muted = False
    a.available = True
    return a


@pytest.fixture
def mock_renderer_pygame():
    """Mock рендерер с атрибутом screen (имитация pygame)."""
    r = MagicMock()
    r.is_active = True
    r.screen = MagicMock()  # не None → pygame-подобный
    r.get_jump_target.return_value = None
    r.poll_events.return_value = []
    r.tick.return_value = 60
    return r