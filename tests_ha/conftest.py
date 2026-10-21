"""Home Assistant-level tests (need pytest-homeassistant-custom-component, Python 3.13+)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.sports_replay.api import ScheduledGame

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"
FIXTURE = FIXTURES / "nfl_401873008.json"

TEAMS = [
    {"id": "25", "abbreviation": "SF", "name": "San Francisco 49ers", "short_name": "49ers"},
    {"id": "28", "abbreviation": "WSH", "name": "Washington Commanders", "short_name": "Commanders"},
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


def _patch(teams, games, summary_file):
    summary = json.loads((FIXTURES / summary_file).read_text(encoding="utf-8"))
    return (
        patch("custom_components.sports_replay.api.EspnClient.teams", return_value=teams),
        patch("custom_components.sports_replay.api.EspnClient.schedule", return_value=games),
        patch("custom_components.sports_replay.api.EspnClient.summary", return_value=summary),
    )


@pytest.fixture
def espn_soccer():
    a, b, c = _patch(
        [{"id": "118", "abbreviation": "UDI", "name": "Udinese", "short_name": "Udinese"}],
        [ScheduledGame("401874771", datetime(2026, 10, 18, 10, 30, tzinfo=UTC), "LEC @ UDI", "", True)],
        "ita1_401874771.json",
    )
    with a, b, c:
        yield


@pytest.fixture
def espn_nba():
    a, b, c = _patch(
        [{"id": "8", "abbreviation": "DET", "name": "Detroit Pistons", "short_name": "Pistons"}],
        [ScheduledGame("401909088", datetime(2026, 10, 20, 23, 0, tzinfo=UTC), "BOS @ DET", "", True)],
        "nba_401909088.json",
    )
    with a, b, c:
        yield
