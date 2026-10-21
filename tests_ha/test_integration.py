"""Config flow, entities, controls and events, with ESPN replaced by the fixture."""

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.sports_replay.api import EspnError
from custom_components.sports_replay.const import DOMAIN, EVENT_PLAY

DEVICE = "sports_replay_sf"


async def _setup(hass: HomeAssistant, league="nfl", team_id="25", abbr="SF") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"league": league, "team_id": team_id, "team_abbr": abbr},
        unique_id=f"{league}_{team_id}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _press(hass, key):
    await hass.services.async_call("button", "press", {"entity_id": f"button.{DEVICE}_{key}"}, blocking=True)


async def test_config_flow(hass: HomeAssistant, espn) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"league": "nfl"})
    assert result["step_id"] == "team"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"team_id": "25"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"league": "nfl", "team_id": "25", "team_abbr": "SF", "team_name": "49ers"}


async def test_game_select_is_spoiler_free(hass: HomeAssistant, espn) -> None:
    await _setup(hass)
    state = hass.states.get(f"select.{DEVICE}_game_to_replay")
    assert state is not None
    options = state.attributes["options"]
    assert options == ["—", "Week 6 · WSH @ SF · 2026-10-20"]  # completed games only, no score
    game = hass.states.get(f"sensor.{DEVICE}_game")
    assert game.state == "NOT_FOUND"  # Team Tracker's "no game"
    assert "api_message" not in game.attributes  # the card would show it as "API Error"


async def test_replay_controls_and_events(hass: HomeAssistant, espn) -> None:
    entry = await _setup(hass)
    events = async_capture_events(hass, EVENT_PLAY)
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": f"select.{DEVICE}_game_to_replay", "option": "Week 6 · WSH @ SF · 2026-10-20"},
        blocking=True,
    )
    game = hass.states.get(f"sensor.{DEVICE}_game")
    assert game.state == "PRE"
    assert game.attributes["team_abbr"] == "SF"
    assert game.attributes["opponent_abbr"] == "WSH"
    assert game.attributes["play_count"] == 178

    # Stepping is a jump: it moves the replay but fires no events.
    for _ in range(3):
        await _press(hass, "next_play")
    game = hass.states.get(f"sensor.{DEVICE}_game")
    assert game.state == "IN"
    assert game.attributes["play_index"] == 3
    assert events == []

    # Seek to just before SF's first touchdown, then play: time is driven by a fake clock.
    manager = entry.runtime_data
    now = [1000.0]
    manager._now = lambda: now[0]
    td = next(i for i, p in enumerate(manager.game.plays) if p.home_score == 7)
    manager.clock.seek_index(td - 1, now[0])
    await _press(hass, "play")
    now[0] += manager.clock.times[td] - manager.clock.times[td - 1] + 0.5
    manager._tick()
    await hass.async_block_till_done()
    assert len(events) == 1
    # The first score of the game: sport category plus the shared ones.
    assert events[0].data["categories"] == ["score", "lead_change", "touchdown"]
    data = events[0].data
    assert data["is_my_team"] is True
    assert (data["team"], data["team_name"], data["my_team_name"], data["opponent_name"]) == (
        "SF", "49ers", "49ers", "Commanders"
    )
    assert (data["my_score"], data["opponent_score"]) == (7, 0)
    assert data["team_rgb"] == [170, 0, 0]  # 49ers red, ready for light.turn_on
    assert data["config_entry_id"] == entry.entry_id
    assert hass.states.get(f"sensor.{DEVICE}_game").attributes["team_score"] == 7

    await _press(hass, "pause")
    assert manager.clock.playing is False


async def test_mode_change_keeps_the_play(hass: HomeAssistant, espn) -> None:
    entry = await _setup(hass)
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": f"select.{DEVICE}_game_to_replay", "option": "Week 6 · WSH @ SF · 2026-10-20"},
        blocking=True,
    )
    await hass.services.async_call(DOMAIN, "seek", {"period": 2, "clock": "8:00"}, blocking=True)
    before = hass.states.get(f"sensor.{DEVICE}_game").attributes["play_index"]
    await hass.services.async_call(
        "select", "select_option", {"entity_id": f"select.{DEVICE}_timing_mode", "option": "condensed"},
        blocking=True,
    )
    after = hass.states.get(f"sensor.{DEVICE}_game")
    assert after.attributes["play_index"] == before
    assert after.attributes["quarter"] == 2
    assert after.attributes["replay_mode"] == "condensed"


