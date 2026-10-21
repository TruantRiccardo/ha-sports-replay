"""Buttons: replay transport controls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SportsReplayConfigEntry
from .entity import SportsReplayEntity
from .manager import ReplayManager


@dataclass(frozen=True, kw_only=True)
class ReplayButtonDescription(ButtonEntityDescription):
    press: Callable[[ReplayManager], Awaitable[None] | None]


BUTTONS = (
    ReplayButtonDescription(key="play", icon="mdi:play", press=lambda m: m.play()),
    ReplayButtonDescription(key="pause", icon="mdi:pause", press=lambda m: m.pause()),
    ReplayButtonDescription(key="previous_play", icon="mdi:skip-previous", press=lambda m: m.step(-1)),
    ReplayButtonDescription(key="next_play", icon="mdi:skip-next", press=lambda m: m.step(1)),
    ReplayButtonDescription(key="back_10s", icon="mdi:rewind-10", press=lambda m: m.shift(-10)),
    ReplayButtonDescription(key="forward_10s", icon="mdi:fast-forward-10", press=lambda m: m.shift(10)),
    ReplayButtonDescription(key="align_here", icon="mdi:crosshairs-gps", press=lambda m: m.align_here()),
    ReplayButtonDescription(key="restart", icon="mdi:restart", press=lambda m: m.restart()),
    ReplayButtonDescription(
        key="refresh_games", icon="mdi:refresh", press=lambda m: m.async_refresh_games()
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SportsReplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(ReplayButton(entry, d) for d in BUTTONS)


class ReplayButton(SportsReplayEntity, ButtonEntity):
    entity_description: ReplayButtonDescription

    def __init__(self, entry: SportsReplayConfigEntry, description: ReplayButtonDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        """Buttons have no state to refresh on every replay tick."""

    async def async_press(self) -> None:
        result = self.entity_description.press(self.manager)
        if result is not None:
            await result
