"""Replay manager: one per config entry (one followed team).

Owns the loaded game, the timeline and the clock; ticks while playing, fires
``sports_replay_play`` events for the plays crossed and notifies the entities.
The game, the play reached and the settings survive a Home Assistant restart.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import EspnClient, EspnError, ScheduledGame
from .const import DOMAIN, EVENT_PLAY, LEAGUES, TICK_SECONDS
from .replay import (
    DEFAULT_MODE,
    Game,
    Play,
    ReplayClock,
    Sport,
    Team,
    TimingMode,
    TimingParams,
    build_timeline,
    classify,
    find_play,
    parse_summary,
    timeouts_remaining,
)

_LOGGER = logging.getLogger(__name__)

RECENT_PLAYS = 15
SCHEDULE_REFRESH = timedelta(hours=6)
STORAGE_VERSION = 1
SAVE_DELAY = 5  # seconds


class ReplayManager:
    def __init__(
        self, hass: HomeAssistant, client: EspnClient, league: str, team_id: str, entry_id: str
    ) -> None:
        self.hass = hass
        self.client = client
        self.league = league
        self.sport = Sport(LEAGUES[league].sport)
        self.team_id = team_id

        self.games: list[ScheduledGame] = []
        self.game_id: str | None = None
        self.game: Game | None = None
        self.mode = DEFAULT_MODE[self.sport]
        self.params = TimingParams()
        self.clock = ReplayClock(times=[])
        self.error: str | None = None

        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self._listeners: list[Callable[[], None]] = []
        self._unsub_tick: CALLBACK_TYPE | None = None
        self._unsub_schedule: CALLBACK_TYPE | None = None
        self._snapshot_key: tuple | None = None
        self._snapshot: dict[str, Any] = {}

    # --- plumbing ------------------------------------------------------------------------

    def _now(self) -> float:
        return self.hass.loop.time()

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def start(self) -> None:
        self._unsub_schedule = async_track_time_interval(
            self.hass, self._scheduled_refresh, SCHEDULE_REFRESH
        )

    @callback
    def shutdown(self) -> None:
        self._stop_ticking()
        if self._unsub_schedule is not None:
            self._unsub_schedule()
            self._unsub_schedule = None

    async def _scheduled_refresh(self, _now: Any = None) -> None:
        await self.async_refresh_games()

    def _start_ticking(self) -> None:
        if self._unsub_tick is None:
            self._unsub_tick = async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=TICK_SECONDS)
            )

    def _stop_ticking(self) -> None:
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None

    # --- persistence ---------------------------------------------------------------------

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "play_index": self.clock.current_index(self._now()) if self.game else -1,
            "mode": self.mode.value,
            "params": asdict(self.params),
            "speed": self.clock.speed,
        }

    async def async_restore(self) -> None:
        """Settings, then the game and the play reached (paused): needs the ESPN API."""
        data = await self._store.async_load() or {}
        try:
            self.mode = TimingMode(data.get("mode", self.mode.value))
            self.params = TimingParams(**{**asdict(self.params), **data.get("params", {})})
            self.clock.speed = float(data.get("speed", self.clock.speed))
        except (TypeError, ValueError):
            _LOGGER.warning("Ignoring invalid stored settings: %s", data)
        if game_id := data.get("game_id"):
            await self.async_load_game(game_id)
            index = data.get("play_index", -1)
            if self.game is not None and isinstance(index, int) and index >= 0:
                self.clock.seek_index(index, self._now())
        self._notify()

    # --- games ---------------------------------------------------------------------------

    @property
    def completed_games(self) -> list[ScheduledGame]:
        return [g for g in self.games if g.completed]

    async def async_refresh_games(self) -> bool:
        try:
            self.games = await self.client.schedule(self.team_id)
            self.error = None
        except EspnError as err:
            self.error = str(err)
            _LOGGER.warning("Could not load the schedule: %s", err)
        self._notify()
        return self.error is None

    async def async_load_game(self, event_id: str) -> None:
        self.pause()
        try:
            game = parse_summary(await self.client.summary(event_id), self.sport)
        except (EspnError, KeyError, IndexError, TypeError) as err:
            self.error = f"Could not load game {event_id}: {err}"
            _LOGGER.warning(self.error)
            self._notify()
            return
        if not game.plays:
            self.error = f"Game {event_id} has no play-by-play yet"
            self._notify()
            return
        self.game_id, self.game, self.error = event_id, game, None
        self._rebuild(keep_index=False)

    def _rebuild(self, keep_index: bool) -> None:
        """Recompute the timeline (after a mode/param change), staying on the same play."""
        if self.game is None:
            self._changed()
            return
        now = self._now()
        index = self.clock.current_index(now) if keep_index else -1
        playing = self.clock.playing
        self.clock = ReplayClock(
            times=build_timeline(self.game, self.mode, self.params), speed=self.clock.speed
        )
        if index >= 0:
            self.clock.seek_index(index, now)
        else:
            self.clock.seek(-1.0, now)
        if playing:
            self.clock.play(now)
        self._changed()

    @callback
    def _changed(self) -> None:
        """A user action changed the replay: refresh the entities and persist."""
        self._notify()
        self._save()

    # --- controls ------------------------------------------------------------------------

    def set_mode(self, mode: TimingMode) -> None:
        self.mode = mode
        self._rebuild(keep_index=True)

    def set_params(self, **changes: float) -> None:
        self.params = TimingParams(**{**asdict(self.params), **changes})
        self._rebuild(keep_index=True)

    def set_speed(self, speed: float) -> None:
        self.clock.set_speed(speed, self._now())
        self._changed()

    def play(self) -> None:
        if self.game is None:
            return
        now = self._now()
        if self.clock.current_index(now) >= len(self.clock.times) - 1:
            self.clock.seek(-1.0, now)  # at the end: start over
        self.clock.play(now)
        self._start_ticking()
        self._tick()

    def pause(self) -> None:
        self.clock.pause(self._now())
        self._stop_ticking()
        self._changed()

    def restart(self) -> None:
        self.clock.seek(-1.0, self._now())
        self._changed()

    def step(self, delta: int) -> None:
        if self.game is not None:
            self.clock.step(delta, self._now())
            self._changed()

    def shift(self, seconds: float) -> None:
        now = self._now()
        self.clock.seek(self.clock.position(now) + seconds, now)
        self._changed()

    def align_here(self) -> None:
        """The play on the dashboard is happening now on screen: drop the accumulated drift."""
        now = self._now()
        index = self.clock.current_index(now)
        if index >= 0:
            self.clock.seek_index(index, now)
        self._changed()

    def seek_to(self, period: int, clock: str) -> bool:
        if self.game is None:
            return False
        index = find_play(self.game, period, clock)
        if index is None:
            return False
        self.clock.seek_index(index, self._now())
        self._changed()
        return True

    @callback
    def _tick(self, _now: Any = None) -> None:
        if self.game is None:
            return
        now = self._now()
        crossed = self.clock.advance(now)
        for index in crossed:
            self._fire(index)
        if self.clock.position(now) >= self.clock.duration:
            self.clock.pause(now)
            self._stop_ticking()
            self._save()
        elif crossed:
            self._save()
        self._notify()

    def _fire(self, index: int) -> None:
        assert self.game is not None
        play = self.game.plays[index]
        event = classify(self.game, index)
        team = self.game.team(event.team_id)
        mine, other = self.my_team, self.other_team
        self.hass.bus.async_fire(
            EVENT_PLAY,
            {
                "mode": "replay",
                "league": self.league,
                "event_id": self.game_id,
                "play_id": play.id,
                "categories": list(event.categories),
                "team": team.abbreviation if team else None,
                "team_id": event.team_id,
                "is_my_team": event.team_id == self.team_id,
                "text": play.text,
                "period": play.period,
                "clock": play.clock,
                "team_score": _score(play, mine),
                "opponent_score": _score(play, other),
                "team_color": f"#{mine.color}" if mine and mine.color else None,
                "opponent_color": f"#{other.color}" if other and other.color else None,
            },
        )

    # --- state ---------------------------------------------------------------------------

    @property
    def my_team(self) -> Team | None:
        if self.game is None:
            return None
        return self.game.team(self.team_id) or self.game.home

    @property
    def other_team(self) -> Team | None:
        if self.game is None or self.my_team is None:
            return None
        return self.game.opponent_of(self.my_team.id)

    def snapshot(self) -> dict[str, Any]:
        """State of the replay, Team Tracker-compatible; recomputed only when it can change."""
        index = self.clock.current_index(self._now()) if self.game else -1
        key = (self.game_id, index, self.mode, self.clock.anchor, self.error)
        if key != self._snapshot_key:
            self._snapshot = self._build_snapshot(index)
            self._snapshot_key = key
        return self._snapshot

    def _wall_times(self) -> dict[str, Any]:
        """The replay as a timer: when it started and when it ends, in wall-clock time.

        They change only on play/pause/seek/speed, never while the replay runs, so a card
        (timer-bar-card, a timestamp in an entities card) can animate the progress itself.
        """
        now = self._now()
        position = max(self.clock.position(now), 0.0)
        speed = self.clock.speed or 1.0
        wall_now = dt_util.utcnow()
        playing = self.clock.playing
        return {
            "replay_position": round(position),
            "replay_started_at": _iso(wall_now - timedelta(seconds=position / speed)) if playing else None,
            "replay_ends_at": _iso(wall_now + timedelta(seconds=(self.clock.duration - position) / speed))
            if playing
            else None,
        }

    def _build_snapshot(self, index: int) -> dict[str, Any]:
        if self.game is None:
            return {"state": "NOT_LOADED", "error": self.error}
        game, plays = self.game, self.game.plays
        play = plays[index] if index >= 0 else None
        mine, other = self.my_team, self.other_team
        assert mine is not None and other is not None

        if index < 0:
            state = "PRE"
        elif index == len(plays) - 1 or "end_game" in classify(game, index).categories:
            state = "POST"
        else:
            state = "IN"

        team_wp = _team_wp(play, mine)
        football = game.sport is Sport.FOOTBALL
        home_to = away_to = None  # timeouts: football only
        if football:
            home_to, away_to = timeouts_remaining(game, index) if index >= 0 else (3, 3)
        team_score, opponent_score = _score(play, mine), _score(play, other)

        recent = []
        for i in range(index, max(index - RECENT_PLAYS, -1), -1):
            p = plays[i]
            ev = classify(game, i)
            t = game.team(ev.team_id)
            recent.append(
                {
                    "period": p.period,
                    "clock": p.clock,
                    "text": p.text,
                    "categories": list(ev.categories),
                    "team": t.abbreviation if t else None,
                }
            )
        history = [round(wp * 100, 1) for p in plays[: index + 1] if (wp := _team_wp(p, mine)) is not None]

        return {
            "state": state,
            "error": self.error,
            # Team Tracker-compatible
            "sport": game.sport.value,
            "league": self.league.upper(),
            "event_id": self.game_id,
            "event_name": game.name,
            "date": game.date.isoformat() if game.date else None,
            "team_id": mine.id,
            "team_abbr": mine.abbreviation,
            "team_name": mine.name,
            "team_logo": mine.logo,
            "team_colors": _colors(mine),
            "team_homeaway": mine.home_away,
            "team_score": team_score,
            "team_timeouts": home_to if mine.home_away == "home" else away_to,
            "team_win_probability": round(team_wp, 3) if team_wp is not None else None,
            "team_winner": team_score > opponent_score if state == "POST" else None,
            "opponent_id": other.id,
            "opponent_abbr": other.abbreviation,
            "opponent_name": other.name,
            "opponent_logo": other.logo,
            "opponent_colors": _colors(other),
            "opponent_homeaway": other.home_away,
            "opponent_score": opponent_score,
            "opponent_timeouts": home_to if other.home_away == "home" else away_to,
            "opponent_win_probability": round(1 - team_wp, 3) if team_wp is not None else None,
            "opponent_winner": opponent_score > team_score if state == "POST" else None,
            "quarter": play.period if play else None,
            "clock": play.clock if play else None,
            "possession": play.end_team_id if play and football else None,
            "last_play": play.text if play else None,
            "down_distance_text": play.down_distance_after if play and football else None,
            "last_update": dt_util.utcnow().isoformat(),
            # Replay-specific. Positions are those of the current play, not of the running clock:
            # a value changing every second would flood the recorder.
            "replay_mode": self.mode.value,
            "replay_playing": self.clock.playing,
            "replay_speed": self.clock.speed,
            "replay_time": round(max(self.clock.times[index], 0)) if index >= 0 else 0,
            "replay_duration": round(self.clock.duration),
            **self._wall_times(),
            "play_index": index + 1,
            "play_count": len(plays),
            "recent_plays": recent,
            "win_probability_history": history,
        }


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _score(play: Play | None, team: Team | None) -> int:
    if play is None or team is None:
        return 0
    return play.home_score if team.home_away == "home" else play.away_score


def _team_wp(play: Play | None, team: Team) -> float | None:
    if play is None or play.home_win_probability is None:
        return None
    return play.home_win_probability if team.home_away == "home" else 1 - play.home_win_probability


def _colors(team: Team) -> list[str] | None:
    if not team.color:
        return None
    return [f"#{team.color}", f"#{team.alternate_color or team.color}"]
