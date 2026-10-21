"""Running football statistics against ESPN's official box score of the same game.

The official numbers are only a reference for the tests: the integration never reads the box
score (it would spoil the result).
"""

import json
from pathlib import Path

import pytest

from replay import Sport, parse_summary
from replay.stats import team_stats

FIXTURE = Path(__file__).parent / "fixtures" / "nfl_401873008.json"
SF, WSH = "25", "28"


@pytest.fixture(scope="module")
def game():
    return parse_summary(json.loads(FIXTURE.read_text(encoding="utf-8")), Sport.FOOTBALL)


@pytest.fixture(scope="module")
def final(game):
    return team_stats(game, len(game.plays) - 1)


def line(s):
    return {
        "total_yards": s["total_yards"],
        "passing_yards": s["passing_yards"],
        "rushing_yards": s["rushing_yards"],
        "rushing_attempts": s["rushing_attempts"],
        "completions": s["completions"],
        "sacks": (s["sacks_taken"], s["sack_yards_lost"]),
        "third_down": s["third_down"],
        "fourth_down": s["fourth_down"],
        "penalties": (s["penalties"], s["penalty_yards"]),
        "turnovers": s["turnovers"],
        "possession_time": s["possession_time"],
    }


def test_team_stats_match_the_official_box_score(final):
    # Official: SF 375 yds (249 net passing, 126 rushing on 29), 21/29, sacked 2-15, 3rd 7-14,
    # 4th 2-2, penalties 11-88, 1 turnover, possession 29:45, 20 first downs, 60 plays.
    assert line(final[SF]) == {
        "total_yards": 375, "passing_yards": 249, "rushing_yards": 126, "rushing_attempts": 29,
        "completions": 21, "sacks": (2, 15), "third_down": "7/14", "fourth_down": "2/2",
        "penalties": (11, 88), "turnovers": 1, "possession_time": "29:45",
    }
    assert final[SF]["pass_attempts"] == 29
    assert final[SF]["first_downs"] == 20
    assert final[SF]["plays"] == 60
    # Official: WSH 314 yds (261 + 53 on 17), 29/40, 4-39, 3-12, 1-3, 7-66, 0, 30:15, 19, 61.
    assert line(final[WSH]) == {
        "total_yards": 314, "passing_yards": 261, "rushing_yards": 53, "rushing_attempts": 17,
        "completions": 29, "sacks": (4, 39), "third_down": "3/12", "fourth_down": "1/3",
        "penalties": (7, 66), "turnovers": 0, "possession_time": "30:15",
    }
    # Known gaps: two incomplete passes wiped out by a penalty ("No Play") are attempts in the
    # official numbers, and one first down by penalty is missed.
    assert final[WSH]["pass_attempts"] == 38  # official 40
    assert final[WSH]["first_downs"] == 18  # official 19


def test_player_stats(final):
    purdy = final[SF]["passers"][0]
    assert (purdy["name"], purdy["completions"], purdy["attempts"], purdy["yards"]) == ("B.Purdy", 21, 29, 264)
    daniels = final[WSH]["passers"][0]
    assert (daniels["completions"], daniels["yards"]) == (29, 300)
    rushers = {r["name"]: (r["carries"], r["yards"]) for r in final[SF]["rushers"]}
    assert rushers["C.McCaffrey"] == (16, 64)
    receivers = final[SF]["receivers"]
    assert receivers == sorted(receivers, key=lambda r: -r["yards"])  # leaders first
    assert sum(r["receptions"] for r in receivers) == 21


def test_stats_run_with_the_replay(game):
    assert team_stats(game, -1)[SF]["total_yards"] == 0
    half = next(i for i, p in enumerate(game.plays) if p.type_text == "End of Half")
    at_half = team_stats(game, half)
    full = team_stats(game, len(game.plays) - 1)
    assert 0 < at_half[SF]["total_yards"] < full[SF]["total_yards"]
    # Only drives already over count towards possession.
    assert at_half[SF]["possession_seconds"] + at_half[WSH]["possession_seconds"] <= 30 * 60


# --- basketball: BOS @ DET, 2026-10-20 ------------------------------------------------------

DET, BOS = "8", "2"


@pytest.fixture(scope="module")
def nba():
    data = json.loads((FIXTURE.parent / "nba_401909088.json").read_text(encoding="utf-8"))
    return parse_summary(data, Sport.BASKETBALL)


