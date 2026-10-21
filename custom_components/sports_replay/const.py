"""Constants for Sports Replay."""

from typing import NamedTuple

DOMAIN = "sports_replay"

CONF_LEAGUE = "league"
CONF_TEAM_ID = "team_id"
CONF_TEAM_ABBR = "team_abbr"


class League(NamedTuple):
    sport: str  # replay.Sport value
    path: str  # ESPN "sport/league" path
    name: str


# League key -> sport and ESPN path. A club playing several competitions (league and Champions
# League) is configured once per competition: ESPN schedules are per competition.
LEAGUES = {
    "nfl": League("football", "football/nfl", "NFL"),
    "college-football": League("football", "football/college-football", "College Football"),
    "nba": League("basketball", "basketball/nba", "NBA"),
    "wnba": League("basketball", "basketball/wnba", "WNBA"),
    "nhl": League("hockey", "hockey/nhl", "NHL"),
    "serie-a": League("soccer", "soccer/ita.1", "Serie A"),
    "premier-league": League("soccer", "soccer/eng.1", "Premier League"),
    "laliga": League("soccer", "soccer/esp.1", "LaLiga"),
    "bundesliga": League("soccer", "soccer/ger.1", "Bundesliga"),
    "ligue-1": League("soccer", "soccer/fra.1", "Ligue 1"),
    "mls": League("soccer", "soccer/usa.1", "MLS"),
    "champions-league": League("soccer", "soccer/uefa.champions", "Champions League"),
    "europa-league": League("soccer", "soccer/uefa.europa", "Europa League"),
}

ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"

EVENT_PLAY = f"{DOMAIN}_play"
SERVICE_SEEK = "seek"

TICK_SECONDS = 1.0
