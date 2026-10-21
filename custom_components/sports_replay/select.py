"""Selects: the game to replay (spoiler-free labels) and the timing mode."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SportsReplayConfigEntry
from .replay import TimingMode
from .entity import SportsReplayEntity

NO_GAME = "—"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SportsReplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([GameSelect(entry, "game_select"), ModeSelect(entry, "mode")])


class GameSelect(SportsReplayEntity, SelectEntity):
    """Completed games only, newest first; labels never show the score."""

    @property
    def options(self) -> list[str]:
        return [NO_GAME] + [g.label for g in reversed(self.manager.completed_games)]

    @property
    def current_option(self) -> str:
        for g in self.manager.games:
            if g.event_id == self.manager.game_id:
                return g.label
        return NO_GAME

    async def async_select_option(self, option: str) -> None:
        for g in self.manager.games:
            if g.label == option:
                await self.manager.async_load_game(g.event_id)
                return


class ModeSelect(SportsReplayEntity, SelectEntity):
    _attr_options = [m.value for m in TimingMode]

    @property
    def current_option(self) -> str:
        return self.manager.mode.value

    async def async_select_option(self, option: str) -> None:
        self.manager.set_mode(TimingMode(option))
