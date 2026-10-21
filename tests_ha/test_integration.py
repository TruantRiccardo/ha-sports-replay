"""Config flow, entities, controls and events, with ESPN replaced by the fixture."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.sports_replay.const import DOMAIN, EVENT_PLAY

DEVICE = "sports_replay_sf"


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"league": "nfl", "team_id": "25", "team_abbr": "SF"},
        unique_id="nfl_25",
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
    assert result["data"] == {"league": "nfl", "team_id": "25", "team_abbr": "SF"}


async def test_game_select_is_spoiler_free(hass: HomeAssistant, espn) -> None:
    await _setup(hass)
    state = hass.states.get(f"select.{DEVICE}_game_to_replay")
    assert state is not None
    options = state.attributes["options"]
    assert options == ["—", "Week 6 · WSH @ SF · 2026-10-20"]  # completed games only, no score
    assert hass.states.get(f"sensor.{DEVICE}_game").state == "NOT_LOADED"


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
    assert [e.data["categories"] for e in events] == [["touchdown"]]
    assert events[0].data["is_my_team"] is True
    assert events[0].data["team"] == "SF"
    assert events[0].data["team_score"] == 7
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
