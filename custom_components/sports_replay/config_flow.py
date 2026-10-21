"""Config flow: pick a league, then a team."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import EspnClient, EspnError
from .const import CONF_LEAGUE, CONF_TEAM_ABBR, CONF_TEAM_ID, CONF_TEAM_NAME, DOMAIN, LEAGUES


class SportsReplayConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._league: str | None = None
        self._teams: list[dict[str, str]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._league = user_input[CONF_LEAGUE]
            return await self.async_step_team()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LEAGUE, default="nfl"): SelectSelector(
                        SelectSelectorConfig(
                            options=list(LEAGUES),
                            translation_key=CONF_LEAGUE,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_team(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._league is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            team = next(t for t in self._teams if t["id"] == user_input[CONF_TEAM_ID])
            await self.async_set_unique_id(f"{self._league}_{team['id']}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"{team['name']} ({LEAGUES[self._league].name})",
                data={
                    CONF_LEAGUE: self._league,
                    CONF_TEAM_ID: team["id"],
                    CONF_TEAM_ABBR: team["abbreviation"],
                    CONF_TEAM_NAME: team["short_name"],
                },
            )
        if not self._teams:
            try:
                client = EspnClient(async_get_clientsession(self.hass), self._league)
                self._teams = await client.teams()
            except EspnError:
                errors["base"] = "cannot_connect"
        options = [SelectOptionDict(value=t["id"], label=t["name"]) for t in self._teams]
        return self.async_show_form(
            step_id="team",
            data_schema=vol.Schema(
                {vol.Required(CONF_TEAM_ID): SelectSelector(SelectSelectorConfig(options=options))}
            ),
            errors=errors,
        )
