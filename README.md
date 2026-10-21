# Sports Replay for Home Assistant

Watching the game **on replay**? Sports Replay rebuilds it event by event in Home Assistant while
you watch: score, clock, last play and win probability move with your broadcast, and every play
fires an event, so your lights can flash on a touchdown, a three-pointer or a goal exactly when
you see it, hours after it happened.

**Spoiler-free by design**: the game picker lists only completed games and never shows a score or a
winner. Nothing is revealed before the replay reaches it.

Supported: **NFL, college football, NBA, WNBA, NHL, Serie A, Premier League, LaLiga, Bundesliga,
Ligue 1, MLS, Champions League, Europa League.**

> Status: **early (0.1)**. Each sport is tested on a real game (NFL, NBA, NHL, Serie A); college
> football, WNBA and the other soccer leagues use the same feeds but are untested. Live mode is
> planned.

## How it stays in sync

ESPN's play-by-play gives the real wall-clock time and the game clock of every play. The
integration turns them into a replay timeline in one of four modes:

| Mode | For | How |
|---|---|---|
| **Full game, no commercials** (default, US sports) | full game replays with the ads cut | wall-clock gaps, every break longer than *Break threshold* (90 s) is shortened to *Break replaced with* (40 s) |
| **Follow the game clock** (default, soccer) | soccer, whose clock never stops | the match clock, stoppage time included; only halftime is shortened |
| **Live broadcast recording** | a recording of the live broadcast, ads included | raw wall-clock gaps |
| **Condensed game** | condensed replays | a fixed *seconds per play* (13 s) |

Measured on real games: an NFL broadcast spans 185 min, its compressed timeline 121 min; an NBA game
186 → 112 min; an NHL game 154 → 98 min. No timeline is perfect, so the key control is
**Align here**: when the play shown on the dashboard happens on screen, press it and the drift is
gone. *Previous play* / *Next play* and ±10 s do the rest.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TruantRiccardo&repository=ha-sports-replay&category=integration)

Or by hand:

1. Open the HACS section of Home Assistant.
2. Click the "⋮" button in the top right corner and select "Custom repositories".
3. Paste `https://github.com/TruantRiccardo/ha-sports-replay`, pick the type "Integration" and
   click "Add".
4. Search for "Sports Replay" in HACS, open it and click "Download".
5. Restart Home Assistant.

### Manually

Download this repository (green "Code" button → "Download ZIP", or `git clone`) and copy the
`custom_components/sports_replay` directory to the `custom_components` directory in your config
directory:

`<config directory>/custom_components/sports_replay/...`

Then restart Home Assistant. Updates are manual too: repeat the copy and restart.

## Configuration

Configuration is done in the UI only; there is no YAML configuration.

