# Sports Replay for Home Assistant

Watching the game **on replay**? Sports Replay rebuilds it play by play in Home Assistant while you
watch: score, quarter, down & distance, last play and win probability move with your broadcast. It
fires an event on every play, so your lights can flash on a touchdown, an hour after it happened,
exactly when you see it.

**Spoiler-free by design**: the game picker lists only completed games and never shows a score or a
winner. Nothing is revealed before the replay reaches it.

> Status: **early (0.1)**. NFL is implemented and tested on a real game; college football uses the
> same feed and should work but is untested. Live mode, NBA and NHL are planned.

## How it stays in sync

ESPN's play-by-play gives the real wall-clock time of every play. The integration turns it into a
replay timeline in one of three modes:

| Mode | For | How |
|---|---|---|
| **Full game, no commercials** (default) | full game replays with ads cut | wall-clock gaps, every break longer than *Break threshold* (90 s) is shortened to *Break replaced with* (40 s) |
| **Live broadcast recording** | a recording of the live broadcast, ads included | raw wall-clock gaps |
| **Condensed game** | condensed replays (~40 min) | a fixed *seconds per play* (13 s) |

On a real game (WSH @ SF, Oct 2026) the live broadcast spans 185 min and the compressed timeline
121 min, close to a full replay without commercials. No timeline is perfect, so the key control is
**Align here**: when the play shown on the dashboard happens on screen, press it and the drift is
gone. *Previous play* / *Next play* and ±10 s do the rest.

## Installation

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/TruantRiccardo/ha-sports-replay`,
   type *Integration*.
2. Install **Sports Replay** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Sports Replay*, then pick league and team.

## Entities

One device per followed team (`Sports Replay SF`):

- `sensor.*_game`: `NOT_LOADED` / `PRE` / `IN` / `POST`, with **Team Tracker-compatible attributes**
  (`team_score`, `opponent_score`, `quarter`, `clock`, `possession`, `last_play`,
  `down_distance_text`, `team_win_probability`, logos, colors, ...) so cards made for
  [Team Tracker](https://github.com/vasqued2/ha-teamtracker) work on the replay too. Extra:
  `recent_plays` (last 15), `win_probability_history`, `play_index` / `play_count`.
- `sensor.*_win_probability`: your team's win probability, %.
- `select.*_game_to_replay` (loads the game), `select.*_timing_mode`.
- Buttons: play, pause, previous/next play, back/forward 10 s, align here, restart, refresh games.
- Numbers: speed (0.25×–4×) and the timing tunables.
- Service `sports_replay.seek`: jump to a game time, e.g. `period: 2`, `clock: "8:34"`.

## Events

Every play the replay crosses fires `sports_replay_play`:

```yaml
categories: [touchdown]   # touchdown, field_goal, field_goal_missed, safety, turnover,
                          # interception, fumble_lost, sack, big_play, red_zone,
                          # two_minute_warning, end_period, end_half, end_game
team: SF                  # who the event is for: scorer, team that gained the ball, offense
is_my_team: true
team_score: 7
opponent_score: 0
text: "B.Purdy pass short left to G.Kittle for 11 yards, TOUCHDOWN."
period: 1
clock: "10:53"
mode: replay
```

Jumps (seek, previous/next play, ±10 s, align here) fire nothing, so skipping ahead never sets off a
burst of flashes.

```yaml
automation:
  - alias: Touchdown 49ers
    triggers:
      - trigger: event
        event_type: sports_replay_play
        event_data:
          is_my_team: true
    conditions:
      - condition: template
        value_template: "{{ 'touchdown' in trigger.event.data.categories }}"
    actions:
      - action: light.turn_on
        target: { entity_id: light.living_room }
        data: { rgb_color: [170, 0, 0], flash: long }
```

## Data source and disclaimer

Data comes from ESPN's public but **unofficial** site API (the same one Team Tracker uses): no key,
no account, and it can change without notice. This project is not affiliated with ESPN, the NFL or
any team.

## Development

```bash
pytest tests                # engine only: plain Python, no Home Assistant needed
pip install pytest-homeassistant-custom-component   # Python 3.13+
pytest tests tests_ha       # full suite
```

The replay engine (`custom_components/sports_replay/engine.py`) has no Home Assistant imports.

## License

MIT
