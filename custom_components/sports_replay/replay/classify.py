"""Event categories of a play, per sport, plus the ones every sport shares.

Who an event is "for" (``PlayEvent.team_id``):
- scores: the team whose score went up (defensive touchdowns and own goals included);
- turnovers, steals, interceptions, turnovers on downs: the team that gained the ball;
- penalties and cards: the penalized team;
- everything else: the team of the play (offense, shooter, ...).
"""

from __future__ import annotations

import re

from .model import Game, Play, PlayEvent, Sport, Team


def classify(game: Game, index: int) -> PlayEvent:
    play = game.plays[index]
    prev = game.plays[index - 1] if index > 0 else None
    team_id = play.team_id
    cats: list[str] = []

    scorer = _scorer(game, play, prev)
    if scorer is not None:
        team_id = scorer.id
        cats.append("score")
        cats += _lead_change(play, prev)

    sport_cats, sport_team = _BY_SPORT[game.sport](game, play)
    cats += sport_cats
    if sport_team is not None and scorer is None:
        team_id = sport_team

    opponent = game.opponent_of(team_id)
    return PlayEvent(tuple(dict.fromkeys(cats)), team_id, opponent.id if opponent else None)


def _scorer(game: Game, play: Play, prev: Play | None) -> Team | None:
    prev_home = prev.home_score if prev else 0
    prev_away = prev.away_score if prev else 0
    if play.home_score > prev_home:
        return game.home
    if play.away_score > prev_away:
        return game.away
    return None


def _lead_change(play: Play, prev: Play | None) -> list[str]:
    before = (prev.home_score - prev.away_score) if prev else 0
    after = play.home_score - play.away_score
    if after == 0:
        return ["tie"]
    if before == 0 or (before > 0) != (after > 0):
        return ["lead_change"]  # also the first score of the game, or a tie broken
    return []


def _gained(game: Game, team_id: str | None) -> str | None:
    other = game.opponent_of(team_id)
    return other.id if other else None


# --- football ------------------------------------------------------------------------------

BIG_PLAY_YARDS = 20
# Non-scoring rushes and receptions: the only plays that count as big plays or red zone entries
# (kick returns, field goals and penalties would otherwise be credited to the wrong team).
_SCRIMMAGE_TYPES = {"5", "24"}  # Rush, Pass Reception
_INCOMPLETE_TYPES = {"3", "7"}  # Pass Incompletion, Sack: can still end a 4th down


def _football(game: Game, play: Play) -> tuple[list[str], str | None]:
    cats: list[str] = []
    team_id = None
    text = play.type_text.lower()

    if play.scoring_type == "touchdown" or "touchdown" in text:
        cats.append("touchdown")
    elif play.scoring_type == "field-goal" or text == "field goal good":
        cats.append("field_goal")
    elif play.scoring_type == "safety" or text == "safety":
        cats.append("safety")
    if "field goal missed" in text or "blocked field goal" in text:
        cats.append("field_goal_missed")

    if play.is_turnover or "interception" in text or "fumble recovery (opponent)" in text:
        cats += ["turnover", "interception" if "interception" in text else "fumble_lost"]
        team_id = _gained(game, play.team_id)

    if play.type_id == "7" or text == "sack":
        cats.append("sack")
    if play.type_id in _SCRIMMAGE_TYPES and not play.is_turnover and play.stat_yardage >= BIG_PLAY_YARDS:
        cats.append("big_play")
    if (
        play.type_id in _SCRIMMAGE_TYPES
        and not play.scoring
        and play.end_team_id == play.team_id
        and play.yards_to_endzone_before is not None
        and play.yards_to_endzone_after is not None
        and play.yards_to_endzone_before > 20 >= play.yards_to_endzone_after
    ):
        cats.append("red_zone")

    if play.type_id in _SCRIMMAGE_TYPES | _INCOMPLETE_TYPES and play.down_before == 4 and not play.scoring:
        if play.end_team_id and play.end_team_id != play.team_id and not play.is_turnover:
            cats.append("turnover_on_downs")
            team_id = _gained(game, play.team_id)
        elif play.type_id in _SCRIMMAGE_TYPES and play.end_team_id == play.team_id and play.down_after == 1:
            cats.append("fourth_down_conversion")

    if play.type_id == "75" or "two-minute warning" in text:
        cats.append("two_minute_warning")
    if play.type_id == "2" or text == "end period":
        cats.append("end_period")
    if play.type_id == "65" or text == "end of half":
        cats.append("end_half")
    if play.type_id == "66" or text == "end of game":
        cats.append("end_game")
    return cats, team_id


# --- basketball ----------------------------------------------------------------------------


