"""ESPN ``summary`` payload -> Game, one reader per sport.

Football groups its plays in drives; basketball and hockey have a flat ``plays`` list;
soccer has no play-by-play but ``keyEvents`` (goals, cards, substitutions, ...).
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from .model import Drive, Game, Play, Player, Sport, Team


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
        plays = [_football_play(p, d, win_prob) for d, p in _football_raw(data)]
        game.drives = [_drive(d) for d in _football_drives(data)]
    elif sport is Sport.SOCCER:
        game.players = _roster_players(data)
        plays = _soccer_plays(data, game)
    else:
        plays = [_flat_play(p, win_prob) for p in data.get("plays") or []]
        game.players = _box_players(data)
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


def _football_drives(data: dict[str, Any]) -> list[dict[str, Any]]:
    drives = data.get("drives") or {}
    result = list(drives.get("previous", []))
    current = drives.get("current")  # the drive in progress, in live games
    if current and current.get("id") not in {d.get("id") for d in result}:
        result.append(current)
    return result


def _football_raw(data: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(drive, play) pairs, each play once."""
    seen: set[Any] = set()
    pairs = []
    for d in _football_drives(data):
        for p in d.get("plays", []):
            if p.get("id") not in seen:
                seen.add(p.get("id"))
                pairs.append((d, p))
    return pairs


def _drive(d: dict[str, Any]) -> Drive:
    team = d.get("team")
    team_id = team.get("id") if isinstance(team, dict) else team
    return Drive(
        id=str(d.get("id", "")),
        team_id=str(team_id) if team_id is not None else None,
        seconds=_clock_seconds(d.get("timeElapsed")),
    )


def _football_play(p: dict[str, Any], drive: dict[str, Any], win_prob: dict[str, float]) -> Play:
    start, end = p.get("start") or {}, p.get("end") or {}
    return Play(
        **_common(p, win_prob),
        team_id=(start.get("team") or {}).get("id"),
        end_team_id=(end.get("team") or {}).get("id"),
        down_before=start.get("down"),
        down_after=end.get("down"),
        distance_before=start.get("distance"),
        distance_after=end.get("distance"),
        drive_id=str(drive.get("id", "")) or None,
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
        participants=tuple(
            str((x.get("athlete") or {}).get("id")) for x in p.get("participants") or [] if x.get("athlete")
        ),
        participant_roles=tuple(x.get("type") for x in p.get("participants") or [] if x.get("athlete")),
        shooting=bool(p.get("shootingPlay")),
        points_attempted=_int(p.get("pointsAttempted")),
        strength=(p.get("strength") or {}).get("abbreviation"),
        penalty_minutes=_int(minutes) if minutes is not None else None,
    )


def _box_players(data: dict[str, Any]) -> dict[str, Player]:
    """Names, teams and starters from the box score's player list. Its statistics are never
    read: they are the final ones, a spoiler."""
    players = {}
    for team in (data.get("boxscore") or {}).get("players") or []:
        team_id = str((team.get("team") or {}).get("id", ""))
        for group in team.get("statistics") or []:
            for a in group.get("athletes") or []:
                athlete = a.get("athlete") or {}
                if not athlete.get("id"):
                    continue
                pid = str(athlete["id"])
                players[pid] = Player(
                    id=pid,
                    name=athlete.get("displayName", ""),
                    short_name=athlete.get("shortName") or athlete.get("displayName", ""),
                    team_id=team_id,
                    starter=bool(a.get("starter")),
                    jersey=athlete.get("jersey"),
                )
    return players


# --- soccer --------------------------------------------------------------------------------

# "Goal! Udinese 0, Lecce 1." / "Own Goal by X, Udinese.  Udinese 0, Lecce 1."
_SCORE_RE = re.compile(r"(\d+), [^.,]*?(\d+)\.")


