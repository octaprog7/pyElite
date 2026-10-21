"""
test_audio_null.py — тесты elite_audio_null.NullAudio.

Все методы — no-op; muted=True, available=False. Никаких зависимостей
(pygame, numpy, elite_core, elite_i18n).

Лицензия: GPL v3.
"""

from __future__ import annotations

import pytest

from elite_audio_null import NullAudio
from elite_backend import AudioBackend, MusicName, SfxName


@pytest.fixture
def audio() -> NullAudio:
    return NullAudio()


def test_init_noop(audio):
    audio.init()


@pytest.mark.parametrize("sfx", list(SfxName))
def test_play_sfx_noop(audio, sfx):
    audio.play_sfx(sfx)


@pytest.mark.parametrize("music", list(MusicName))
def test_play_music_noop(audio, music):
    audio.play_music(music)
    audio.play_music(music, loops=3)


def test_stop_music_noop(audio):
    audio.stop_music()


def test_stop_all_noop(audio):
    audio.stop_all()


def test_volume_noop(audio):
    audio.set_music_volume(0.5)
    audio.set_sfx_volume(0.9)


def test_toggle_mute_noop(audio):
    audio.toggle_mute()


def test_muted_property(audio):
    assert audio.muted is True


def test_available_property(audio):
    assert audio.available is False


def test_shutdown_noop(audio):
    audio.shutdown()


def test_isinstance_audio_backend(audio):
    assert isinstance(audio, AudioBackend)