def _basketball(game: Game, play: Play) -> tuple[list[str], str | None]:
    cats: list[str] = []
    team_id = None
    kind = play.type_text.lower()
    text = play.text.lower()

    if play.scoring:
        if play.score_value == 3:
            cats.append("three_pointer")
        elif play.score_value == 1:
            cats.append("free_throw")
        else:
            cats.append("two_pointer")
        if "dunk" in kind:
            cats.append("dunk")
    if " blocks " in text:
        cats.append("block")
    if "turnover" in kind:
        cats.append("turnover")
        team_id = _gained(game, play.team_id)
        if " steals)" in text:
            cats.append("steal")
    elif "foul" in kind:
        cats.append("foul")
    if "timeout" in kind:
        cats.append("timeout")
    if kind == "end period":
        cats.append("end_period")
    if kind == "end game":
        cats.append("end_game")
    return cats, team_id


# --- hockey --------------------------------------------------------------------------------


def _hockey(game: Game, play: Play) -> tuple[list[str], str | None]:
    cats: list[str] = []
    kind = play.type_text.lower()

    if play.scoring:
        cats.append("goal")
        if play.strength == "power-play":
            cats.append("power_play_goal")
        elif play.strength == "short-handed":
            cats.append("shorthanded_goal")
        if "empty net" in play.text.lower():
            cats.append("empty_net_goal")
    if play.penalty_minutes is not None:
        cats.append("penalty")
        if "fighting" in kind:
            cats.append("fight")
    if kind == "period start":
        cats.append("period_start")
    if kind == "period end":
        cats.append("end_period")
    if kind == "end of game":
        cats.append("end_game")
    return cats, None


# --- soccer --------------------------------------------------------------------------------

_SECOND_YELLOW = re.compile(r"second yellow", re.IGNORECASE)


def _soccer(game: Game, play: Play) -> tuple[list[str], str | None]:
    cats: list[str] = []
    kind = play.type_text.lower()

    if play.scoring:
        cats.append("goal")
        if "own goal" in kind:
            cats.append("own_goal")
        if "penalty" in kind:
            cats.append("penalty_goal")
        if "header" in kind:
            cats.append("header")
    elif "penalty" in kind and ("missed" in kind or "saved" in kind):
        cats.append("penalty_missed")
    if "yellow card" in kind and not _SECOND_YELLOW.search(play.text):
        cats.append("yellow_card")
    if "red card" in kind or _SECOND_YELLOW.search(play.text):
        cats.append("red_card")
    if kind == "substitution":
        cats.append("substitution")
    if "var" in kind.split():
        cats.append("var")
    if kind in ("kickoff", "start 2nd half", "start extra time"):
        cats.append("period_start")
    if kind == "halftime":
        cats.append("end_period")
    if kind in ("end regular time", "end extra time", "end shootout", "full time") and play is game.plays[-1]:
        cats.append("end_game")
    return cats, None


_BY_SPORT = {
    Sport.FOOTBALL: _football,
    Sport.BASKETBALL: _basketball,
    Sport.HOCKEY: _hockey,
    Sport.SOCCER: _soccer,
}


# --- timeouts (football) -------------------------------------------------------------------

_TIMEOUT_RE = re.compile(r"Timeout #\d+ by (\w+)", re.IGNORECASE)


def timeouts_remaining(game: Game, index: int) -> tuple[int, int] | None:
    """(home, away) timeouts left after play ``index``: 3 per half, 2 in overtime.

    Football only (None otherwise). The caller is read from the play text ("Timeout #1 by WAS").
    """
    if game.sport is not Sport.FOOTBALL:
        return None
    home = away = 3
    half = 1
    for p in game.plays[: index + 1]:
        p_half = 1 if p.period <= 2 else 2 if p.period <= 4 else 3
        if p_half != half:
            half = p_half
            home = away = 3 if half < 3 else 2
        if p.type_id != "21" or not (m := _TIMEOUT_RE.search(p.text)):
            continue
        caller = _text_team(game, m.group(1))
        if caller is game.home:
            home = max(home - 1, 0)
        elif caller is game.away:
            away = max(away - 1, 0)
    return home, away


def _text_team(game: Game, abbr: str) -> Team | None:
    """Team named by an abbreviation in a play description.

    The text can use a different abbreviation than the team's (WAS for WSH): exact match
    first, then the only team sharing the first two letters, then the first letter.
    """
    abbr = abbr.upper()
    teams = (game.home, game.away)
    for prefix in (len(abbr), 2, 1):
        match = [t for t in teams if t.abbreviation.upper()[:prefix] == abbr[:prefix]]
        if len(match) == 1:
            return match[0]
    return None