def _roster_players(data: dict[str, Any]) -> dict[str, Player]:
    """Line-ups from the rosters: names, teams, starters, shirt numbers. Never their statistics
    nor the subbedIn/subbedOut flags: those are final, a spoiler."""
    players = {}
    for roster in data.get("rosters") or []:
        team_id = str((roster.get("team") or {}).get("id", ""))
        for entry in roster.get("roster") or []:
            athlete = entry.get("athlete") or {}
            if not athlete.get("id"):
                continue
            pid = str(athlete["id"])
            players[pid] = Player(
                id=pid,
                name=athlete.get("displayName", ""),
                short_name=athlete.get("shortName") or athlete.get("displayName", ""),
                team_id=team_id,
                starter=bool(entry.get("starter")),
                jersey=entry.get("jersey"),
            )
    return players


def _soccer_plays(data: dict[str, Any], game: Game) -> list[Play]:
    """The match commentary (shots, corners, fouls, offsides, goals, cards, substitutions), plus
    the key events it lacks (halftime, second half kick-off); key events only when there is no
    commentary.

    Commentary has no team ids: the team comes from the matching key event, else from the first
    player (rosters), else from the team name in the text ("Corner, Lecce."). The score is read
    from the goal text, which also gets own goals right, and counted per team as a fallback.
    Shoot-out kicks never change the score.
    """
    key_events = {str(e.get("id")): e for e in data.get("keyEvents") or [] if e.get("id") is not None}
    by_name = {p.name: p for p in game.players.values()}
    raw: list[tuple[datetime | None, int, dict[str, Any], str | None]] = []
    commentary = [c for c in data.get("commentary") or [] if c.get("play")]
    for c in commentary:
        play = c["play"]
        event = key_events.get(str(play.get("id")), play)
        raw.append((_time(play.get("wallclock")), _int(c.get("sequence")), event, c.get("text")))
    known = {str(c["play"].get("id")) for c in commentary}
    raw += [(_time(e.get("wallclock")), -1, e, None) for k, e in key_events.items() if k not in known]
    # Chronological; ties keep the commentary order.
    raw.sort(key=lambda r: ((r[0].timestamp() if r[0] else 0.0), r[1]))

    home = away = 0
    plays = []
    for i, (_, _, e, outer_text) in enumerate(raw):
        etype = e.get("type") or {}
        athletes = [(x.get("athlete") or {}) for x in e.get("participants") or []]
        participants = tuple(_athlete_id(a, by_name) for a in athletes)
        # The commentary line ("Foul by X (Lecce).") rather than the play's own text, which can be
        # the next line ("Y wins a free kick").
        text = outer_text or e.get("text") or e.get("shortText") or etype.get("text", "")
        team_id = _soccer_team(game, e, participants, text)
        scoring = bool(e.get("scoringPlay")) and not e.get("shootout")
        if scoring:
            if m := _SCORE_RE.search(e.get("text") or text):
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
                text=text,
                period=_int((e.get("period") or {}).get("number")),
                clock=clock.get("displayValue", ""),
                clock_seconds=_clock_seconds(clock),
                wallclock=_time(e.get("wallclock")),
                home_score=home,
                away_score=away,
                team_id=team_id,
                scoring=scoring,
                score_value=1 if scoring else 0,
                participants=participants,
                shootout=bool(e.get("shootout")),
            )
        )
    return plays


def _athlete_id(athlete: dict[str, Any], by_name: dict[str, Player]) -> str:
    if athlete.get("id"):
        return str(athlete["id"])
    player = by_name.get(athlete.get("displayName", ""))
    return player.id if player else ""


def _soccer_team(game: Game, event: dict[str, Any], participants: tuple[str, ...], text: str) -> str | None:
    if team_id := (event.get("team") or {}).get("id"):
        return str(team_id)
    if participants and participants[0] in game.players:
        return game.players[participants[0]].team_id
    for team in (game.home, game.away):
        for name in {team.name, team.short_name}:
            if name and (f"({name})" in text or f", {name}." in text):
                return team.id
    return None
