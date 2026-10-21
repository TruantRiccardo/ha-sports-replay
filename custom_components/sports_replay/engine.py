"""Replay engine: pure Python, no Home Assistant imports, so it can be unit-tested offline.

Turns an ESPN ``summary`` payload into a timeline of plays, each with a replay time in
seconds, and drives a clock over that timeline that reports which plays were crossed.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from statistics import median
from typing import Any


class TimingMode(StrEnum):
    """How replay time is derived from the plays."""

    # Full game replay with the commercial breaks cut: wall-clock gaps, long gaps compressed.
    FULL_NO_ADS = "full_no_ads"
    # Recording of the live broadcast, commercials included: raw wall-clock gaps.
    BROADCAST = "broadcast"
    # Condensed game: a fixed duration per play.
    CONDENSED = "condensed"


@dataclass(frozen=True)
class TimingParams:
    """Tunables of the timing modes, in seconds."""

    gap_threshold: float = 90.0  # FULL_NO_ADS: gaps longer than this are treated as a break...
    gap_pause: float = 40.0  # ...and shortened to this
    condensed_per_play: float = 13.0  # CONDENSED: duration of every play
    min_gap: float = 3.0  # floor for zero/negative wall-clock gaps (plays logged out of order)


@dataclass(frozen=True)
class Team:
    id: str
    abbreviation: str
    name: str
    home_away: str  # "home" | "away"
    color: str | None = None  # hex without '#', as ESPN returns it
    alternate_color: str | None = None
    logo: str | None = None


@dataclass(frozen=True)
class Play:
    id: str
    sequence: int
    type_id: str
    type_text: str
    text: str
    period: int
    clock: str
    wallclock: datetime | None
    home_score: int
    away_score: int
    offense_team_id: str | None  # team in possession at the snap
    end_team_id: str | None  # team in possession after the play
    down_distance_before: str | None
    down_distance_after: str | None
    yards_to_endzone_before: int | None
    yards_to_endzone_after: int | None
    stat_yardage: int
    scoring: bool
    scoring_type: str | None  # "touchdown", "field-goal", "safety", ...
    is_turnover: bool
    home_win_probability: float | None  # 0..1, after the play


@dataclass
class Game:
    event_id: str
    home: Team
    away: Team
    plays: list[Play] = field(default_factory=list)

    def team(self, team_id: str | None) -> Team | None:
        if team_id == self.home.id:
            return self.home
        if team_id == self.away.id:
            return self.away
        return None

    def opponent_of(self, team_id: str | None) -> Team | None:
        if team_id == self.home.id:
            return self.away
        if team_id == self.away.id:
            return self.home
        return None


# --- parsing -------------------------------------------------------------------------------


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _team_from_competitor(comp: dict[str, Any]) -> Team:
    team = comp.get("team", {})
    logos = team.get("logos") or []
    logo = team.get("logo") or (logos[0].get("href") if logos else None)
    return Team(
        id=str(team.get("id", "")),
        abbreviation=team.get("abbreviation", ""),
        name=team.get("displayName") or team.get("name", ""),
        home_away=comp.get("homeAway", ""),
        color=team.get("color"),
        alternate_color=team.get("alternateColor"),
        logo=logo,
    )


def parse_summary(data: dict[str, Any]) -> Game:
    """Build a Game from an ESPN football ``summary`` payload (NFL, college football)."""
    competition = data["header"]["competitions"][0]
    teams = {c.get("homeAway"): _team_from_competitor(c) for c in competition["competitors"]}
    game = Game(event_id=str(data["header"].get("id", "")), home=teams["home"], away=teams["away"])

    win_prob = {
        str(w.get("playId")): w.get("homeWinPercentage")
        for w in data.get("winprobability") or []
        if w.get("playId") is not None
    }

    raw = [p for d in (data.get("drives") or {}).get("previous", []) for p in d.get("plays", [])]
    # Some feeds also carry the drive in progress (live games).
    current = (data.get("drives") or {}).get("current")
    if current:
        known = {p.get("id") for p in raw}
        raw += [p for p in current.get("plays", []) if p.get("id") not in known]

    plays = []
    for p in raw:
        start, end = p.get("start") or {}, p.get("end") or {}
        scoring_type = (p.get("scoringType") or {}).get("name")
        plays.append(
            Play(
                id=str(p.get("id", "")),
                sequence=_int(p.get("sequenceNumber")),
                type_id=str((p.get("type") or {}).get("id", "")),
                type_text=(p.get("type") or {}).get("text", ""),
                text=p.get("text", ""),
                period=_int((p.get("period") or {}).get("number")),
                clock=(p.get("clock") or {}).get("displayValue", ""),
                wallclock=_parse_time(p.get("wallclock")),
                home_score=_int(p.get("homeScore")),
                away_score=_int(p.get("awayScore")),
                offense_team_id=(start.get("team") or {}).get("id"),
                end_team_id=(end.get("team") or {}).get("id"),
                down_distance_before=start.get("downDistanceText"),
                down_distance_after=end.get("downDistanceText"),
                yards_to_endzone_before=start.get("yardsToEndzone"),
                yards_to_endzone_after=end.get("yardsToEndzone"),
                stat_yardage=_int(p.get("statYardage")),
                scoring=bool(p.get("scoringPlay")),
                scoring_type=scoring_type,
                is_turnover=bool(p.get("isTurnover")),
                home_win_probability=win_prob.get(str(p.get("id"))),
            )
        )
    plays.sort(key=lambda pl: pl.sequence)
    game.plays = plays
    return game


# --- timeline ------------------------------------------------------------------------------


def build_timeline(plays: list[Play], mode: TimingMode, params: TimingParams | None = None) -> list[float]:
    """Replay time (seconds from the first play) at which each play happens.

    Plays without a wall-clock time get the median gap of the game, so a few missing
    timestamps do not stall or rush the replay.
    """
    params = params or TimingParams()
    if not plays:
        return []
    if mode is TimingMode.CONDENSED:
        return [i * params.condensed_per_play for i in range(len(plays))]

    raw_gaps: list[float | None] = []
    for prev, cur in zip(plays, plays[1:]):
        if prev.wallclock and cur.wallclock:
            raw_gaps.append((cur.wallclock - prev.wallclock).total_seconds())
        else:
            raw_gaps.append(None)
    known = [g for g in raw_gaps if g is not None and g > 0]
    fallback = median(known) if known else params.gap_pause

    times = [0.0]
    for gap in raw_gaps:
        g = fallback if gap is None else gap
        g = max(g, params.min_gap)
        if mode is TimingMode.FULL_NO_ADS and g > params.gap_threshold:
            g = params.gap_pause
        times.append(times[-1] + g)
    return times


# --- event categories ----------------------------------------------------------------------

BIG_PLAY_YARDS = 20
# Non-scoring rushes and receptions: the only plays that count as big plays or red zone entries
# (kick returns, field goals and penalties would otherwise be credited to the wrong team).
_SCRIMMAGE_TYPES = {"5", "24"}  # Rush, Pass Reception


@dataclass(frozen=True)
class PlayEvent:
    """What a play means, from the point of view of the automations."""

    categories: tuple[str, ...]
    team_id: str | None  # the team the event is "for": scorer, team that gained the ball, offense
    opponent_id: str | None


def classify(game: Game, index: int) -> PlayEvent:
    """Categories of a football play: touchdown, field_goal, safety, turnover, ... ."""
    play = game.plays[index]
    prev = game.plays[index - 1] if index > 0 else None
    cats: list[str] = []
    team_id = play.offense_team_id
    text = play.type_text.lower()

    # Scoring: credit the team whose score went up, which also covers defensive scores.
    prev_home = prev.home_score if prev else 0
    prev_away = prev.away_score if prev else 0
    if play.home_score > prev_home:
        team_id = game.home.id
    elif play.away_score > prev_away:
        team_id = game.away.id

    if play.scoring_type == "touchdown" or "touchdown" in text:
        cats.append("touchdown")
    elif play.scoring_type == "field-goal" or text == "field goal good":
        cats.append("field_goal")
    elif play.scoring_type == "safety" or text == "safety":
        cats.append("safety")
    if "field goal missed" in text or "blocked field goal" in text:
        cats.append("field_goal_missed")

    if play.is_turnover or "interception" in text or "fumble recovery (opponent)" in text:
        cats.append("turnover")
        cats.append("interception" if "interception" in text else "fumble_lost")
        # The event is for the team that gained the ball, unless it then scored (already set).
        if "touchdown" not in cats and "safety" not in cats:
            gained = game.opponent_of(play.offense_team_id)
            team_id = gained.id if gained else team_id

    if play.type_id == "7" or text == "sack":
        cats.append("sack")
    if (
        play.type_id in _SCRIMMAGE_TYPES
        and not play.is_turnover
        and play.stat_yardage >= BIG_PLAY_YARDS
    ):
        cats.append("big_play")
    if (
        play.type_id in _SCRIMMAGE_TYPES
        and not play.scoring
        and play.end_team_id == play.offense_team_id
        and play.yards_to_endzone_before is not None
        and play.yards_to_endzone_after is not None
        and play.yards_to_endzone_before > 20 >= play.yards_to_endzone_after
    ):
        cats.append("red_zone")

    if play.type_id == "75" or "two-minute warning" in text:
        cats.append("two_minute_warning")
    if play.type_id == "2" or text == "end period":
        cats.append("end_period")
    if play.type_id == "65" or text == "end of half":
        cats.append("end_half")
    if play.type_id == "66" or text == "end of game":
        cats.append("end_game")

    opponent = game.opponent_of(team_id)
    return PlayEvent(tuple(cats), team_id, opponent.id if opponent else None)


# --- clock ---------------------------------------------------------------------------------


@dataclass
class ReplayClock:
    """Position on a timeline, advancing with a monotonic time source while playing.

    ``now`` is always passed in (seconds, monotonic), which keeps the clock deterministic
    in tests and independent of the Home Assistant event loop.
    """

    times: list[float]
    speed: float = 1.0
    max_burst: int = 3  # crossing more plays than this in one tick is a jump: no events
    _base_pos: float = 0.0
    _base_now: float = 0.0
    _playing: bool = False
    _last_index: int = -1

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def duration(self) -> float:
        return self.times[-1] if self.times else 0.0

    def position(self, now: float) -> float:
        pos = self._base_pos
        if self._playing:
            pos += (now - self._base_now) * self.speed
        return min(max(pos, -1.0), self.duration)

    def index_at(self, position: float) -> int:
        """Index of the last play at or before ``position``; -1 before the first play."""
        return bisect_right(self.times, position) - 1

    def current_index(self, now: float) -> int:
        return self.index_at(self.position(now))

    def play(self, now: float) -> None:
        if not self._playing:
            self._base_pos, self._base_now, self._playing = self.position(now), now, True

    def pause(self, now: float) -> None:
        if self._playing:
            self._base_pos, self._playing = self.position(now), False

    def set_speed(self, speed: float, now: float) -> None:
        self._base_pos, self._base_now = self.position(now), now
        self.speed = speed

    def seek(self, position: float, now: float) -> None:
        """Jump without emitting the plays in between."""
        self._base_pos, self._base_now = min(max(position, -1.0), self.duration), now
        self._last_index = self.current_index(now)

    def seek_index(self, index: int, now: float) -> None:
        if not self.times:
            return
        index = min(max(index, 0), len(self.times) - 1)
        self.seek(self.times[index], now)

    def step(self, delta: int, now: float) -> None:
        self.seek_index(self.current_index(now) + delta, now)

    def advance(self, now: float) -> list[int]:
        """Indexes of the plays crossed since the last call, in order (empty on a jump)."""
        index = self.current_index(now)
        crossed = list(range(self._last_index + 1, index + 1))
        self._last_index = index
        if len(crossed) > self.max_burst:
            return []
        return crossed


def find_play(game: Game, period: int, clock: str) -> int | None:
    """Index of the first play of ``period`` at or after (game clock counts down) ``clock``."""

    def secs(value: str) -> int:
        mm, _, ss = value.partition(":")
        return _int(mm) * 60 + _int(ss)

    target = secs(clock)
    for i, p in enumerate(game.plays):
        if p.period == period and secs(p.clock) <= target:
            return i
        if p.period > period:
            return i
    return None
