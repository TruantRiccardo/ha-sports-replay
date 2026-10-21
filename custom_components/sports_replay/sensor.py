"""Sensors: the game (Team Tracker-compatible attributes) and one sensor per piece of state.

The game sensor keeps everything in its attributes for cards and templates; the others make
the same state visible on the device page and usable in automations without templates.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util, slugify

from . import SportsReplayConfigEntry
from .const import CONF_TEAM_ABBR, CONF_TEAM_NAME
from .entity import SportsReplayEntity
from .manager import ReplayManager
from .replay import Sport

MAX_STATE_LENGTH = 255

STATUS_OPTIONS = ["not_loaded", "ready", "playing", "paused", "finished"]


def _status(m: ReplayManager, s: dict[str, Any]) -> str:
    if m.game is None:
        return "not_loaded"
    if s["replay_playing"]:
        return "playing"
    if s["state"] == "POST":
        return "finished"
    if s["play_index"] == 0:
        return "ready"
    return "paused"


def _progress(m: ReplayManager, s: dict[str, Any]) -> float | None:
    if not s.get("play_count"):
        return None
    return round(100 * s["play_index"] / s["play_count"])


_PERIOD_PREFIX = {Sport.FOOTBALL: "Q", Sport.BASKETBALL: "Q", Sport.HOCKEY: "P"}
_REGULAR_PERIODS = {Sport.FOOTBALL: 4, Sport.BASKETBALL: 4, Sport.HOCKEY: 3}
_SOCCER_PERIODS = {1: "1st half", 2: "2nd half", 3: "ET 1st half", 4: "ET 2nd half", 5: "Penalties"}


def _period(m: ReplayManager, s: dict[str, Any]) -> str | None:
    q = s.get("quarter")
    if not q:
        return None
    if m.sport is Sport.SOCCER:
        return _SOCCER_PERIODS.get(q, str(q))
    regular = _REGULAR_PERIODS[m.sport]
    if q <= regular:
        return f"{_PERIOD_PREFIX[m.sport]}{q}"
    extra = q - regular
    return "OT" if extra == 1 else f"OT{extra}"


def _possession(m: ReplayManager, s: dict[str, Any]) -> str | None:
    team = m.game.team(s.get("possession")) if m.game else None
    return team.abbreviation if team else None


def _text(key: str) -> Callable[[ReplayManager, dict[str, Any]], str | None]:
    def value(m: ReplayManager, s: dict[str, Any]) -> str | None:
        v = s.get(key)
        return None if v is None else str(v)[:MAX_STATE_LENGTH]

    return value


def _replay_end(m: ReplayManager, s: dict[str, Any]) -> datetime | None:
    ends = s.get("replay_ends_at")
    return dt_util.parse_datetime(ends) if ends else None


def _timer_attributes(m: ReplayManager) -> dict[str, Any]:
    """The replay as a timer, e.g. for timer-bar-card (start_time/end_time attributes)."""
    s = m.snapshot()
    return {
        "started_at": s.get("replay_started_at"),
        "ends_at": s.get("replay_ends_at"),
        "position": s.get("replay_position"),
        "duration": s.get("replay_duration"),
        "speed": s.get("replay_speed"),
    }


# Attributes holding lists of players: kept out of the recorder.
_PLAYER_LISTS = ("passers", "rushers", "receivers", "players", "on_court")


def _side_stats(side: str) -> Callable[[ReplayManager, dict[str, Any]], Any]:
    """Headline statistic: total yards (football), field goal % (basketball)."""

    def value(m: ReplayManager, s: dict[str, Any]) -> Any:
        stats = m.stats()
        if not stats:
            return None
        team = stats[side]
        if m.sport is Sport.BASKETBALL:
            return round(100 * team["fgm"] / team["fga"]) if team["fga"] else None
        return team["total_yards"]

    return value


def _side_stats_attributes(side: str) -> Callable[[ReplayManager], dict[str, Any]]:
    def attributes(m: ReplayManager) -> dict[str, Any]:
        stats = m.stats()
        if not stats:
            return {}
        return {k: v for k, v in stats[side].items() if k not in _PLAYER_LISTS}

    return attributes


def _leader(side: str) -> Callable[[ReplayManager, dict[str, Any]], Any]:
    """Football: the quarterback's line ("B.Purdy 21/29, 264 yds"), else the leading rusher.
    Basketball: the top scorer ("P. George 38 pts, 5 reb, 3 ast")."""

    def value(m: ReplayManager, s: dict[str, Any]) -> Any:
        stats = m.stats()
        if not stats:
            return None
        team = stats[side]
        if m.sport is Sport.BASKETBALL:
            if players := team["players"]:
                p = players[0]
                return f"{p['name']} {p['points']} pts, {p['rebounds']} reb, {p['assists']} ast"
            return None
        if passers := team["passers"]:
            p = passers[0]
            return f"{p['name']} {p['completions']}/{p['attempts']}, {p['yards']} yds"
        if rushers := team["rushers"]:
            r = rushers[0]
            return f"{r['name']} {r['carries']} car, {r['yards']} yds"
        return None

    return value


def _players_attributes(side: str) -> Callable[[ReplayManager], dict[str, Any]]:
    def attributes(m: ReplayManager) -> dict[str, Any]:
        stats = m.stats()
        if not stats:
            return {}
        return {k: stats[side][k] for k in _PLAYER_LISTS if k in stats[side]}

    return attributes


def _on_court(side: str) -> Callable[[ReplayManager, dict[str, Any]], Any]:
    def value(m: ReplayManager, s: dict[str, Any]) -> Any:
        stats = m.stats()
        return ", ".join(stats[side]["on_court"])[:MAX_STATE_LENGTH] if stats else None

    return value


def _key(key: str) -> Callable[[ReplayManager, dict[str, Any]], Any]:
    return lambda m, s: s.get(key)


@dataclass(frozen=True, kw_only=True)
class ReplaySensorDescription(SensorEntityDescription):
    value: Callable[[ReplayManager, dict[str, Any]], Any]
    sports: frozenset[Sport] | None = None  # None: every sport
    # Name with the configured team's short name ("49ers score"); the entity id keeps this
    # generic suffix instead, the same for every team: sensor.sports_replay_sf_team_score.
    team_object_id: str | None = None
    attributes: Callable[[ReplayManager], dict[str, Any]] | None = None
    player_lists: bool = False  # attributes are player lists: kept out of the recorder


FOOTBALL = frozenset({Sport.FOOTBALL})
BASKETBALL = frozenset({Sport.BASKETBALL})
STATS_SPORTS = FOOTBALL | BASKETBALL

SENSORS = (
    ReplaySensorDescription(
        key="status", icon="mdi:play-pause", device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS, value=_status, attributes=_timer_attributes,
    ),
    ReplaySensorDescription(
        key="replay_end", icon="mdi:flag-checkered", device_class=SensorDeviceClass.TIMESTAMP,
        value=_replay_end,
    ),
    ReplaySensorDescription(
        key="progress", icon="mdi:progress-clock", native_unit_of_measurement=PERCENTAGE,
        value=_progress,
    ),
    ReplaySensorDescription(
        key="replay_time", icon="mdi:timer-outline", device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS, suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0, value=lambda m, s: s.get("replay_time") if m.game else None,
    ),
    ReplaySensorDescription(
        key="replay_duration", icon="mdi:timer-sand", device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS, suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0, value=lambda m, s: s.get("replay_duration") if m.game else None,
    ),
    ReplaySensorDescription(
        key="team_score", icon="mdi:scoreboard", team_object_id="team_score",
        value=lambda m, s: s.get("team_score") if m.game else None,
    ),
    ReplaySensorDescription(
        key="opponent_score", icon="mdi:scoreboard-outline",
        value=lambda m, s: s.get("opponent_score") if m.game else None,
    ),
    ReplaySensorDescription(key="period", icon="mdi:numeric", value=_period),
    ReplaySensorDescription(key="game_clock", icon="mdi:clock-outline", value=_text("clock")),
    ReplaySensorDescription(key="last_play", icon="mdi:text-short", value=_text("last_play")),
    ReplaySensorDescription(
        key="down_distance", icon="mdi:football", sports=FOOTBALL, value=_text("down_distance_text"),
    ),
    ReplaySensorDescription(
        key="possession", icon="mdi:football-helmet", sports=FOOTBALL, value=_possession,
    ),
    ReplaySensorDescription(
        key="team_timeouts", icon="mdi:timer-pause", sports=FOOTBALL, team_object_id="team_timeouts_left",
        value=_key("team_timeouts"),
    ),
    ReplaySensorDescription(
        key="opponent_timeouts", icon="mdi:timer-pause-outline", sports=FOOTBALL,
        value=_key("opponent_timeouts"),
    ),
    # Statistics up to the current play.
    *(
        ReplaySensorDescription(
            key=f"{side}_stats", icon="mdi:chart-box" if side == "team" else "mdi:chart-box-outline",
            sports=frozenset({sport}), team_object_id="team_stats" if side == "team" else None,
            native_unit_of_measurement=unit, value=_side_stats(side),
            attributes=_side_stats_attributes(side),
        )
        for side in ("team", "opponent")
        for sport, unit in ((Sport.FOOTBALL, "yd"), (Sport.BASKETBALL, PERCENTAGE))
    ),
    *(
        ReplaySensorDescription(
            key=f"{side}_players", icon="mdi:account-group" if side == "team" else "mdi:account-group-outline",
            sports=STATS_SPORTS, team_object_id="team_players" if side == "team" else None,
            value=_leader(side), attributes=_players_attributes(side), player_lists=True,
        )
        for side in ("team", "opponent")
    ),
    *(
        ReplaySensorDescription(
            key=f"{side}_on_court", icon="mdi:basketball" if side == "team" else "mdi:basketball-hoop-outline",
            sports=BASKETBALL, team_object_id="team_on_court" if side == "team" else None,
            value=_on_court(side),
        )
        for side in ("team", "opponent")
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SportsReplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    sport = entry.runtime_data.sport
    entities: list[SensorEntity] = [GameSensor(entry, "game"), WinProbabilitySensor(entry, "win_probability")]
    entities += [
        (PlayersSensor if d.player_lists else ReplaySensor)(entry, d)
        for d in SENSORS
        if d.sports is None or sport in d.sports
    ]
    async_add_entities(entities)


class GameSensor(SportsReplayEntity, SensorEntity):
    """State PRE / IN / POST like Team Tracker (NOT_FOUND before a game is picked)."""

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


class ReplaySensor(SportsReplayEntity, SensorEntity):
    """One value of the snapshot. No state class: see WinProbabilitySensor."""

    entity_description: ReplaySensorDescription

    def __init__(self, entry: SportsReplayConfigEntry, description: ReplaySensorDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description
        if description.team_object_id:
            abbr = entry.data[CONF_TEAM_ABBR]
            self._attr_translation_placeholders = {"team": entry.data.get(CONF_TEAM_NAME, abbr)}
            self.entity_id = f"sensor.{slugify(f'sports_replay_{abbr}')}_{description.team_object_id}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.manager, self.manager.snapshot())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes is None:
            return None
        return self.entity_description.attributes(self.manager)


class PlayersSensor(ReplaySensor):
    """Home Assistant reads unrecorded attributes per class, not per entity: hence a subclass."""

    _unrecorded_attributes = frozenset(_PLAYER_LISTS)
