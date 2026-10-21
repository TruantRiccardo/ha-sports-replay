"""Running statistics: computed from the plays up to the replay position, never from ESPN's
final box score (that would spoil the result).

Football: player statistics come from the play text ("B.Purdy pass short left to G.Kittle for
11 yards"), as ESPN's football play-by-play does not list participants.
Basketball: from the participants of each play, plus who is on the court (starters, then
substitutions).
Hockey: from the participants and their roles (scorer, assister, shooter, hitter, ...).
Soccer: from the match commentary (shots, corners, fouls, offsides, cards) and the line-ups
(starters, then substitutions).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re

from .classify import _text_team, is_soccer_foul
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
    if game.sport is Sport.BASKETBALL:
        return _basketball(game, index)
    if game.sport is Sport.HOCKEY:
        return _hockey(game, index)
    if game.sport is Sport.SOCCER:
        return _soccer(game, index)
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


# --- basketball ----------------------------------------------------------------------------

_BASKETBALL_COUNTERS = (
    "points", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
    "rebounds", "offensive_rebounds", "defensive_rebounds",
    "assists", "steals", "blocks", "turnovers", "fouls",
)


def _basketball(game: Game, index: int) -> dict[str, dict]:
    teams = {t.id: dict.fromkeys(_BASKETBALL_COUNTERS, 0) for t in (game.home, game.away)}
    players: dict[str, dict] = {}
    on_court = {t: [p.id for p in game.players.values() if p.team_id == t and p.starter] for t in teams}

    def player(pid: str) -> dict | None:
        info = game.players.get(pid)
        if info is None or info.team_id not in teams:
            return None
        if pid not in players:
            players[pid] = {"name": info.short_name, "jersey": info.jersey, **dict.fromkeys(_BASKETBALL_COUNTERS, 0)}
        return players[pid]

    def add(pid: str | None, team_id: str | None, **counts: int) -> None:
        target = player(pid) if pid else None
        team = teams.get(target and game.players[pid].team_id or team_id or "")
        for key, n in counts.items():
            if target is not None:
                target[key] += n
            if team is not None:
                team[key] += n

    for play in game.plays[: index + 1]:
        kind = play.type_text.lower()
        who = play.participants
        first = who[0] if who else None
        if kind == "substitution" and len(who) >= 2:
            entering, leaving = who[0], who[1]
            info = game.players.get(entering)
            if info and info.team_id in on_court:
                lineup = on_court[info.team_id]
                if leaving in lineup:
                    lineup[lineup.index(leaving)] = entering
                elif entering not in lineup:
                    lineup.append(entering)
            continue
        if play.shooting:
            free_throw = "free throw" in kind
            made = play.scoring
            if free_throw:
                add(first, play.team_id, fta=1, ftm=int(made), points=play.score_value if made else 0)
            else:
                three = play.points_attempted == 3
                add(first, play.team_id, fga=1, fgm=int(made), fg3a=int(three), fg3m=int(three and made),
                    points=play.score_value if made else 0)
                if len(who) >= 2:
                    if made:
                        add(who[1], None, assists=1)
                    else:
                        add(who[1], None, blocks=1)
        elif "rebound" in kind:
            # Team rebounds (no player) are not in the official totals.
            if first is not None:
                side = "offensive_rebounds" if "offensive" in kind else "defensive_rebounds"
                add(first, play.team_id, rebounds=1, **{side: 1})
        elif "turnover" in kind or "turnover" in play.text.lower():  # "Traveling": only in the text
            add(first, play.team_id, turnovers=1)
            if len(who) >= 2:
                add(who[1], None, steals=1)
        elif "foul" in kind and "technical" not in kind:
            add(first, play.team_id, fouls=1)

    result = {}
    for team_id, totals in teams.items():
        roster = [p for pid, p in players.items() if game.players[pid].team_id == team_id]
        result[team_id] = {
            **totals,
            "field_goals": f"{totals['fgm']}/{totals['fga']}",
            "three_pointers": f"{totals['fg3m']}/{totals['fg3a']}",
            "free_throws": f"{totals['ftm']}/{totals['fta']}",
            "players": sorted(roster, key=lambda p: (-p["points"], p["name"])),
            "on_court": [game.players[pid].short_name for pid in on_court[team_id]],
        }
    return result


# --- shared by the player-based sports -----------------------------------------------------


class _Book:
    """Counters per team and per player, players registered from the game's rosters."""

    def __init__(self, game: Game, counters: tuple[str, ...]) -> None:
        self.game = game
        self.counters = counters
        self.teams = {t.id: dict.fromkeys(counters, 0) for t in (game.home, game.away)}
        self.players: dict[str, dict] = {}

    def player(self, pid: str | None) -> dict | None:
        info = self.game.players.get(pid or "")
        if info is None or info.team_id not in self.teams:
            return None
        if info.id not in self.players:
            self.players[info.id] = {"name": info.short_name, "jersey": info.jersey, **dict.fromkeys(self.counters, 0)}
        return self.players[info.id]

    def add(self, pid: str | None, team_id: str | None = None, **counts: int) -> None:
        """Count for the player (and their team), or for ``team_id`` when there is no player."""
        target = self.player(pid)
        team = self.teams.get(self.game.players[pid].team_id if target is not None else team_id or "")
        for key, n in counts.items():
            if target is not None:
                target[key] += n
            if team is not None:
                team[key] += n

    def roster(self, team_id: str, sort: str) -> list[dict]:
        mine = [p for pid, p in self.players.items() if self.game.players[pid].team_id == team_id]
        return sorted(mine, key=lambda p: (-p[sort], p["name"]))


