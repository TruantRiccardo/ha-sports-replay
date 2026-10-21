"""Sensors: the game (Team Tracker-compatible attributes) and the team's win probability."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SportsReplayConfigEntry
from .entity import SportsReplayEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SportsReplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([GameSensor(entry, "game"), WinProbabilitySensor(entry, "win_probability")])


class GameSensor(SportsReplayEntity, SensorEntity):
    """State PRE / IN / POST like Team Tracker (NOT_LOADED before a game is picked)."""

    _unrecorded_attributes = frozenset(
        {"recent_plays", "win_probability_history", "team_logo", "opponent_logo", "last_update"}
    )

    @property
    def native_value(self) -> str:
        return self.manager.snapshot()["state"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # The snapshot is cached and shared: never mutate it.
        return {k: v for k, v in self.manager.snapshot().items() if k != "state"}


class WinProbabilitySensor(SportsReplayEntity, SensorEntity):
    """No state class on purpose: replays would pollute long-term statistics."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0

    @property
    def native_value(self) -> float | None:
        wp = self.manager.snapshot().get("team_win_probability")
        return None if wp is None else round(wp * 100, 1)
