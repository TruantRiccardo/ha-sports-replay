"""Numbers: replay speed and the timing tunables."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SportsReplayConfigEntry
from .entity import SportsReplayEntity


@dataclass(frozen=True, kw_only=True)
class ReplayNumberDescription(NumberEntityDescription):
    param: str | None = None  # TimingParams field; None for the speed


NUMBERS = (
    ReplayNumberDescription(
        key="speed", icon="mdi:speedometer", native_min_value=0.25, native_max_value=4,
        native_step=0.25, mode=NumberMode.BOX,
    ),
    ReplayNumberDescription(
        key="gap_threshold", param="gap_threshold", native_min_value=30, native_max_value=600,
        native_step=5, native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.CONFIG, mode=NumberMode.BOX,
    ),
    ReplayNumberDescription(
        key="gap_pause", param="gap_pause", native_min_value=0, native_max_value=180,
        native_step=5, native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.CONFIG, mode=NumberMode.BOX,
    ),
    ReplayNumberDescription(
        key="condensed_per_play", param="condensed_per_play", native_min_value=3,
        native_max_value=60, native_step=1, native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.CONFIG, mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SportsReplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(ReplayNumber(entry, d) for d in NUMBERS)


class ReplayNumber(SportsReplayEntity, NumberEntity):
    entity_description: ReplayNumberDescription

    def __init__(self, entry: SportsReplayConfigEntry, description: ReplayNumberDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        if self.entity_description.param is None:
            return self.manager.clock.speed
        return getattr(self.manager.params, self.entity_description.param)

    async def async_set_native_value(self, value: float) -> None:
        if self.entity_description.param is None:
            self.manager.set_speed(value)
        else:
            self.manager.set_params(**{self.entity_description.param: value})