def _line_up(game: Game, index: int) -> dict[str, list[str]]:
    """Players on the field/court: starters, then substitutions (entering, leaving)."""
    lineup = {t.id: [p.id for p in game.players.values() if p.team_id == t.id and p.starter] for t in (game.home, game.away)}
    for play in game.plays[: index + 1]:
        if play.type_text.lower() != "substitution" or len(play.participants) < 2:
            continue
        entering, leaving = play.participants[0], play.participants[1]
        info = game.players.get(entering)
        if info is None or info.team_id not in lineup:
            continue
        team = lineup[info.team_id]
        if leaving in team:
            team[team.index(leaving)] = entering
        elif entering not in team:
            team.append(entering)
    return {t: [game.players[pid].short_name for pid in ids] for t, ids in lineup.items()}


def _same_team(game: Game, a: str | None, b: str | None) -> bool:
    pa, pb = game.players.get(a or ""), game.players.get(b or "")
    return pa is not None and pb is not None and pa.team_id == pb.team_id


# --- hockey --------------------------------------------------------------------------------

_HOCKEY_COUNTERS = (
    "goals", "assists", "points", "shots", "hits", "blocked_shots", "faceoffs_won",
    "takeaways", "giveaways", "penalties", "penalty_minutes", "saves", "power_play_goals",
)


def _hockey(game: Game, index: int) -> dict[str, dict]:
    book = _Book(game, _HOCKEY_COUNTERS)
    faceoffs = 0
    for play in game.plays[: index + 1]:
        roles = dict(zip(play.participant_roles, play.participants))
        kind = play.type_text.lower()
        if play.scoring:
            book.add(roles.get("scorer"), play.team_id, goals=1, points=1, shots=1,
                     power_play_goals=int(play.strength == "power-play"))
            for role, pid in zip(play.participant_roles, play.participants):
                if role == "assister":
                    book.add(pid, None, assists=1, points=1)
        elif kind == "shot":
            book.add(roles.get("shooter"), play.team_id, shots=1)
            book.add(roles.get("saver"), None, saves=1)
        elif kind == "hit":
            book.add(roles.get("hit-credited"), play.team_id, hits=1)
        elif kind == "blocked":
            defender, shooter = roles.get("defender"), roles.get("shooter")
            # A shot blocked by a teammate is not a blocked shot for anyone.
            if not _same_team(game, defender, shooter):
                book.add(defender, None, blocked_shots=1)
        elif kind == "face off":
            faceoffs += 1
            book.add(roles.get("face-off-winner"), play.team_id, faceoffs_won=1)
        elif kind == "takeaway":
            book.add(roles.get("taker"), play.team_id, takeaways=1)
        elif kind == "giveaway":
            book.add(roles.get("giver"), play.team_id, giveaways=1)
        if play.penalty_minutes is not None:
            book.add(play.participants[0] if play.participants else None, play.team_id,
                     penalties=1, penalty_minutes=play.penalty_minutes)

    result = {}
    for team_id, totals in book.teams.items():
        result[team_id] = {
            **totals,
            "faceoff_pct": round(100 * totals["faceoffs_won"] / faceoffs) if faceoffs else None,
            "players": book.roster(team_id, "points"),
        }
    return result


# --- soccer --------------------------------------------------------------------------------

_SOCCER_COUNTERS = (
    "goals", "assists", "shots", "shots_on_target", "corners", "fouls", "offsides",
    "yellow_cards", "red_cards", "saves",
)
_SOCCER_ON_TARGET = {"shot on target"}
_SOCCER_SHOT_TYPES = {"shot on target", "shot off target", "shot blocked", "shot hit woodwork"}


def _soccer(game: Game, index: int) -> dict[str, dict]:
    book = _Book(game, _SOCCER_COUNTERS)
    for play in game.plays[: index + 1]:
        kind = play.type_text.lower()
        first = play.participants[0] if play.participants else None
        if play.scoring:
            own_goal = "own goal" in kind
            # An own goal is not a shot nor a goal of the player.
            if not own_goal:
                book.add(first, play.team_id, goals=1, shots=1, shots_on_target=1)
                if len(play.participants) >= 2:
                    book.add(play.participants[1], None, assists=1)
            elif (scorer := game.opponent_of(play.team_id)) is not None:
                book.teams[scorer.id]["goals"] += 1
        elif kind in _SOCCER_SHOT_TYPES:
            on_target = kind in _SOCCER_ON_TARGET
            book.add(first, play.team_id, shots=1, shots_on_target=int(on_target))
            if on_target and (keeper_team := game.opponent_of(play.team_id)) is not None:
                book.teams[keeper_team.id]["saves"] += 1
        elif kind == "corner awarded":
            book.add(None, play.team_id, corners=1)
        elif kind == "offside":
            book.add(None, play.team_id, offsides=1)
        elif is_soccer_foul(play):
            book.add(first, play.team_id, fouls=1)
        if "yellow card" in kind and "second yellow" not in play.text.lower():
            book.add(first, play.team_id, yellow_cards=1)
        if "red card" in kind or "second yellow" in play.text.lower():
            book.add(first, play.team_id, red_cards=1)

    lineup = _line_up(game, index)
    result = {}
    for team_id, totals in book.teams.items():
        result[team_id] = {
            **totals,
            "players": book.roster(team_id, "goals"),
            "on_field": lineup[team_id],
        }
    return result