async def test_team_tracker_attributes(hass: HomeAssistant, espn) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": f"select.{DEVICE}_game_to_replay", "option": "Week 6 · WSH @ SF · 2026-10-20"},
        blocking=True,
    )
    await hass.services.async_call(DOMAIN, "seek", {"period": 4, "clock": "1:46"}, blocking=True)
    a = hass.states.get(f"sensor.{DEVICE}_game").attributes
    # What ha-teamtracker-card reads to draw a football game.
    assert a["sport"] == "football"
    assert (a["team_id"], a["opponent_id"]) == ("25", "28")
    assert a["possession"] in ("25", "28")
    assert a["team_timeouts"] == 3 and a["opponent_timeouts"] == 0
    assert a["event_name"] == "WSH @ SF"
    assert a["date"].startswith("2026-10-20")
    assert a["team_winner"] is None  # not before the end: no spoiler
    assert a["team_colors"][0].startswith("#")


async def test_not_ready_when_espn_is_down(hass: HomeAssistant, espn) -> None:
    with patch(
        "custom_components.sports_replay.api.EspnClient.schedule", side_effect=EspnError("down")
    ):
        entry = MockConfigEntry(
            domain=DOMAIN, data={"league": "nfl", "team_id": "25", "team_abbr": "SF"}
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_restore_after_restart(hass: HomeAssistant, espn, hass_storage) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"league": "nfl", "team_id": "25", "team_abbr": "SF"}, entry_id="abc"
    )
    hass_storage[f"{DOMAIN}.abc"] = {
        "version": 1,
        "key": f"{DOMAIN}.abc",
        "data": {
            "game_id": "401873008",
            "play_index": 41,
            "mode": "condensed",
            "params": {"condensed_per_play": 20},
            "speed": 1.5,
        },
    }
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    a = hass.states.get(f"sensor.{DEVICE}_game").attributes
    assert a["play_index"] == 42
    assert a["replay_mode"] == "condensed"
    assert a["replay_speed"] == 1.5
    assert entry.runtime_data.params.condensed_per_play == 20
    assert a["replay_playing"] is False  # never resumes on its own


async def test_soccer_replay(hass: HomeAssistant, espn_soccer) -> None:
    await _setup(hass, "serie-a", "118", "UDI")
    device = "sports_replay_udi"
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": f"select.{device}_game_to_replay", "option": "LEC @ UDI · 2026-10-18"},
        blocking=True,
    )
    assert hass.states.get(f"select.{device}_timing_mode").state == "game_clock"
    # TV clock 85:00 in the 2nd half: the next event is Lecce's third goal (85:15).
    await hass.services.async_call(DOMAIN, "seek", {"period": 2, "clock": "85:00"}, blocking=True)
    a = hass.states.get(f"sensor.{device}_game").attributes
    assert a["sport"] == "soccer"
    assert (a["team_score"], a["opponent_score"]) == (0, 3)
    assert a["clock"] == "86'"
    assert a["team_timeouts"] is None and a["possession"] is None
    assert hass.states.get(f"sensor.{device}_win_probability").state == "unknown"


async def test_nba_events(hass: HomeAssistant, espn_nba) -> None:
    entry = await _setup(hass, "nba", "8", "DET")
    device = "sports_replay_det"
    events = async_capture_events(hass, EVENT_PLAY)
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": f"select.{device}_game_to_replay", "option": "BOS @ DET · 2026-10-20"},
        blocking=True,
    )
    manager = entry.runtime_data
    now = [0.0]
    manager._now = lambda: now[0]
    three = next(i for i, p in enumerate(manager.game.plays) if p.scoring and p.score_value == 3)
    manager.clock.seek_index(three - 1, now[0])
    manager.play()
    now[0] += manager.clock.times[three] - manager.clock.times[three - 1] + 0.1
    manager._tick()
    await hass.async_block_till_done()
    assert "three_pointer" in events[-1].data["categories"]
    assert "score" in events[-1].data["categories"]
    a = hass.states.get(f"sensor.{device}_game").attributes
    assert a["sport"] == "basketball"
    assert a["team_win_probability"] is not None


