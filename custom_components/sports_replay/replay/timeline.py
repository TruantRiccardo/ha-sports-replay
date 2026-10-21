"""Replay timeline (when each play happens) and the clock that runs over it."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from enum import StrEnum
from statistics import median

from .model import CLOCK_COUNTS_DOWN, Game, Play, Sport


class TimingMode(StrEnum):
    """How replay time is derived from the plays."""

    # Full game replay with the commercial breaks cut: wall-clock gaps, long gaps compressed.
    FULL_NO_ADS = "full_no_ads"
    # Recording of the live broadcast, commercials included: raw wall-clock gaps.
    BROADCAST = "broadcast"
    # Condensed game: a fixed duration per play.
    CONDENSED = "condensed"
    # Follow the game clock, with only the breaks between periods shortened. Right for soccer,
    # whose clock never stops and whose key events are too sparse for wall-clock compression.
    GAME_CLOCK = "game_clock"


DEFAULT_MODE = {
    Sport.FOOTBALL: TimingMode.FULL_NO_ADS,
    Sport.BASKETBALL: TimingMode.FULL_NO_ADS,
    Sport.HOCKEY: TimingMode.FULL_NO_ADS,
    Sport.SOCCER: TimingMode.GAME_CLOCK,
}

# Soccer clock values are minutes since kick-off of regular/extra time: where each period starts.
_SOCCER_PERIOD_START = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60}


@dataclass(frozen=True)
class TimingParams:
    """Tunables of the timing modes, in seconds."""

    gap_threshold: float = 90.0  # FULL_NO_ADS: gaps longer than this are treated as a break...
    gap_pause: float = 40.0  # ...and shortened to this; also the period break in GAME_CLOCK
    condensed_per_play: float = 13.0  # CONDENSED: duration of every play
    min_gap: float = 3.0  # floor for zero/negative wall-clock gaps (plays logged out of order)


def build_timeline(game: Game, mode: TimingMode, params: TimingParams | None = None) -> list[float]:
    """Replay time (seconds from the first play) at which each play happens. Strictly increasing."""
    params = params or TimingParams()
    plays, sport = game.plays, game.sport
    if not plays:
        return []
    if mode is TimingMode.CONDENSED:
        return [i * params.condensed_per_play for i in range(len(plays))]
    if mode is TimingMode.GAME_CLOCK:
        return _game_clock_timeline(plays, params, sport)

    raw_gaps: list[float | None] = []
    for prev, cur in zip(plays, plays[1:]):
        if prev.wallclock and cur.wallclock:
            raw_gaps.append((cur.wallclock - prev.wallclock).total_seconds())
        else:
            raw_gaps.append(None)
    # Plays without a wall-clock time get the median gap, so a few missing timestamps do not
    # stall or rush the replay.
    known = [g for g in raw_gaps if g is not None and g > 0]
    fallback = median(known) if known else params.gap_pause

    times = [0.0]
    for gap in raw_gaps:
        g = fallback if gap is None else gap
        g = max(g, params.min_gap)
        if mode is TimingMode.FULL_NO_ADS and g > params.gap_threshold:
            g = params.gap_pause
        times.append(times[-1] + g)
    return times


def _elapsed_in_period(play: Play, sport: Sport) -> float | None:
    if play.clock_seconds is None:
        return None
    if sport is Sport.SOCCER:
        return max(play.clock_seconds - _SOCCER_PERIOD_START.get(play.period, 0), 0.0)
    if CLOCK_COUNTS_DOWN[sport]:
        return None  # a countdown clock stops all the time: useless as a timeline
    return play.clock_seconds


def _game_clock_timeline(plays: list[Play], params: TimingParams, sport: Sport) -> list[float]:
    times: list[float] = []
    period_offset = 0.0
    period_end = 0.0
    current_period = plays[0].period
    for play in plays:
        if play.period != current_period:
            period_offset = period_end + params.gap_pause
            current_period = play.period
        elapsed = _elapsed_in_period(play, sport)
        t = period_offset + elapsed if elapsed is not None else (times[-1] if times else 0.0)
        if times and t <= times[-1]:
            t = times[-1] + 1.0  # same minute (substitutions): keep the order, one second apart
        times.append(t)
        period_end = max(period_end, t)
    return [t - times[0] for t in times]


# --- clock ---------------------------------------------------------------------------------


@dataclass
class ReplayClock:
    """Position on a timeline, advancing with a monotonic time source while playing.

    ``now`` is always passed in (seconds, monotonic), which keeps the clock deterministic
    in tests and independent of the Home Assistant event loop.
    """

    times: list[float]
    speed: float = 1.0
    max_burst: int = 3  # crossing more plays than this in one tick is a jump: no events
    _base_pos: float = 0.0
    _base_now: float = 0.0
    _playing: bool = False
    _last_index: int = -1

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def duration(self) -> float:
        return self.times[-1] if self.times else 0.0

    @property
    def anchor(self) -> tuple[float, float, bool, float]:
        """What the position depends on besides time: changes only on play/pause/seek/speed."""
        return self._base_pos, self._base_now, self._playing, self.speed

    def position(self, now: float) -> float:
        pos = self._base_pos
        if self._playing:
            pos += (now - self._base_now) * self.speed
        return min(max(pos, -1.0), self.duration)

    def index_at(self, position: float) -> int:
        """Index of the last play at or before ``position``; -1 before the first play."""
        return bisect_right(self.times, position) - 1

    def current_index(self, now: float) -> int:
        return self.index_at(self.position(now))

    def play(self, now: float) -> None:
        if not self._playing:
            self._base_pos, self._base_now, self._playing = self.position(now), now, True

    def pause(self, now: float) -> None:
        if self._playing:
            self._base_pos, self._playing = self.position(now), False

    def set_speed(self, speed: float, now: float) -> None:
        self._base_pos, self._base_now = self.position(now), now
        self.speed = speed

    def seek(self, position: float, now: float) -> None:
        """Jump without emitting the plays in between."""
        self._base_pos, self._base_now = min(max(position, -1.0), self.duration), now
        self._last_index = self.current_index(now)

    def seek_index(self, index: int, now: float) -> None:
        if not self.times:
            return
        index = min(max(index, 0), len(self.times) - 1)
        self.seek(self.times[index], now)

    def step(self, delta: int, now: float) -> None:
        self.seek_index(self.current_index(now) + delta, now)

    def advance(self, now: float) -> list[int]:
        """Indexes of the plays crossed since the last call, in order (empty on a jump)."""
        index = self.current_index(now)
        crossed = list(range(self._last_index + 1, index + 1))
        self._last_index = index
        if len(crossed) > self.max_burst:
            return []
        return crossed


def find_play(game: Game, period: int, clock: str) -> int | None:
    """Index of the first play of ``period`` at or after the game time ``clock`` ("mm:ss").

    Soccer and hockey clocks count up; football and basketball clocks count down. For
    soccer, ``clock`` is the match minute as shown on screen ("67:00" in the 2nd half).
    """
    mm, _, ss = clock.partition(":")
    try:
        target = int(mm) * 60 + int(ss or 0)
    except ValueError:
        return None
    down = CLOCK_COUNTS_DOWN[game.sport]
    for i, p in enumerate(game.plays):
        if p.period > period:
            return i
        if p.period != period or p.clock_seconds is None:
            continue
        if (down and p.clock_seconds <= target) or (not down and p.clock_seconds >= target):
            return i
    return None
