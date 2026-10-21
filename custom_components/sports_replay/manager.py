"""Replay manager: one per config entry (one followed team).

Owns the loaded game, the timeline and the clock; ticks while playing, fires
``sports_replay_play`` events for the plays crossed and notifies the entities.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .api import EspnClient, EspnError, ScheduledGame
from .const import EVENT_PLAY, TICK_SECONDS
from .engine import (
    Game,
    ReplayClock,
    TimingMode,
    TimingParams,
    build_timeline,
    classify,
    find_play,
    parse_summary,
)

_LOGGER = logging.getLogger(__name__)

RECENT_PLAYS = 15


class ReplayManager:
    def __init__(self, hass: HomeAssistant, client: EspnClient, league: str, team_id: str) -> None:
        self.hass = hass
        self.client = client
        self.league = league
        self.team_id = team_id

        self.games: list[ScheduledGame] = []
        self.game_id: str | None = None
        self.game: Game | None = None
        self.mode = TimingMode.FULL_NO_ADS
        self.params = TimingParams()
        self.clock = ReplayClock(times=[])
        self.error: str | None = None

        self._listeners: list[Callable[[], None]] = []
        self._unsub_tick: CALLBACK_TYPE | None = None

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
    def shutdown(self) -> None:
        self._stop_ticking()

    def _start_ticking(self) -> None:
        if self._unsub_tick is None:
            self._unsub_tick = async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=TICK_SECONDS)
            )

    def _stop_ticking(self) -> None:
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None

    # --- games ---------------------------------------------------------------------------

    @property
    def completed_games(self) -> list[ScheduledGame]:
        return [g for g in self.games if g.completed]

    async def async_refresh_games(self) -> None:
        try:
            self.games = await self.client.schedule(self.team_id)
            self.error = None
        except EspnError as err:
            self.error = str(err)
            _LOGGER.warning("Could not load the schedule: %s", err)
        self._notify()

    async def async_load_game(self, event_id: str) -> None:
        self.pause()
        try:
            game = parse_summary(await self.client.summary(event_id))
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
            return
        now = self._now()
        index = self.clock.current_index(now) if keep_index else -1
        playing = self.clock.playing
        self.clock = ReplayClock(
            times=build_timeline(self.game.plays, self.mode, self.params), speed=self.clock.speed
        )
        if index >= 0:
            self.clock.seek_index(index, now)
        else:
            self.clock.seek(-1.0, now)
        if playing:
            self.clock.play(now)
        self._notify()

    # --- controls ------------------------------------------------------------------------

    def set_mode(self, mode: TimingMode) -> None:
        self.mode = mode
        self._rebuild(keep_index=True)

    def set_params(self, **changes: float) -> None:
        self.params = TimingParams(**{**self.params.__dict__, **changes})
        self._rebuild(keep_index=True)

    def set_speed(self, speed: float) -> None:
        self.clock.set_speed(speed, self._now())
        self._notify()

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
        self._notify()

    def restart(self) -> None:
        self.clock.seek(-1.0, self._now())
        self._notify()

    def step(self, delta: int) -> None:
        if self.game is not None:
            self.clock.step(delta, self._now())
            self._notify()

    def shift(self, seconds: float) -> None:
        now = self._now()
        self.clock.seek(self.clock.position(now) + seconds, now)
        self._notify()

    def align_here(self) -> None:
        """The play on the dashboard is happening now on screen: drop the accumulated drift."""
        now = self._now()
        index = self.clock.current_index(now)
        if index >= 0:
            self.clock.seek_index(index, now)
        self._notify()

    def seek_to(self, period: int, clock: str) -> bool:
        if self.game is None:
            return False
        index = find_play(self.game, period, clock)
        if index is None:
            return False
        self.clock.seek_index(index, self._now())
        self._notify()
        return True

    @callback
    def _tick(self, _now: Any = None) -> None:
        if self.game is None:
            return
        now = self._now()
        for index in self.clock.advance(now):
            self._fire(index)
        if self.clock.position(now) >= self.clock.duration:
            self.clock.pause(now)
            self._stop_ticking()
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
                "team_score": self._score(play, mine),
                "opponent_score": self._score(play, other),
                "team_color": mine.color if mine else None,
                "opponent_color": other.color if other else None,
            },
        )

    # --- state ---------------------------------------------------------------------------

    @property
    def my_team(self):
        if self.game is None:
            return None
        return self.game.team(self.team_id) or self.game.home

    @property
    def other_team(self):
        if self.game is None or self.my_team is None:
            return None
        return self.game.opponent_of(self.my_team.id)

    @staticmethod
    def _score(play, team) -> int:
        if play is None or team is None:
            return 0
        return play.home_score if team.home_away == "home" else play.away_score

    def snapshot(self) -> dict[str, Any]:
        """State of the replay at this moment, in Team Tracker-compatible attribute names."""
        if self.game is None:
            return {"state": "NOT_LOADED", "error": self.error}
        now = self._now()
        index = self.clock.current_index(now)
        plays = self.game.plays
        play = plays[index] if index >= 0 else None
        mine, other = self.my_team, self.other_team

        if index < 0:
            state = "PRE"
        elif index == len(plays) - 1 or (play and play.type_text == "End of Game"):
            state = "POST"
        else:
            state = "IN"

        wp_home = play.home_win_probability if play else None
        team_wp = None
        if wp_home is not None and mine is not None:
            team_wp = wp_home if mine.home_away == "home" else 1 - wp_home

        recent = []
        for i in range(index, max(index - RECENT_PLAYS, -1), -1):
            p = plays[i]
            ev = classify(self.game, i)
            t = self.game.team(ev.team_id)
            recent.append(
                {
                    "period": p.period,
                    "clock": p.clock,
                    "text": p.text,
                    "categories": list(ev.categories),
                    "team": t.abbreviation if t else None,
                }
            )

        history = []
        for p in plays[: index + 1]:
            if p.home_win_probability is not None and mine is not None:
                wp = p.home_win_probability if mine.home_away == "home" else 1 - p.home_win_probability
                history.append(round(wp * 100, 1))

        return {
            "state": state,
            "error": self.error,
            "league": self.league.upper(),
            "event_id": self.game_id,
            "team_abbr": mine.abbreviation if mine else None,
            "team_name": mine.name if mine else None,
            "team_logo": mine.logo if mine else None,
            "team_colors": [f"#{mine.color}", f"#{mine.alternate_color}"] if mine and mine.color else None,
            "team_homeaway": mine.home_away if mine else None,
            "team_score": self._score(play, mine),
            "opponent_abbr": other.abbreviation if other else None,
            "opponent_name": other.name if other else None,
            "opponent_logo": other.logo if other else None,
            "opponent_colors": [f"#{other.color}", f"#{other.alternate_color}"]
            if other and other.color
            else None,
            "opponent_score": self._score(play, other),
            "quarter": play.period if play else None,
            "clock": play.clock if play else None,
            "possession": play.end_team_id if play else None,
            "last_play": play.text if play else None,
            "down_distance_text": play.down_distance_after if play else None,
            "team_win_probability": round(team_wp, 3) if team_wp is not None else None,
            "opponent_win_probability": round(1 - team_wp, 3) if team_wp is not None else None,
            "replay_mode": self.mode.value,
            "replay_playing": self.clock.playing,
            "replay_speed": self.clock.speed,
            # No replay position here: it changes every second and would flood the recorder.
            "play_index": index + 1,
            "play_count": len(plays),
            "recent_plays": recent,
            "win_probability_history": history,
        }
