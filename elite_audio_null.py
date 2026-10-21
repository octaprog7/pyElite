"""
elite_audio_null.py — no-op аудио-бекенд для pyElite.

Реализация AudioBackend без зависимостей (нет pygame, numpy, elite_core,
elite_i18n). Все методы — no-op; muted=True, available=False. Используется
в headless-режиме и в CI, где звуковая карта отсутствует.

Лицензия: GPL v3.
"""

from __future__ import annotations

from elite_backend import AudioBackend, MusicName, SfxName

__all__ = ["NullAudio"]


class NullAudio(AudioBackend):
    """Аудио-заглушка: не воспроизводит звук и никогда не доступна."""

    def __init__(self, **kwargs) -> None:
        del kwargs  # параметры бекенда игнорируются (совместимость фабрики)

    def init(self) -> None:
        pass

    def play_sfx(self, name: SfxName) -> None:
        pass

    def play_music(self, name: MusicName, loops: int = -1) -> None:
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
        return True

    @property
    def available(self) -> bool:
        return False

    def shutdown(self) -> None:
        pass