"""The game_event blueprint, run by Home Assistant's own automation engine."""

from datetime import timedelta
from pathlib import Path
import shutil

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.sports_replay.const import EVENT_PLAY

BLUEPRINT = Path(__file__).parents[1] / "blueprints" / "automation" / "sports_replay" / "game_event.yaml"

EVENT = {
    "config_entry_id": "entry1",
    "categories": ["score", "lead_change", "touchdown"],
    "team": "SF",
    "team_name": "49ers",
    "team_rgb": [170, 0, 0],
    "is_my_team": True,
    "my_team_name": "49ers",
    "opponent_name": "Commanders",
    "my_score": 7,
    "opponent_score": 0,
    "text": "Purdy to Kittle, TOUCHDOWN.",
    "period": 1,
    "clock": "10:53",
}


async def _setup(hass: HomeAssistant, **inputs) -> None:
    dest = Path(hass.config.path("blueprints/automation/sports_replay"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, dest / "game_event.yaml")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "touchdown",
                "alias": "Touchdown",
                "use_blueprint": {
                    "path": "sports_replay/game_event.yaml",
                    "input": {"team": "entry1", **inputs},
                },
            }
        },
    )
    await hass.async_block_till_done()


async def _run(hass: HomeAssistant, data: dict) -> None:
    hass.bus.async_fire(EVENT_PLAY, data)
    await hass.async_block_till_done()
    for _ in range(10):  # let the flash delays run out
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
        await hass.async_block_till_done()


async def test_flash_and_announce(hass: HomeAssistant) -> None:
    on = async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    snap = async_mock_service(hass, "scene", "create")
    restore = async_mock_service(hass, "scene", "turn_on")
    announce = async_mock_service(hass, "assist_satellite", "announce")
    await _setup(
        hass,
        lights=["light.tv"],
        flashes=2,
        satellites=["assist_satellite.kitchen"],
    )
    await _run(hass, EVENT)

    assert snap[0].data == {"scene_id": "sports_replay_touchdown", "snapshot_entities": ["light.tv"]}
    assert len(on) == 2 and len(off) == 2
    assert on[0].data["rgb_color"] == [170, 0, 0]  # the scoring team's color
    assert restore[0].data["entity_id"] == ["scene.sports_replay_touchdown"]
    assert announce[0].data["message"] == "49ers! 49ers 7, Commanders 0."


async def test_side_and_categories_filter(hass: HomeAssistant) -> None:
    on = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    async_mock_service(hass, "scene", "create")
    async_mock_service(hass, "scene", "turn_on")
    await _setup(hass, lights=["light.tv"], flashes=1, categories=["touchdown"], side="mine")

    await _run(hass, {**EVENT, "is_my_team": False})  # the opponent scores
    await _run(hass, {**EVENT, "categories": ["sack"]})  # not a wanted category
    await _run(hass, {**EVENT, "config_entry_id": "other"})  # another team's replay
    assert on == []

    await _run(hass, EVENT)
    assert len(on) == 1


async def test_fixed_color_and_no_announcement(hass: HomeAssistant) -> None:
    on = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    async_mock_service(hass, "scene", "create")
    async_mock_service(hass, "scene", "turn_on")
    announce = async_mock_service(hass, "assist_satellite", "announce")
    await _setup(
        hass, lights=["light.tv"], flashes=1, color_source="fixed", color=[255, 160, 0], side="any"
    )
    await _run(hass, {**EVENT, "is_my_team": False})
    assert on[0].data["rgb_color"] == [255, 160, 0]
    assert announce == []
