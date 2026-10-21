"""ESPN ``summary`` payload -> Game, one reader per sport.

Football groups its plays in drives; basketball and hockey have a flat ``plays`` list;
soccer has no play-by-play but ``keyEvents`` (goals, cards, substitutions, ...).
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from .model import Game, Play, Sport, Team


def parse_summary(data: dict[str, Any], sport: Sport = Sport.FOOTBALL) -> Game:
    competition = data["header"]["competitions"][0]
    teams = {c.get("homeAway"): _team(c) for c in competition["competitors"]}
    game = Game(
        event_id=str(data["header"].get("id", "")),
        sport=sport,
        home=teams["home"],
        away=teams["away"],
        date=_time(competition.get("date")),
    )
    win_prob = {
        str(w.get("playId")): w.get("homeWinPercentage")
        for w in data.get("winprobability") or []
        if w.get("playId") is not None
    }
    if sport is Sport.FOOTBALL:
        plays = [_football_play(p, win_prob) for p in _football_raw(data)]
    elif sport is Sport.SOCCER:
        plays = _soccer_plays(data, game)
    else:
        plays = [_flat_play(p, win_prob) for p in data.get("plays") or []]
    plays.sort(key=lambda pl: pl.sequence)
    game.plays = plays
    return game


# --- helpers -------------------------------------------------------------------------------


def _time(value: str | None) -> datetime | None:
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


_ADDED_TIME_RE = re.compile(r"\+(\d+)'")


def _clock_seconds(clock: dict[str, Any] | None) -> float | None:
    """ESPN gives a numeric ``value`` (soccer) or only "mm:ss" (the other sports).

    In soccer stoppage time the value stays at the end of the half (2700 for "45'+2'"): the
    added minutes are read from the display, or an event at 90'+4' would fire four minutes
    before it is seen. "+N'" means during minute N of stoppage: its middle is used.
    """
    if not clock:
        return None
    if isinstance(clock.get("value"), (int, float)):
        added = _ADDED_TIME_RE.search(str(clock.get("displayValue", "")))
        return float(clock["value"]) + ((int(added.group(1)) - 0.5) * 60 if added else 0.0)
    mm, sep, ss = str(clock.get("displayValue", "")).partition(":")
    if not sep:
        return None
    try:
        return int(mm) * 60 + float(ss)
    except ValueError:
        return None


def short_name(team: dict[str, Any]) -> str:
    """ "49ers", "Lakers", "Milan": soccer has shortDisplayName ("AC Milan" -> "Milan"), the US
    leagues only ``name`` in game payloads."""
    return team.get("shortDisplayName") or team.get("name") or team.get("abbreviation", "")


def _team(comp: dict[str, Any]) -> Team:
    team = comp.get("team", {})
    logos = team.get("logos") or []
    return Team(
        id=str(team.get("id", "")),
        abbreviation=team.get("abbreviation", ""),
        name=team.get("displayName") or team.get("name", ""),
        home_away=comp.get("homeAway", ""),
        short_name=short_name(team),
        color=team.get("color"),
        alternate_color=team.get("alternateColor"),
        logo=team.get("logo") or (logos[0].get("href") if logos else None),
    )


def _common(p: dict[str, Any], win_prob: dict[str, float]) -> dict[str, Any]:
    clock = p.get("clock") or {}
    return {
        "id": str(p.get("id", "")),
        "sequence": _int(p.get("sequenceNumber")),
        "type_id": str((p.get("type") or {}).get("id", "")),
        "type_text": (p.get("type") or {}).get("text", ""),
        "text": p.get("text", ""),
        "period": _int((p.get("period") or {}).get("number")),
        "clock": clock.get("displayValue", ""),
        "clock_seconds": _clock_seconds(clock),
        "wallclock": _time(p.get("wallclock")),
        "home_score": _int(p.get("homeScore")),
        "away_score": _int(p.get("awayScore")),
        "scoring": bool(p.get("scoringPlay")),
        "score_value": _int(p.get("scoreValue")),
        "home_win_probability": win_prob.get(str(p.get("id"))),
    }


# --- football ------------------------------------------------------------------------------


def _football_raw(data: dict[str, Any]) -> list[dict[str, Any]]:
    drives = data.get("drives") or {}
    raw = [p for d in drives.get("previous", []) for p in d.get("plays", [])]
    if current := drives.get("current"):  # the drive in progress, in live games
        known = {p.get("id") for p in raw}
        raw += [p for p in current.get("plays", []) if p.get("id") not in known]
    return raw


def _football_play(p: dict[str, Any], win_prob: dict[str, float]) -> Play:
    start, end = p.get("start") or {}, p.get("end") or {}
    return Play(
        **_common(p, win_prob),
        team_id=(start.get("team") or {}).get("id"),
        end_team_id=(end.get("team") or {}).get("id"),
        down_before=start.get("down"),
        down_after=end.get("down"),
        down_distance_before=start.get("downDistanceText"),
        down_distance_after=end.get("downDistanceText"),
        yards_to_endzone_before=start.get("yardsToEndzone"),
        yards_to_endzone_after=end.get("yardsToEndzone"),
        stat_yardage=_int(p.get("statYardage")),
        scoring_type=(p.get("scoringType") or {}).get("name"),
        is_turnover=bool(p.get("isTurnover")),
    )


# --- basketball, hockey --------------------------------------------------------------------


def _flat_play(p: dict[str, Any], win_prob: dict[str, float]) -> Play:
    ptype = p.get("type") or {}
    minutes = ptype.get("penaltyMinutes")
    return Play(
        **_common(p, win_prob),
        team_id=(p.get("team") or {}).get("id"),
        strength=(p.get("strength") or {}).get("abbreviation"),
        penalty_minutes=_int(minutes) if minutes is not None else None,
    )


# --- soccer --------------------------------------------------------------------------------

# "Goal! Udinese 0, Lecce 1." / "Own Goal by X, Udinese.  Udinese 0, Lecce 1."
_SCORE_RE = re.compile(r"(\d+), [^.,]*?(\d+)\.")


def _soccer_plays(data: dict[str, Any], game: Game) -> list[Play]:
    """Key events with a running score.

    Key events carry no score: it is read from the goal text, which also gets own goals
    right, and counted per team as a fallback. Shoot-out kicks never change the score.
    """
    home = away = 0
    plays = []
    for i, e in enumerate(data.get("keyEvents") or []):
        etype = e.get("type") or {}
        team_id = str((e.get("team") or {}).get("id", "")) or None
        scoring = bool(e.get("scoringPlay")) and not e.get("shootout")
        if scoring:
            if m := _SCORE_RE.search(e.get("text", "")):
                home, away = int(m.group(1)), int(m.group(2))
            elif team_id == game.home.id:
                home += 1
            elif team_id == game.away.id:
                away += 1
        clock = e.get("clock") or {}
        plays.append(
            Play(
                id=str(e.get("id", i)),
                sequence=i,
                type_id=str(etype.get("id", "")),
                type_text=etype.get("text", ""),
                text=e.get("text") or e.get("shortText") or etype.get("text", ""),
                period=_int((e.get("period") or {}).get("number")),
                clock=clock.get("displayValue", ""),
                clock_seconds=_clock_seconds(clock),
                wallclock=_time(e.get("wallclock")),
                home_score=home,
                away_score=away,
                team_id=team_id,
                scoring=scoring,
                score_value=1 if scoring else 0,
                shootout=bool(e.get("shootout")),
            )
        )
    return plays