def test_basketball_team_stats_match_the_official_box_score(nba):
    final = team_stats(nba, len(nba.plays) - 1)
    pick = ("points", "field_goals", "three_pointers", "free_throws", "rebounds", "offensive_rebounds",
            "assists", "steals", "blocks", "turnovers", "fouls")
    assert {k: final[BOS][k] for k in pick} == {
        "points": 113, "field_goals": "40/88", "three_pointers": "17/42", "free_throws": "16/21",
        "rebounds": 39, "offensive_rebounds": 12, "assists": 28, "steals": 10, "blocks": 5,
        "turnovers": 14, "fouls": 26,
    }
    assert {k: final[DET][k] for k in pick} == {
        "points": 121, "field_goals": "39/86", "three_pointers": "15/40", "free_throws": "28/32",
        "rebounds": 49, "offensive_rebounds": 14, "assists": 27, "steals": 7, "blocks": 5,
        "turnovers": 17, "fouls": 22,
    }


def test_basketball_player_stats(nba):
    final = team_stats(nba, len(nba.plays) - 1)
    george = next(p for p in final[BOS]["players"] if p["name"] == "P. George")
    # Official line: 38 pts, 12-21 FG, 7-12 3PT, 7-8 FT.
    assert (george["points"], george["fgm"], george["fga"], george["fg3m"], george["fg3a"], george["ftm"], george["fta"]) == (
        38, 12, 21, 7, 12, 7, 8
    )
    assert final[BOS]["players"][0]["name"] == "P. George"  # top scorer first
    assert sum(p["points"] for p in final[DET]["players"]) == 121


def test_basketball_five_on_court_all_game(nba):
    for index in range(-1, len(nba.plays), 7):
        stats = team_stats(nba, index)
        assert len(stats[DET]["on_court"]) == 5 and len(stats[BOS]["on_court"]) == 5, index
    assert team_stats(nba, -1)[BOS]["points"] == 0


# --- hockey: ANA @ NYR, 2026-10-19 ----------------------------------------------------------

ANA, NYR = "25", "13"


def _load(name, sport):
    return parse_summary(json.loads((FIXTURE.parent / name).read_text(encoding="utf-8")), sport)


def test_hockey_stats_match_the_official_box_score():
    game = _load("nhl_401892535.json", Sport.HOCKEY)
    final = team_stats(game, len(game.plays) - 1)
    pick = ("goals", "shots", "hits", "blocked_shots", "faceoffs_won", "takeaways", "giveaways",
            "penalties", "penalty_minutes", "power_play_goals")
    assert [final[ANA][k] for k in pick] == [2, 31, 29, 13, 26, 4, 13, 4, 8, 0]
    assert [final[NYR][k] for k in pick] == [5, 30, 15, 17, 31, 2, 19, 3, 6, 1]
    # Points = goals + assists; the leaders first.
    top = final[NYR]["players"][0]
    assert top["points"] == top["goals"] + top["assists"] > 0
    assert sum(p["goals"] for p in final[NYR]["players"]) == 5


# --- soccer: Udinese - Lecce, 2026-10-18 ----------------------------------------------------

UDI, LEC = "118", "113"


def test_soccer_stats_match_the_official_box_score():
    game = _load("ita1_401874771.json", Sport.SOCCER)
    final = team_stats(game, len(game.plays) - 1)
    pick = ("goals", "shots", "shots_on_target", "corners", "fouls", "offsides", "yellow_cards", "red_cards", "saves")
    assert [final[UDI][k] for k in pick] == [0, 14, 2, 1, 10, 3, 1, 0, 8]
    assert [final[LEC][k] for k in pick] == [3, 17, 11, 4, 11, 8, 0, 0, 2]
    scorers = {p["name"] for p in final[LEC]["players"] if p["goals"]}
    assert scorers == {"K. Gaspar", "J. Siebert"} | {p["name"] for p in final[LEC]["players"] if p["name"].startswith("K. N")}
    # The third goal came from a fast break, without an assist.
    assert {p["name"] for p in final[LEC]["players"] if p["assists"]} == {"A. Gallo", "Tiago Gabriel"}
    assert final[LEC]["players"][0]["goals"] == 1  # scorers first


def test_soccer_eleven_on_the_field_all_game():
    game = _load("ita1_401874771.json", Sport.SOCCER)
    start = team_stats(game, -1)
    end = team_stats(game, len(game.plays) - 1)
    for team in (UDI, LEC):
        assert len(start[team]["on_field"]) == 11 and len(end[team]["on_field"]) == 11
        assert start[team]["on_field"] != end[team]["on_field"]  # substitutions applied
