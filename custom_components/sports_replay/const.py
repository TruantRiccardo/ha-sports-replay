"""Constants for Sports Replay."""

DOMAIN = "sports_replay"

CONF_LEAGUE = "league"
CONF_TEAM_ID = "team_id"
CONF_TEAM_ABBR = "team_abbr"

# league key -> ESPN "sport/league" path. Only football is implemented for now: the engine
# reads drives, while basketball and hockey feeds expose a flat list of plays.
LEAGUES = {
    "nfl": "football/nfl",
    "college-football": "football/college-football",
}

ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"

EVENT_PLAY = f"{DOMAIN}_play"
SERVICE_SEEK = "seek"

TICK_SECONDS = 1.0
