"""Sports Replay: spoiler-free, play-by-play replay of a game, synced to the broadcast."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import EspnClient
from .api import EspnError
from .const import CONF_LEAGUE, CONF_TEAM_ABBR, CONF_TEAM_ID, CONF_TEAM_NAME, DOMAIN, SERVICE_SEEK
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
    if CONF_TEAM_NAME not in entry.data:
        await _add_team_name(hass, entry, client)
    manager = ReplayManager(hass, client, league, entry.data[CONF_TEAM_ID], entry.entry_id)
    if not await manager.async_refresh_games():
        raise ConfigEntryNotReady(manager.error)
    entry.runtime_data = manager
    manager.start()
    entry.async_on_unload(manager.shutdown)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # The last game is reloaded from ESPN: do not hold up Home Assistant's startup for it.
    entry.async_create_background_task(hass, manager.async_restore(), f"{DOMAIN} restore")
    return True


async def _add_team_name(hass: HomeAssistant, entry: ConfigEntry, client: EspnClient) -> None:
    """Entries created by 0.1.0 have no short team name: look it up once (abbreviation if offline)."""
    name = entry.data[CONF_TEAM_ABBR]
    try:
        teams = await client.teams()
        name = next((t["short_name"] for t in teams if t["id"] == entry.data[CONF_TEAM_ID]), name)
    except EspnError:
        return  # try again at the next start
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TEAM_NAME: name})


async def async_unload_entry(hass: HomeAssistant, entry: SportsReplayConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
