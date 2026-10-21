"""Running statistics: computed from the plays up to the replay position, never from ESPN's
final box score (that would spoil the result).

Football only for now. Player statistics come from the play text ("B.Purdy pass short left to
G.Kittle for 11 yards"), as ESPN's football play-by-play does not list participants.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re

from .classify import _text_team
from .model import Game, Play, Sport

_NAME = r"([A-Z][A-Za-z'.\-]*\.[A-Za-z'\-]+(?: [JS]r\.| I{2,3})?)"
_YARDS = r"for (-?\d+) yards?|for (no gain)"
_PASS = re.compile(_NAME + r" pass (?!incomplete).*?to " + _NAME + r".*?(?:" + _YARDS + r")")
_INCOMPLETE = re.compile(_NAME + r" pass incomplete")
_INTERCEPTED = re.compile(_NAME + r" pass .*?INTERCEPTED", re.IGNORECASE)
_SACK = re.compile(_NAME + r" sacked .*?(?:" + _YARDS + r")")
_RUSH = re.compile(
    _NAME
    + r" (?:up the middle|scrambles|kneels|left|right|(?:left|right) (?:end|tackle|guard))"
    + r".*?(?:"
    + _YARDS
    + r")"
)
_PENALTY = re.compile(r"PENALTY on (\w+)(?:-[^,]*)?, [^,]+?, (\d+) yards?", re.IGNORECASE)
_NO_PLAY = re.compile(r"No Play", re.IGNORECASE)
_NULLIFIED = re.compile(r"NULLIFIED", re.IGNORECASE)
_ENFORCED_AT = re.compile(r"enforced at (\w+) (\d+)")

# Plays that can carry an offensive action (the action itself is read from the text).
_OFFENSE_TYPES = {"3", "5", "7", "8", "24", "26", "29", "36", "67", "68"}


def _yards(match: re.Match, group: int) -> int:
    value = match.group(group)
    return int(value) if value else 0  # "no gain"


@dataclass
class Passer:
    name: str
    completions: int = 0
    attempts: int = 0
    yards: int = 0
    touchdowns: int = 0
    interceptions: int = 0
    sacks: int = 0


@dataclass
class Rusher:
    name: str
    carries: int = 0
    yards: int = 0
    touchdowns: int = 0


@dataclass
class Receiver:
    name: str
    receptions: int = 0
    yards: int = 0
    touchdowns: int = 0


@dataclass
class FootballTeamStats:
    total_yards: int = 0
    passing_yards: int = 0  # net: sack yards subtracted, as in official stats
    rushing_yards: int = 0
    plays: int = 0
    completions: int = 0
    pass_attempts: int = 0
    rushing_attempts: int = 0
    first_downs: int = 0
    third_down_conversions: int = 0
    third_down_attempts: int = 0
    fourth_down_conversions: int = 0
    fourth_down_attempts: int = 0
    turnovers: int = 0
    sacks_taken: int = 0
    sack_yards_lost: int = 0
    penalties: int = 0
    penalty_yards: int = 0
    possession_seconds: int = 0
    passers: dict[str, Passer] = field(default_factory=dict)
    rushers: dict[str, Rusher] = field(default_factory=dict)
    receivers: dict[str, Receiver] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        for key, sort in (("passers", "yards"), ("rushers", "yards"), ("receivers", "yards")):
            d[key] = sorted(d[key].values(), key=lambda p: -p[sort])
        mm, ss = divmod(self.possession_seconds, 60)
        d["possession_time"] = f"{mm}:{ss:02d}"
        d["third_down"] = f"{self.third_down_conversions}/{self.third_down_attempts}"
        d["fourth_down"] = f"{self.fourth_down_conversions}/{self.fourth_down_attempts}"
        return d


def team_stats(game: Game, index: int) -> dict[str, dict] | None:
    """{team_id: stats} after play ``index`` (-1: before the first play). None if not supported."""
    if game.sport is not Sport.FOOTBALL:
        return None
    stats = {game.home.id: FootballTeamStats(), game.away.id: FootballTeamStats()}
    for play in game.plays[: index + 1]:
        _football_play(game, play, stats)
    _possession(game, index, stats)
    return {team_id: s.as_dict() for team_id, s in stats.items()}


def _football_play(game: Game, play: Play, stats: dict[str, FootballTeamStats]) -> None:
    for m in _PENALTY.finditer(play.text):
        team = _text_team(game, m.group(1))
        if team is not None:
            stats[team.id].penalties += 1
            stats[team.id].penalty_yards += int(m.group(2))

    offense = stats.get(play.team_id or "")
    if offense is None:
        return
    text = play.text
    if play.type_id not in _OFFENSE_TYPES or _NO_PLAY.search(text):
        # No play, but a defensive foul can still hand the offense a first down.
        if _penalty_first_down(game, play):
            offense.first_downs += 1
        return
    touchdown = "TOUCHDOWN" in text and not _NULLIFIED.search(text)
    action = None

    if m := _PASS.search(text):
        action = "pass"
        yards = _yards(m, 3)
        passer = offense.passers.setdefault(m.group(1), Passer(m.group(1)))
        receiver = offense.receivers.setdefault(m.group(2), Receiver(m.group(2)))
        passer.completions += 1
        passer.attempts += 1
        passer.yards += yards
        receiver.receptions += 1
        receiver.yards += yards
        if touchdown:
            passer.touchdowns += 1
            receiver.touchdowns += 1
        offense.completions += 1
        offense.pass_attempts += 1
        offense.passing_yards += yards
    elif m := _INTERCEPTED.search(text):
        action = "pass"
        passer = offense.passers.setdefault(m.group(1), Passer(m.group(1)))
        passer.attempts += 1
        passer.interceptions += 1
        offense.pass_attempts += 1
        offense.turnovers += 1
    elif m := _INCOMPLETE.search(text):
        action = "pass"
        offense.passers.setdefault(m.group(1), Passer(m.group(1))).attempts += 1
        offense.pass_attempts += 1
    elif m := _SACK.search(text):
        action = "sack"
        lost = -_yards(m, 2)
        offense.passers.setdefault(m.group(1), Passer(m.group(1))).sacks += 1
        offense.sacks_taken += 1
        offense.sack_yards_lost += lost
        offense.passing_yards -= lost
    elif m := _RUSH.search(text):
        action = "rush"
        yards = _yards(m, 2)
        if _NULLIFIED.search(text):
            # A spot foul during the run: it counts up to the spot of the foul.
            yards = _yards_to_spot(game, play, yards)
        rusher = offense.rushers.setdefault(m.group(1), Rusher(m.group(1)))
        rusher.carries += 1
        rusher.yards += yards
        if touchdown:
            rusher.touchdowns += 1
        offense.rushing_attempts += 1
        offense.rushing_yards += yards

    if action is None:
        return
    offense.plays += 1
    offense.total_yards = offense.passing_yards + offense.rushing_yards
    if play.type_id == "29" or ("FUMBLES" in text and play.is_turnover):
        offense.turnovers += 1

    kept = play.end_team_id == play.team_id
    first_down = touchdown or (
        kept
        and play.down_after == 1
        and (play.down_before != 1 or (play.distance_after or 0) >= (play.distance_before or 0))
    )
    if first_down and action != "sack":
        offense.first_downs += 1
    elif not first_down and _penalty_first_down(game, play):
        offense.first_downs += 1
    if play.down_before == 3:
        offense.third_down_attempts += 1
        offense.third_down_conversions += first_down
    elif play.down_before == 4:
        offense.fourth_down_attempts += 1
        offense.fourth_down_conversions += first_down


def _penalty_first_down(game: Game, play: Play) -> bool:
    """A first down given by a foul of the defense."""
    against_defense = any(
        (t := _text_team(game, m.group(1))) is not None and t.id != play.team_id
        for m in _PENALTY.finditer(play.text)
    )
    return (
        against_defense
        and play.end_team_id == play.team_id
        and play.down_after == 1
        and (play.down_before != 1 or (play.distance_after or 0) >= (play.distance_before or 0))
    )


def _yards_to_spot(game: Game, play: Play, fallback: int) -> int:
    m = _ENFORCED_AT.search(play.text)
    if not m or play.yards_to_endzone_before is None:
        return fallback
    side = _text_team(game, m.group(1))
    if side is None:
        return fallback
    # The yard line is on the defense's side when it names the defending team.
    to_endzone = int(m.group(2)) if side.id != play.team_id else 100 - int(m.group(2))
    return play.yards_to_endzone_before - to_endzone


def _possession(game: Game, index: int, stats: dict[str, FootballTeamStats]) -> None:
    """Time of possession of the drives finished by play ``index``."""
    if index < 0:
        return
    current_drive = game.plays[index].drive_id
    done_drives = {p.drive_id for p in game.plays[: index + 1]} - {current_drive}
    if index == len(game.plays) - 1:
        done_drives.add(current_drive)
    for drive in game.drives:
        if drive.id in done_drives and drive.team_id in stats and drive.seconds:
            stats[drive.team_id].possession_seconds += int(drive.seconds)
