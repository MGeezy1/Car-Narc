"""Merge duplicate reads of one vehicle.

The tracker can lose a plate for a moment (a missed detection, a blur) and then
start a fresh track when it reappears, so one car becomes several short reads,
and the early ones are usually the blurriest and wrongest. In practice the
fragments are strictly sequential (the plate is gone, then back), whereas two
different cars side by side are visible at the same time.

So a finished read is held briefly, and a later read is merged into it when:
  - their time spans do not overlap (one vehicle cannot be tracked twice at once),
  - the gap between them is within `window_s`, and
  - the plates are within `max_edit_distance` of each other. A new read is compared
    with every plate that has actually been merged into the held read, so a chain
    A~B~C still joins up. The tracker's own `alternatives` are deliberately NOT used:
    a track that briefly absorbed a neighbouring car's reads carries that car's plate
    as an alternative, and matching on it would merge two different vehicles.

The best-supported read (reads x confidence) wins; the losing plate is kept in
`alternatives` so the disagreement stays visible.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .config import MergeConfig
from .models import PlateRead
from .plates import levenshtein


def _support(r: PlateRead) -> float:
    return r.n_reads * r.confidence


@dataclass
class _Held:
    read: PlateRead
    members: set[str]  # main plates of every read merged into `read` so far


class ReadMerger:
    def __init__(self, cfg: MergeConfig):
        self.cfg = cfg
        self._pending: list[_Held] = []
        self.merged = 0  # how many reads were folded into another

    @property
    def enabled(self) -> bool:
        return self.cfg.window_s > 0

    def push(self, read: PlateRead) -> None:
        """Add a finished read, merging it into a pending one if it is the same vehicle."""
        if self.enabled:
            for i, held in enumerate(self._pending):
                if self._same_vehicle(held, read):
                    self._pending[i] = _Held(self._combine(held.read, read), held.members | {read.plate})
                    self.merged += 1
                    return
        self._pending.append(_Held(read, {read.plate}))

    def release(self, now: float, flush: bool = False, live_starts: Iterable[float] = ()) -> list[PlateRead]:
        """Reads that are ready to emit.

        A read is ready once it has gone unseen for `window_s`, unless a still-live track
        started within that window after it (its probable continuation), in which case it
        waits for that track to finish, for at most `max_hold_s`. `flush` releases everything.
        `live_starts` are the start times of the tracks that are still open.
        """
        starts = list(live_starts)
        ready: list[PlateRead] = []
        keep: list[_Held] = []
        for held in self._pending:
            r = held.read
            if flush or (now - r.last_ts >= self.cfg.window_s and not self._successor_live(r, starts, now)):
                ready.append(r)
            else:
                keep.append(held)
        self._pending = keep
        return ready

    def _successor_live(self, r: PlateRead, starts: list[float], now: float) -> bool:
        if now - r.last_ts >= self.cfg.max_hold_s:
            return False
        return any(r.last_ts <= s <= r.last_ts + self.cfg.window_s for s in starts)

    # -- internals -----------------------------------------------------------

    def _same_vehicle(self, held: _Held, b: PlateRead) -> bool:
        a = held.read
        if b.first_ts >= a.last_ts:
            gap = b.first_ts - a.last_ts
        elif a.first_ts >= b.last_ts:
            gap = a.first_ts - b.last_ts
        else:
            return False  # overlapping in time: two vehicles, not one
        if gap > self.cfg.window_s:
            return False
        return any(levenshtein(m, b.plate) <= self.cfg.max_edit_distance for m in held.members)

    @staticmethod
    def _combine(a: PlateRead, b: PlateRead) -> PlateRead:
        winner, loser = (a, b) if _support(a) >= _support(b) else (b, a)
        total = a.n_reads + b.n_reads
        # Weights are "share of all reads that read this text". Each side's alternatives
        # are relative to its own reads, so rescale them, and carry over the loser's own
        # alternatives too, or earlier dissent is lost when three or more fragments join.
        alts: dict[str, float] = {}

        def note(text: str, weight: float) -> None:
            if text != winner.plate:
                alts[text] = max(alts.get(text, 0.0), weight)

        for t, w in winner.alternatives:
            note(t, w * winner.n_reads / total)
        note(loser.plate, loser.n_reads / total)
        for t, w in loser.alternatives:
            note(t, w * loser.n_reads / total)
        top = sorted(alts.items(), key=lambda kv: kv[1], reverse=True)[:3]
        return replace(
            winner,
            n_reads=total,
            first_ts=min(a.first_ts, b.first_ts),
            last_ts=max(a.last_ts, b.last_ts),
            alternatives=top,
        )
