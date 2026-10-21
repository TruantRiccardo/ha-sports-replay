"""Offline tests of the replay engine on a real NFL game (WSH @ SF, 2026-10-19)."""

import json
from pathlib import Path

import pytest

from replay import (
    ReplayClock,
    TimingMode,
    TimingParams,
    build_timeline,
    classify,
    find_play,
    parse_summary,
    Sport,
)

FIXTURE = Path(__file__).parent / "fixtures" / "nfl_401873008.json"


@pytest.fixture(scope="module")
def game():
    return parse_summary(json.loads(FIXTURE.read_text(encoding="utf-8")), Sport.FOOTBALL)


def test_parse(game):
    assert game.home.abbreviation == "SF"
    assert game.away.abbreviation == "WSH"
    assert len(game.plays) == 178
    sequences = [p.sequence for p in game.plays]
    assert sequences == sorted(sequences)
    assert all(p.wallclock for p in game.plays)
    assert sum(p.home_win_probability is not None for p in game.plays) > 170


def test_timeline_modes(game):
    broadcast = build_timeline(game, TimingMode.BROADCAST)
    full = build_timeline(game, TimingMode.FULL_NO_ADS)
    condensed = build_timeline(game, TimingMode.CONDENSED, TimingParams(condensed_per_play=13))
    for t in (broadcast, full, condensed):
        assert len(t) == len(game.plays)
        assert t[0] == 0
        assert all(b > a for a, b in zip(t, t[1:])), "timeline must be strictly increasing"
    # Measured on this game: ~185 min live, ~121 min with breaks over 90 s cut to 40 s.
    assert 180 * 60 < broadcast[-1] < 190 * 60
    assert 115 * 60 < full[-1] < 127 * 60
    assert condensed[-1] == 13 * 177


def test_classify_scoring(game):
    events = [classify(game, i) for i in range(len(game.plays))]
    tds = [e for e in events if "touchdown" in e.categories]
    fgs = [e for e in events if "field_goal" in e.categories]
    assert len(tds) == 5
    assert len(fgs) == 2
    # Every touchdown is credited to the team whose score went up.
    for i, e in enumerate(events):
        if "touchdown" in e.categories:
            play, prev = game.plays[i], game.plays[i - 1]
            scorer = game.home.id if play.home_score > prev.home_score else game.away.id
            assert e.team_id == scorer
    assert sum("end_game" in e.categories for e in events) == 1


def test_classify_turnover_credits_recovering_team(game):
    for i, p in enumerate(game.plays):
        if p.type_text == "Fumble Recovery (Opponent)":
            e = classify(game, i)
            assert "fumble_lost" in e.categories
            assert e.team_id != p.team_id
            break
    else:
        pytest.fail("fixture has a fumble recovery")


def test_clock_emits_crossed_plays_in_order():
    clock = ReplayClock(times=[0, 10, 20, 30, 40])
    assert clock.advance(0) == [0]
    clock.play(now=100)
    assert clock.advance(105) == []
    assert clock.advance(110) == [1]
    assert clock.advance(125) == [2]
    clock.pause(125)
    assert clock.advance(500) == []
    assert clock.current_index(500) == 2


def test_clock_jump_emits_nothing():
    clock = ReplayClock(times=[i * 10.0 for i in range(20)], max_burst=3)
    clock.advance(0)
    clock.seek(150, now=0)
    assert clock.advance(0) == []
    assert clock.current_index(0) == 15
    clock.step(-1, now=0)
    assert clock.current_index(0) == 14
    assert clock.advance(0) == []


def test_clock_speed_and_end():
    clock = ReplayClock(times=[0, 10, 20])
    clock.play(now=0)
    clock.set_speed(2.0, now=0)
    assert clock.current_index(5) == 1
    assert clock.position(1000) == 20  # clamped at the last play


def test_find_play(game):
    i = find_play(game, 2, "8:00")
    p = game.plays[i]
    assert p.period == 2
    mm, ss = p.clock.split(":")
    assert int(mm) * 60 + int(ss) <= 480
    assert find_play(game, 9, "1:00") is None


def test_big_play_only_on_scrimmage(game):
    for i, p in enumerate(game.plays):
        e = classify(game, i)
        if "big_play" in e.categories or "red_zone" in e.categories:
            assert p.type_text in ("Rush", "Pass Reception"), p.text
            assert e.team_id == p.team_id


def test_timeouts_follow_the_play_text(game):
    from replay import timeouts_remaining

    by_text = {}
    for i, p in enumerate(game.plays):
        if p.type_id == "21":
            by_text[(p.period, p.clock, p.text.split(" by ")[1].split()[0])] = timeouts_remaining(game, i)
    # SF is home, Washington is "WAS" in the text but "WSH" as abbreviation.
    assert by_text[(1, "5:42", "SF")] == (2, 3)
    assert by_text[(2, "0:49", "WAS")] == (1, 1)
    assert by_text[(4, "1:46", "WAS")] == (3, 0)  # reset at halftime, then all three used
    assert by_text[(4, "0:06", "SF")] == (2, 0)


def test_fourth_down(game):
    conv, failed = [], []
    for i, p in enumerate(game.plays):
        e = classify(game, i)
        if "fourth_down_conversion" in e.categories:
            conv.append(e.team_id == p.team_id)
        if "turnover_on_downs" in e.categories:
            failed.append(e.team_id != p.team_id)  # credited to the defense
    assert len(conv) == 3 and all(conv)
    assert len(failed) == 2 and all(failed)


def test_game_header(game):
    assert game.name == "WSH @ SF"
    assert game.date is not None and game.date.year == 2026
