"""Offline tests of the engine on real NBA, NHL and Serie A games."""

import json
from pathlib import Path

import pytest

from replay import (
    DEFAULT_MODE,
    Sport,
    TimingMode,
    build_timeline,
    classify,
    find_play,
    parse_summary,
    timeouts_remaining,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name, sport):
    return parse_summary(json.loads((FIXTURES / name).read_text(encoding="utf-8")), sport)


@pytest.fixture(scope="module")
def nba():
    return load("nba_401909088.json", Sport.BASKETBALL)  # BOS @ DET, 2026-10-20


@pytest.fixture(scope="module")
def nhl():
    return load("nhl_401892535.json", Sport.HOCKEY)  # ANA @ NYR, 2026-10-19


@pytest.fixture(scope="module")
def soccer():
    return load("ita1_401874771.json", Sport.SOCCER)  # Udinese - Lecce, 2026-10-18


def categories(game):
    return [classify(game, i) for i in range(len(game.plays))]


def test_every_sport_builds_an_increasing_timeline(nba, nhl, soccer):
    for game in (nba, nhl, soccer):
        for mode in TimingMode:
            t = build_timeline(game, mode)
            assert len(t) == len(game.plays)
            assert all(b > a for a, b in zip(t, t[1:])), (game.sport, mode)


def test_nba(nba):
    assert (nba.home.abbreviation, nba.away.abbreviation) == ("DET", "BOS")
    assert (nba.plays[-1].home_score, nba.plays[-1].away_score) == (121, 113)
    assert nba.has_win_probability
    events = categories(nba)
    points = {"three_pointer": 3, "two_pointer": 2, "free_throw": 1}
    # Every point is accounted for by exactly one scoring category.
    total = sum(points[c] for e in events for c in e.categories if c in points)
    assert total == 121 + 113
    # A turnover is credited to the team that gained the ball.
    for i, e in enumerate(events):
        if "turnover" in e.categories:
            assert e.team_id != nba.plays[i].team_id
    assert sum("end_game" in e.categories for e in events) == 1
    assert timeouts_remaining(nba, 10) is None  # football only


def test_nhl(nhl):
    assert (nhl.plays[-1].home_score, nhl.plays[-1].away_score) == (5, 2)
    assert not nhl.has_win_probability
    events = categories(nhl)
    assert sum("goal" in e.categories for e in events) == 7
    assert sum("power_play_goal" in e.categories for e in events) == 1
    assert sum("penalty" in e.categories for e in events) == 7
    # The hockey clock counts up: 8:00 into the 2nd period finds a 2nd-period play at or after it.
    i = find_play(nhl, 2, "8:00")
    assert nhl.plays[i].period == 2 and nhl.plays[i].clock_seconds >= 480


def test_soccer_score_and_events(soccer):
    assert (soccer.home.abbreviation, soccer.away.abbreviation) == ("UDI", "LEC")
    goals = [(p.clock, p.home_score, p.away_score) for p, e in zip(soccer.plays, categories(soccer)) if "goal" in e.categories]
    assert goals == [("11'", 0, 1), ("33'", 0, 2), ("86'", 0, 3)]
    events = categories(soccer)
    assert sum("header" in e.categories for e in events) == 1
    assert sum("yellow_card" in e.categories for e in events) == 1
    assert sum("substitution" in e.categories for e in events) == 10
    assert events[-1].categories == ("end_game",)


def test_soccer_game_clock_counts_stoppage_time(soccer):
    assert DEFAULT_MODE[Sport.SOCCER] is TimingMode.GAME_CLOCK
    t = build_timeline(soccer, TimingMode.GAME_CLOCK)
    by_clock = {p.clock: x / 60 for p, x in zip(soccer.plays, t)}
    assert by_clock["11'"] == pytest.approx(650 / 60)  # 10:50 into the match
    # Halftime at 45'+2' is after 45:00, not clamped to it.
    assert by_clock["45'+2'"] == pytest.approx(46.5)
    # 2nd half: its own clock from 45:00, after the 1st half and a 40 s break.
    assert by_clock["86'"] == pytest.approx(46.5 + 40 / 60 + (5115 - 2700) / 60)
    # The final whistle at 90'+3' lands ~2.5 minutes after 90:00.
    assert by_clock["90'+3'"] - by_clock["86'"] == pytest.approx((5400 + 150 - 5115) / 60)
