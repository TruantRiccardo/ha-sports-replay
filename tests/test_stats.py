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


def test_other_sports_not_supported_yet():
    data = json.loads((FIXTURE.parent / "nba_401909088.json").read_text(encoding="utf-8"))
    assert team_stats(parse_summary(data, Sport.BASKETBALL), 10) is None
