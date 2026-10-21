"""Sports Replay: spoiler-free, play-by-play replay of a game, synced to the broadcast."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import EspnClient
from .const import CONF_LEAGUE, CONF_TEAM_ID, DOMAIN, SERVICE_SEEK
from .manager import ReplayManager

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SportsReplayConfigEntry = ConfigEntry[ReplayManager]

SEEK_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("period"): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
        vol.Required("clock"): vol.Match(r"^\d{1,2}:\d{2}$"),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def seek(call: ServiceCall) -> None:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if entry_id := call.data.get("config_entry_id"):
            entries = [e for e in entries if e.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError("No Sports Replay entry found")
        for entry in entries:
            if not entry.runtime_data.seek_to(call.data["period"], call.data["clock"]):
                raise ServiceValidationError("No loaded game, or no play at that time")

    hass.services.async_register(DOMAIN, SERVICE_SEEK, seek, schema=SEEK_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SportsReplayConfigEntry) -> bool:
    league = entry.data[CONF_LEAGUE]
    client = EspnClient(async_get_clientsession(hass), league)
    manager = ReplayManager(hass, client, league, entry.data[CONF_TEAM_ID])
    await manager.async_refresh_games()
    entry.runtime_data = manager
    entry.async_on_unload(manager.shutdown)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SportsReplayConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
