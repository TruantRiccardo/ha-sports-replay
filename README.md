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

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/TruantRiccardo/ha-sports-replay`,
   type *Integration*.
2. Install **Sports Replay** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Sports Replay*, then pick league and team.
   A club playing several competitions (league and Champions League) is added once per
   competition: ESPN schedules are per competition.

## Entities

One device per followed team (`Sports Replay SF`):

- `sensor.*_game`: `NOT_LOADED` / `PRE` / `IN` / `POST`, with **Team Tracker-compatible attributes**
  (`sport`, `team_id`, `team_score`, `opponent_*`, `quarter`, `clock`, `last_play`,
  `team_win_probability`, `event_name`, `date`, logos, colors; for football also `possession`,
  `down_distance_text`, `team_timeouts`) so cards made for
  [Team Tracker](https://github.com/vasqued2/ha-teamtracker) can show the replay too.
  `team_winner` is only set once the replay reaches the end. Extra: `recent_plays` (last 15),
  `win_probability_history`, `play_index` / `play_count`.
- `sensor.*_win_probability`: your team's win probability, % (NFL, college football, NBA; ESPN has
  none for hockey and soccer).
- `select.*_game_to_replay` (loads the game), `select.*_timing_mode`.
- Buttons: play, pause, previous/next play, back/forward 10 s, align here, restart, refresh games.
- Numbers: speed (0.25×–4×) and the timing tunables.
- Service `sports_replay.seek`: jump to a game time, e.g. `period: 2`, `clock: "8:34"` (for soccer,
  the TV clock: `period: 2`, `clock: "67:30"`).

The game, the play reached and the settings are kept across restarts; the replay comes back
paused. The schedule refreshes every 6 hours (or with *Refresh games*).

## Events

Every play the replay crosses fires `sports_replay_play`:

```yaml
categories: [score, lead_change, touchdown]
team: SF                  # who the event is for, see below
is_my_team: true
team_score: 7
opponent_score: 0
text: "B.Purdy pass short left to G.Kittle for 11 yards, TOUCHDOWN."
period: 1
clock: "10:53"
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

```yaml
automation:
  - alias: My team scores
    triggers:
      - trigger: event
        event_type: sports_replay_play
        event_data:
          is_my_team: true
    conditions:
      - condition: template
        value_template: "{{ 'score' in trigger.event.data.categories }}"
    actions:
      - action: light.turn_on
        target: { entity_id: light.living_room }
        data: { rgb_color: [170, 0, 0], flash: long }
```

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