[![Open your Home Assistant instance and start setting up Sports Replay.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=sports_replay)

1. Go to *Settings → Devices & services*, click "Add integration" and look for "Sports Replay".
2. Pick the league.
3. Pick your team from the list (loaded from ESPN, no team ID to look up).

You get a device named after your team's abbreviation, e.g. `Sports Replay SF`, whose entities
start with `sports_replay_sf_` (`sensor.sports_replay_sf_game`,
`select.sports_replay_sf_game_to_replay`, ...). To follow more teams, add the integration again
once per team. A club playing several competitions (league and Champions League) is added once per
competition: ESPN schedules are per competition.

### First replay

1. In `select.*_game_to_replay` pick the game: only completed games are listed, without scores.
2. In `select.*_timing_mode` check the mode matches what you are watching (see below).
3. Start the video and press *Play* when the opening kickoff / tip-off / face-off / kick-off
   happens on screen.
4. If the dashboard runs ahead or behind, use *Previous play* / *Next play* until it shows the play
   on screen, then press *Align here* the moment it happens.

## Entities

One device per followed team (`Sports Replay SF`):

- `sensor.*_game`: `PRE` / `IN` / `POST`, `NOT_FOUND` before a game is picked (Team Tracker's
  states), with **Team Tracker-compatible attributes**
  (`sport`, `team_id`, `team_score`, `opponent_*`, `quarter`, `clock`, `last_play`,
  `team_win_probability`, `event_name`, `date`, logos, colors; for football also `possession`,
  `down_distance_text`, `team_timeouts`) so cards made for
  [Team Tracker](https://github.com/vasqued2/ha-teamtracker) can show the replay too.
  `team_winner` is only set once the replay reaches the end. Extra: `recent_plays` (last 15),
  `win_probability_history`, `play_index` / `play_count`.
- `sensor.*_win_probability`: your team's win probability, % (NFL, college football, NBA; ESPN has
  none for hockey and soccer).
- The same state as separate sensors, for the device page, dashboards and automations without
  templates:
  - **Replay status**: `not_loaded`, `ready` (loaded, first play not reached yet), `playing`,
    `paused`, `finished`;
  - **Replay progress** (% of the plays), **Replay time** and **Replay duration** (at the current
    play: they change play by play, not every second);
  - **Replay end**: when the replay will end while it plays (a timestamp: cards show "in 47
    minutes" and keep it current on their own);
  - **49ers score** (your team's short name: *Lakers score*, *Milan score*, ...),
    **Opponent score**, **Period** (`Q2`, `P3`, `OT`, `2nd half`, ...), **Game clock**,
    **Last play**;
  - football only: **Down and distance**, **Possession**, **49ers timeouts left**,
    **Opponent timeouts left**.

  - **statistics up to the current play** (football and basketball for now), never ESPN's final
    box score, which would spoil the result:
    - **49ers stats** / **Opponent stats**: football: total yards, with net passing and rushing
      yards, plays, completions and attempts, first downs, third and fourth down efficiency,
      turnovers, sacks, penalties and time of possession (drives already over) as attributes.
      Basketball: field goal %, with field goals, three-pointers, free throws, rebounds
      (offensive, defensive), assists, steals, blocks, turnovers and fouls as attributes;
    - **49ers players** / **Opponent players**: football: the quarterback's line
      (`B.Purdy 21/29, 264 yds`), with every passer, rusher and receiver in the attributes.
      Basketball: the top scorer (`P. George 38 pts, 5 reb, 3 ast`), with every player's line
      (points, shots, rebounds, assists, steals, blocks, turnovers, fouls) in the attributes.
      Leaders first;
    - basketball only, **Pistons on court** / **Opponent on court**: the five on the court
      (starters, then every substitution).

    Checked against the official box score of a full game. Basketball: every team and player
    number matches. Football, whose play-by-play has no player list, so the numbers are read
    from the play text: every number matches, except two incomplete passes wiped out by a
    penalty that official stats still count as attempts, and one first down by penalty.
    Football player names are as ESPN writes them in the play text (`B.Purdy`).

  The team sensors are named after the team you configured, but their entity ids are the same for
  every team: `sensor.sports_replay_<abbreviation>_team_score`,
  `sensor.sports_replay_<abbreviation>_team_timeouts_left`, `..._team_stats`, `..._team_players`, `..._team_on_court`.
- `select.*_game_to_replay` (loads the game), `select.*_timing_mode`.
- Buttons: play, pause, previous/next play, back/forward 10 s, align here, restart, refresh games.
- Numbers: speed (0.25×–4×) and the timing tunables.
- Service `sports_replay.seek`: jump to a game time, e.g. `period: 2`, `clock: "8:34"` (for soccer,
  the TV clock: `period: 2`, `clock: "67:30"`).

### A running replay clock

Home Assistant integrations cannot create `timer` entities, so *Replay status* carries the same
information as attributes: `started_at` and `ends_at` (wall-clock times, set while playing),
`position`, `duration`, `speed`. They only change on play, pause, seek or speed change, so the
recorder is not flooded and a card can animate the progress itself, e.g. with
[timer-bar-card](https://github.com/rianadon/timer-bar-card):

```yaml
type: custom:timer-bar-card
entities:
  - entity: sensor.sports_replay_sf_replay_status
    name: Replay
    active_state: playing
    start_time:
      attribute: started_at
    end_time:
      attribute: ends_at
```

The game, the play reached and the settings are kept across restarts; the replay comes back
paused. The schedule refreshes every 6 hours (or with *Refresh games*).

## Events

Every play the replay crosses fires `sports_replay_play`:

```yaml
categories: [score, lead_change, touchdown]
text: "B.Purdy pass short left to G.Kittle for 11 yards, TOUCHDOWN."
period: 1
clock: "10:53"
# the team the event is for (see below)
team: SF
team_name: 49ers
team_color: "#aa0000"
team_rgb: [170, 0, 0]     # ready for light.turn_on; the alternate color if the main one is too dark
is_my_team: true
# both sides, from your team's point of view
my_team: SF
my_team_name: 49ers
opponent: WSH
opponent_name: Commanders
my_score: 7
opponent_score: 0
config_entry_id: 01J...  # which followed team, when you follow more than one
league: nfl
sport: football
mode: replay
```

| Sport | Categories |
|---|---|
| all | `score`, `lead_change` (includes the first score), `tie` |
| football | `touchdown`, `field_goal`, `field_goal_missed`, `safety`, `turnover`, `interception`, `fumble_lost`, `turnover_on_downs`, `fourth_down_conversion`, `sack`, `big_play` (20+ yd), `red_zone`, `two_minute_warning`, `end_period`, `end_half`, `end_game` |
| basketball | `three_pointer`, `two_pointer`, `free_throw`, `dunk`, `block`, `steal`, `turnover`, `foul`, `timeout`, `end_period`, `end_game` |
| hockey | `goal`, `power_play_goal`, `shorthanded_goal`, `empty_net_goal`, `penalty`, `fight`, `period_start`, `end_period`, `end_game` |
| soccer | `goal`, `own_goal`, `penalty_goal`, `header`, `penalty_missed`, `yellow_card`, `red_card`, `substitution`, `var`, `period_start`, `end_period`, `end_game` |

`team` is the scorer for scores (defensive touchdowns and own goals included), the team that gained
the ball for turnovers, steals and turnovers on downs, the penalized team for penalties and cards,
the team of the play otherwise.

Jumps (seek, previous/next play, ±10 s, align here) fire nothing, so skipping ahead never sets off a
burst of flashes.

## Dashboard: the Team Tracker card

The game sensor speaks Team Tracker's language, so the scoreboard card made for it shows the replay:
[**ha-teamtracker-card**](https://github.com/vasqued2/ha-teamtracker-card) by
[@vasqued2](https://github.com/vasqued2), with layouts for football, basketball, hockey and soccer.

1. Install it from HACS: search for "Team Tracker Card" (it is in the default HACS list), download
   it and reload the browser.
2. Add it to a dashboard pointing at the game sensor:

```yaml
type: custom:teamtracker-card
entity: sensor.sports_replay_sf_game
outline: true
```

The card shows the replay as if it were live (`IN`), the final once the replay reaches the end
(`POST`) and its "not found" panel before a game is loaded. Team Tracker fields that a replay
does not have (TV network, odds, records) stay empty. For the controls, add the buttons and the
selects of the device in an entities card next to it, and the replay clock below.

## Automations: lights and announcements

The **Game event** blueprint flashes lights in the team's colors and makes an announcement on the
events you pick, then gives the lights back the state they had (effects included).

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FTruantRiccardo%2Fha-sports-replay%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsports_replay%2Fgame_event.yaml)

Or by hand: *Settings → Automations & scenes → Blueprints → Import blueprint* and paste
`https://github.com/TruantRiccardo/ha-sports-replay/blob/main/blueprints/automation/sports_replay/game_event.yaml`.

Then *Create automation* from it, once per reaction you want. Some recipes:

| Automation | Events | Whose | Lights | Announcement |
|---|---|---|---|---|
| My team scores | `score` | My team | team color, 5 flashes | `{{ team_name }}! {{ my_team_name }} {{ my_score }}, {{ opponent_name }} {{ opponent_score }}.` |
| The opponent scores | `score` | The opponent | team color, 1 flash | none |
| Ball won | `turnover`, `turnover_on_downs`, `steal` | My team | fixed amber, 3 flashes | `Ball to the {{ team_name }}!` |
| Trouble | `red_card`, `penalty` | My team | fixed red, 2 flashes | `{{ text }}` |
| Final whistle | `end_game` | Both | none | `{% if my_score > opponent_score %}{{ my_team_name }} win {{ my_score }} to {{ opponent_score }}!{% elif my_score < opponent_score %}{{ my_team_name }} lose {{ my_score }} to {{ opponent_score }}.{% else %}It ends in a tie, {{ my_score }} all.{% endif %}` |

The same automation in YAML, if you prefer:

```yaml
alias: 49ers score
use_blueprint:
  path: sports_replay/game_event.yaml
  input:
    team: 01J...          # the Sports Replay entry: pick it in the UI
    categories: [score]
    side: mine
    lights: [light.living_room, light.tv_strip]
    flashes: 5
    satellites: [assist_satellite.kitchen]
```

## Credits

- [Team Tracker](https://github.com/vasqued2/ha-teamtracker) and
  [ha-teamtracker-card](https://github.com/vasqued2/ha-teamtracker-card) by
  [@vasqued2](https://github.com/vasqued2): the attribute names this integration follows and the
  card that displays it.
- [ha-nfl](https://github.com/zacs/ha-nfl) by [@zacs](https://github.com/zacs), where Team Tracker
  started, and the model for this README's installation guide.
- [timer-bar-card](https://github.com/rianadon/timer-bar-card) by
  [@rianadon](https://github.com/rianadon) for the replay clock.
- [My Home Assistant](https://my.home-assistant.io/) for the one-click buttons.
- Data: ESPN.

## Data source and disclaimer

Data comes from ESPN's public but **unofficial** site API (the same one Team Tracker uses): no key,
no account, and it can change without notice. This project is not affiliated with ESPN or any
league or team.

## Development

```bash
pytest tests                # engine only: plain Python, no Home Assistant needed
pip install pytest-homeassistant-custom-component   # Python 3.13+
pytest tests tests_ha       # full suite
```

The replay engine (`custom_components/sports_replay/replay/`) has no Home Assistant imports.

## License

MIT
