"""Home Assistant-level tests (need pytest-homeassistant-custom-component, Python 3.13+)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.sports_replay.api import ScheduledGame

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURE = Path(__file__).parents[1] / "tests" / "fixtures" / "nfl_401873008.json"

TEAMS = [
    {"id": "25", "abbreviation": "SF", "name": "San Francisco 49ers"},
    {"id": "28", "abbreviation": "WSH", "name": "Washington Commanders"},
]
GAMES = [
    ScheduledGame("401873008", datetime(2026, 10, 20, 0, 15, tzinfo=UTC), "WSH @ SF", "Week 6", True),
    ScheduledGame("401873077", datetime(2026, 11, 23, 1, 20, tzinfo=UTC), "MIN VS SF", "Week 11", False),
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def espn():
    summary = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with (
        patch("custom_components.sports_replay.api.EspnClient.teams", return_value=TEAMS),
        patch("custom_components.sports_replay.api.EspnClient.schedule", return_value=GAMES),
        patch("custom_components.sports_replay.api.EspnClient.summary", return_value=summary),
    ):
        yield
