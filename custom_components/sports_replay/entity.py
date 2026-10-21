"""Base entity: one device per followed team, refreshed by the replay manager."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_TEAM_ABBR, DOMAIN
from .manager import ReplayManager


class SportsReplayEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        self.manager: ReplayManager = entry.runtime_data
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Sports Replay {entry.data[CONF_TEAM_ABBR]}",
            manufacturer="ESPN data",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.add_listener(self._handle_update))

    def _handle_update(self) -> None:
        self.async_write_ha_state()
