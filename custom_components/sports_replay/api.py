"""Thin async client for the public (unofficial) ESPN site API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

from .const import ESPN_BASE_URL, LEAGUES

TIMEOUT = aiohttp.ClientTimeout(total=20)


class EspnError(Exception):
    """The ESPN API did not answer, or answered with something unexpected."""


@dataclass(frozen=True)
class ScheduledGame:
    """A game of the schedule. Deliberately carries no score or winner: spoiler-free."""

    event_id: str
    date: datetime
    short_name: str  # "WSH @ SF"
    week: str  # "Week 6", or "" when ESPN gives none
    completed: bool

    @property
    def label(self) -> str:
        week = f"{self.week} · " if self.week else ""
        return f"{week}{self.short_name} · {self.date:%Y-%m-%d}"


class EspnClient:
    def __init__(self, session: aiohttp.ClientSession, league: str) -> None:
        self._session = session
        self._path = LEAGUES[league]

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with self._session.get(url, params=params, timeout=TIMEOUT) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise EspnError(f"{url}: {err}") from err

    async def teams(self) -> list[dict[str, str]]:
        """[{id, abbreviation, name}], sorted by name."""
        data = await self._get(f"{ESPN_BASE_URL}/{self._path}/teams", {"limit": 1000})
        try:
            raw = data["sports"][0]["leagues"][0]["teams"]
        except (KeyError, IndexError) as err:
            raise EspnError(f"unexpected teams payload: {err}") from err
        teams = [
            {
                "id": str(t["team"]["id"]),
                "abbreviation": t["team"].get("abbreviation", ""),
                "name": t["team"].get("displayName", ""),
            }
            for t in raw
        ]
        return sorted(teams, key=lambda t: t["name"])

    async def schedule(self, team_id: str) -> list[ScheduledGame]:
        """Regular season and postseason games of the team, oldest first."""
        games: dict[str, ScheduledGame] = {}
        for season_type in (2, 3):
            data = await self._get(
                f"{ESPN_BASE_URL}/{self._path}/teams/{team_id}/schedule", {"seasontype": season_type}
            )
            for e in data.get("events") or []:
                try:
                    status = e["competitions"][0]["status"]["type"]
                    date = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                except (KeyError, IndexError, ValueError):
                    continue
                games[str(e["id"])] = ScheduledGame(
                    event_id=str(e["id"]),
                    date=date,
                    short_name=e.get("shortName", ""),
                    week=(e.get("week") or {}).get("text", ""),
                    completed=bool(status.get("completed")),
                )
        return sorted(games.values(), key=lambda g: g.date)

    async def summary(self, event_id: str) -> dict[str, Any]:
        return await self._get(f"{ESPN_BASE_URL}/{self._path}/summary", {"event": event_id})
