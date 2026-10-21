"""Data model shared by every sport."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Sport(StrEnum):
    FOOTBALL = "football"
    BASKETBALL = "basketball"
    HOCKEY = "hockey"
    SOCCER = "soccer"


# Does the game clock count down (football, basketball) or up (hockey, soccer)?
CLOCK_COUNTS_DOWN = {
    Sport.FOOTBALL: True,
    Sport.BASKETBALL: True,
    Sport.HOCKEY: False,
    Sport.SOCCER: False,
}


@dataclass(frozen=True)
class Team:
    id: str
    abbreviation: str
    name: str  # "San Francisco 49ers"
    home_away: str  # "home" | "away"
    short_name: str = ""  # "49ers", "Lakers", "Milan"
    color: str | None = None  # hex without '#', as ESPN returns it
    alternate_color: str | None = None
    logo: str | None = None


@dataclass(frozen=True)
class Play:
    """One play (football, basketball, hockey) or key event (soccer)."""

    id: str
    sequence: int
    type_id: str
    type_text: str
    text: str
    period: int
    clock: str  # as displayed: "8:34", "13'"
    clock_seconds: float | None  # the same clock in seconds (remaining or elapsed, see Sport)
    wallclock: datetime | None
    home_score: int
    away_score: int
    team_id: str | None  # team of the play: offense (football), shooter, penalized team, ...
    scoring: bool = False
    score_value: int = 0
    home_win_probability: float | None = None  # 0..1, after the play
    # football
    end_team_id: str | None = None  # team in possession after the play
    down_before: int | None = None
    down_after: int | None = None
    distance_before: int | None = None
    distance_after: int | None = None
    drive_id: str | None = None
    down_distance_before: str | None = None
    down_distance_after: str | None = None
    yards_to_endzone_before: int | None = None
    yards_to_endzone_after: int | None = None
    stat_yardage: int = 0
    scoring_type: str | None = None  # "touchdown", "field-goal", "safety", ...
    is_turnover: bool = False
    # basketball (and hockey, soccer later): athletes involved, ESPN's order
    # (shooter then assister/blocker, player losing the ball then stealer, entering then leaving)
    participants: tuple[str, ...] = ()
    shooting: bool = False
    points_attempted: int = 0
    # hockey
    strength: str | None = None  # "even-strength", "power-play", "short-handed"
    penalty_minutes: int | None = None
    # soccer
    shootout: bool = False


@dataclass(frozen=True)
class Player:
    """A player of the game's rosters: names and starters only, never statistics."""

    id: str
    name: str  # "Jayson Tatum"
    short_name: str  # "J. Tatum"
    team_id: str
    starter: bool = False
    jersey: str | None = None


@dataclass(frozen=True)
class Drive:
    """Football drive: who had the ball and for how long (game clock)."""

    id: str
    team_id: str | None
    seconds: float | None


@dataclass
class Game:
    event_id: str
    sport: Sport
    home: Team
    away: Team
    date: datetime | None = None
    plays: list[Play] = field(default_factory=list)
    drives: list[Drive] = field(default_factory=list)  # football only
    players: dict[str, Player] = field(default_factory=dict)  # basketball: id -> player

    @property
    def name(self) -> str:
        return f"{self.away.abbreviation} @ {self.home.abbreviation}"

    @property
    def has_win_probability(self) -> bool:
        return any(p.home_win_probability is not None for p in self.plays)

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


@dataclass(frozen=True)
class PlayEvent:
    """What a play means, from the point of view of the automations."""

    categories: tuple[str, ...]
    team_id: str | None  # the team the event is "for" (see classify)
    opponent_id: str | None
