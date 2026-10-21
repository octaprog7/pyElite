"""
test_renderer_cli.py — тесты elite_renderer_cli.CLIRenderer.

Вывод перехватывается через capsys, os.system — через monkeypatch.

Лицензия: GPL v3.
"""

from __future__ import annotations

import pytest

from elite_renderer_cli import CLIRenderer
from elite_backend import Renderer, RenderState
from elite_core import CombatResult


@pytest.fixture
def renderer() -> CLIRenderer:
    return CLIRenderer()


@pytest.fixture
def cli_env(monkeypatch):
    """Отключить реальный os.system('clear')."""
    monkeypatch.setattr("os.system", lambda cmd: None)
    return None


def test_init_prints_header(renderer, cli_env, capsys):
    renderer.init()
    out = capsys.readouterr().out
    assert "pyElite (CLI mode)" in out


def test_set_state(renderer):
    renderer.set_state(RenderState.MAP)
    assert renderer._state == RenderState.MAP


def test_render_docked_shows_system(renderer, game_state, i18n, capsys):
    renderer.render(game_state, i18n)
    out = capsys.readouterr().out
    assert game_state.system["name"] in out


def test_render_docked_shows_market(renderer, game_state, i18n, capsys):
    renderer.render(game_state, i18n)
    out = capsys.readouterr().out
    assert "Price(Cr)" in out or "Food" in out


def test_render_map_shows_systems(renderer, game_state, i18n, capsys):
    renderer.set_state(RenderState.MAP)
    renderer.render(game_state, i18n)
    out = capsys.readouterr().out
    assert "Galaxy map" in out
    assert "TIBEDI" in out


def test_render_combat_shows_hint(renderer, game_state, i18n, capsys):
    renderer.set_state(RenderState.COMBAT)
    renderer.render(game_state, i18n)
    out = capsys.readouterr().out
    assert "[F]ight" in out or "PIRATE" in out


def test_render_flight_shows_system(renderer, game_state, i18n, capsys):
    renderer.set_state(RenderState.FLIGHT)
    renderer.render(game_state, i18n)
    out = capsys.readouterr().out
    assert "FLIGHT MODE" in out
    assert game_state.system["name"] in out


def test_jump_progress_percent(renderer, game_state, i18n, capsys):
    renderer.render_jump_progress(game_state, i18n, 0.5)
    assert "50%" in capsys.readouterr().out


def test_jump_progress_complete(renderer, game_state, i18n, capsys):
    renderer.render_jump_progress(game_state, i18n, 1.0)
    out = capsys.readouterr().out
    assert "Jump complete." in out


def test_combat_round_without_result(renderer, game_state, i18n, capsys):
    renderer.render_combat_round(game_state, i18n, 2, 5, 40, None)
    out = capsys.readouterr().out
    assert "Round 2/5" in out
    assert "Enemy damage: -40" in out


def test_combat_round_destroyed(renderer, game_state, i18n, capsys):
    result = CombatResult(action="fight", success=False, message="boom",
                          status="destroyed", destroyed=True)
    renderer.render_combat_round(game_state, i18n, 1, 1, 120, result)
    assert "destroyed" in capsys.readouterr().out


def test_combat_round_with_result(renderer, game_state, i18n, capsys):
    result = CombatResult(action="fight", success=True, message="win",
                          status="fight_win")
    renderer.render_combat_round(game_state, i18n, 1, 1, 40, result)
    assert "fight_win" in capsys.readouterr().out


def test_poll_events_empty(renderer):
    assert renderer.poll_events() == []


def test_tick_zero(renderer):
    assert renderer.tick() == 0


def test_get_jump_target_none(renderer):
    assert renderer.get_jump_target() is None


def test_show_message_noop(renderer):
    renderer.show_message("hello")   # не падает


def test_shutdown(renderer, capsys):
    assert renderer.is_active is True
    renderer.shutdown()
    assert renderer.is_active is False
    assert "Goodbye" in capsys.readouterr().out


def test_isinstance_renderer(renderer):
    assert isinstance(renderer, Renderer)