async def test_state_sensors(hass: HomeAssistant, espn) -> None:
    entry = await _setup(hass)
    s = lambda key: hass.states.get(f"sensor.{DEVICE}_{key}").state  # noqa: E731
    assert s("replay_status") == "not_loaded"
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": f"select.{DEVICE}_game_to_replay", "option": "Week 6 · WSH @ SF · 2026-10-20"},
        blocking=True,
    )
    assert s("replay_status") == "ready"
    assert s("replay_progress") == "0"
    await _press(hass, "play")
    assert s("replay_status") == "playing"
    # The replay as a timer: start and end in wall-clock time, for timer-bar-card.
    status = hass.states.get(f"sensor.{DEVICE}_replay_status").attributes
    started, ends = dt_util.parse_datetime(status["started_at"]), dt_util.parse_datetime(status["ends_at"])
    assert (ends - started).total_seconds() == pytest.approx(status["duration"], abs=2)
    assert dt_util.parse_datetime(s("replay_end")) == ends
    await _press(hass, "next_play")
    await _press(hass, "pause")
    assert s("replay_status") == "paused"  # "ready" only until the first play is reached
    assert hass.states.get(f"sensor.{DEVICE}_replay_status").attributes["ends_at"] is None
    assert s("replay_end") == "unknown"

    await hass.services.async_call(DOMAIN, "seek", {"period": 4, "clock": "1:46"}, blocking=True)
    assert s("period") == "Q4"
    assert s("team_score") == "23" and s("opponent_score") == "17"
    # "49ers score" in the UI, generic entity id.
    assert hass.states.get(f"sensor.{DEVICE}_team_score").attributes["friendly_name"] == "Sports Replay SF 49ers score"
    assert s("team_timeouts_left") == "3" and s("opponent_timeouts_left") == "0"
    assert s("possession") in ("SF", "WSH")
    assert s("down_and_distance") != "unknown"
    assert 90 < int(s("replay_progress")) < 100
    assert float(s("replay_time")) < float(s("replay_duration"))

    manager = entry.runtime_data
    manager.clock.seek_index(len(manager.game.plays) - 1, manager._now())
    manager._notify()
    assert s("replay_status") == "finished"


async def test_football_only_sensors(hass: HomeAssistant, espn_soccer) -> None:
    await _setup(hass, "serie-a", "118", "UDI")
    assert hass.states.get("sensor.sports_replay_udi_period") is not None
    assert hass.states.get("sensor.sports_replay_udi_possession") is None
    assert hass.states.get("sensor.sports_replay_udi_down_and_distance") is None


async def test_team_name_added_to_old_entries(hass: HomeAssistant, espn) -> None:
    entry = await _setup(hass)  # created like 0.1.0 did: no team_name
    assert entry.data["team_name"] == "49ers"


async def test_stats_sensors(hass: HomeAssistant, espn) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": f"select.{DEVICE}_game_to_replay", "option": "Week 6 · WSH @ SF · 2026-10-20"},
        blocking=True,
    )
    assert hass.states.get(f"sensor.{DEVICE}_team_stats").state == "0"  # nothing happened yet
    await hass.services.async_call(DOMAIN, "seek", {"period": 4, "clock": "0:00"}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": f"button.{DEVICE}_next_play"}, blocking=True)

    stats = hass.states.get(f"sensor.{DEVICE}_team_stats")
    assert stats.state == "375"  # SF total yards, as in the official box score
    assert stats.attributes["friendly_name"] == "Sports Replay SF 49ers stats"
    assert stats.attributes["possession_time"] == "29:45"
    assert "passers" not in stats.attributes
    assert hass.states.get(f"sensor.{DEVICE}_opponent_stats").state == "314"

    players = hass.states.get(f"sensor.{DEVICE}_team_players")
    assert players.state == "B.Purdy 21/29, 264 yds"
    assert players.attributes["rushers"][0]["name"] == "C.McCaffrey"
    assert hass.states.get(f"sensor.{DEVICE}_opponent_players").state.startswith("J.Daniels 29/")

    # Player lists stay out of the recorder (Home Assistant reads this per class).
    from custom_components.sports_replay.sensor import PlayersSensor

    assert {"passers", "rushers", "receivers"} <= PlayersSensor._Entity__combined_unrecorded_attributes
