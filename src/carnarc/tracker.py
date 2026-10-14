"""Plate tracking and multi-frame voting.

A car at highway speed is in good view for well under a second, so a single OCR
read is often wrong (blur, glare, a partial frame). The tracker follows each
plate across frames, collects every OCR read, and votes character-by-character
to produce one consensus read per vehicle.

Memory note: only the best observation's crop/frame are kept per track. Frames
are held by reference, so the camera source must return a fresh array per frame.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .config import PlateRulesConfig, TrackingConfig
from .models import Box, Observation, OcrResult, PlateRead
from .plates import is_plausible


@dataclass
class Vote:
    plate: str
    confidence: float
    n_reads: int  # reads in the winning length group
    alternatives: list[tuple[str, float]]


def vote(reads: list[OcrResult]) -> Vote | None:
    """Combine OCR reads of one plate into a consensus.

    1. Group reads by length and keep the group with the most total weight
       (a read's weight is its mean per-character confidence).
    2. Within the group, pick each character position by confidence-weighted vote.
    3. confidence = (group's share of all weight)
                    x (mean per-position agreement)
                    x (mean read confidence in the group)
       so conflicting lengths, conflicting characters and shaky reads all pull it down.

    Returns None if there are no usable reads.
    """
    reads = [r for r in reads if r.text and len(r.char_conf) == len(r.text)]
    if not reads:
        return None

    total_weight = sum(r.mean_conf for r in reads)
    groups: dict[int, list[OcrResult]] = defaultdict(list)
    for r in reads:
        groups[len(r.text)].append(r)

    def group_weight(rs: list[OcrResult]) -> float:
        return sum(r.mean_conf for r in rs)

    # Heaviest group wins; on a tie prefer the larger group, then the longer plate.
    length, group = max(groups.items(), key=lambda kv: (group_weight(kv[1]), len(kv[1]), kv[0]))

    chars: list[str] = []
    agreements: list[float] = []
    for pos in range(length):
        tally: dict[str, float] = defaultdict(float)
        for r in group:
            tally[r.text[pos]] += r.char_conf[pos] * r.mean_conf
        winner, win_w = max(tally.items(), key=lambda kv: (kv[1], kv[0]))
        chars.append(winner)
        denom = sum(tally.values())
        agreements.append(win_w / denom if denom > 0 else 0.0)

    plate = "".join(chars)
    share = group_weight(group) / total_weight if total_weight > 0 else 0.0
    mean_conf = group_weight(group) / len(group)
    confidence = share * (sum(agreements) / len(agreements)) * mean_conf

    alt_weight: dict[str, float] = defaultdict(float)
    for r in reads:
        if r.text != plate:
            alt_weight[r.text] += r.mean_conf
    alternatives = sorted(
        ((t, w / total_weight) for t, w in alt_weight.items()),
        key=lambda kv: kv[1],
        reverse=True,
    )[:3]

    return Vote(plate, max(0.0, min(1.0, confidence)), len(group), alternatives)


def _quality(obs: Observation) -> float:
    """Which observation makes the best snapshot: confident read, bigger plate."""
    return obs.ocr.mean_conf * obs.det_conf * math.sqrt(max(obs.box.area, 1.0))


@dataclass
class Track:
    id: int
    first_ts: float
    last_ts: float
    last_frame_idx: int
    last_box: Box
    velocity: tuple[float, float] = (0.0, 0.0)  # box-center pixels per frame
    missed: int = 0
    reads: list[OcrResult] = field(default_factory=list)
    best: Observation | None = None
    _best_q: float = -1.0

    def predict(self, frame_idx: int) -> Box:
        dt = frame_idx - self.last_frame_idx
        return self.last_box.shifted(self.velocity[0] * dt, self.velocity[1] * dt)

    def add(self, obs: Observation) -> None:
        dt = obs.frame_idx - self.last_frame_idx
        if dt > 0:
            (ox, oy), (nx, ny) = self.last_box.center, obs.box.center
            self.velocity = ((nx - ox) / dt, (ny - oy) / dt)
        self.last_box = obs.box
        self.last_frame_idx = obs.frame_idx
        self.last_ts = obs.ts
        self.missed = 0
        if obs.ocr.text:
            self.reads.append(obs.ocr)
            q = _quality(obs)
            if q > self._best_q:
                self._best_q, self.best = q, obs


class PlateTracker:
    def __init__(self, tracking: TrackingConfig, rules: PlateRulesConfig):
        self.cfg = tracking
        self.rules = rules
        self.tracks: list[Track] = []
        self._next_id = 1
        self.dropped_short = 0
        self.dropped_implausible = 0

    # -- association -----------------------------------------------------

    def _match(self, boxes: list[Box], frame_idx: int) -> list[tuple[int, int]]:
        """Greedy track<->box assignment, best score first.

        Primary score is IoU against the predicted box. If boxes do not overlap
        (fast movers can jump more than a plate width between frames) a
        center-distance gate of `gate_widths` plate widths still allows a match,
        scored lower than any real overlap.
        """
        candidates: list[tuple[float, int, int]] = []
        for ti, t in enumerate(self.tracks):
            pred = t.predict(frame_idx)
            for bi, b in enumerate(boxes):
                iou = max(pred.iou(b), t.last_box.iou(b))
                if iou >= self.cfg.iou_threshold:
                    candidates.append((1.0 + iou, ti, bi))
                    continue
                (px, py), (bx, by) = pred.center, b.center
                dist = math.hypot(px - bx, py - by)
                gate = self.cfg.gate_widths * max(pred.width, b.width, 1.0)
                if dist <= gate:
                    candidates.append((1.0 - dist / gate, ti, bi))
        candidates.sort(key=lambda c: c[0], reverse=True)

        used_t: set[int] = set()
        used_b: set[int] = set()
        pairs: list[tuple[int, int]] = []
        for _score, ti, bi in candidates:
            if ti in used_t or bi in used_b:
                continue
            used_t.add(ti)
            used_b.add(bi)
            pairs.append((ti, bi))
        return pairs

    # -- public API --------------------------------------------------------

    def update(self, observations: list[Observation], frame_idx: int) -> list[PlateRead]:
        """Feed one frame's observations; returns reads for tracks that just ended."""
        boxes = [o.box for o in observations]
        pairs = self._match(boxes, frame_idx)
        matched_t = {ti for ti, _ in pairs}
        matched_b = {bi for _, bi in pairs}

        for ti, bi in pairs:
            self.tracks[ti].add(observations[bi])

        for bi, obs in enumerate(observations):
            if bi in matched_b:
                continue
            track = Track(
                id=self._next_id,
                first_ts=obs.ts,
                last_ts=obs.ts,
                last_frame_idx=obs.frame_idx,
                last_box=obs.box,
            )
            self._next_id += 1
            track.add(obs)
            self.tracks.append(track)

        finished: list[PlateRead] = []
        alive: list[Track] = []
        for ti, t in enumerate(self.tracks):
            if ti not in matched_t and t.last_frame_idx != frame_idx:
                t.missed += 1
            if t.missed > self.cfg.max_missed_frames:
                read = self._finalize(t)
                if read:
                    finished.append(read)
            else:
                alive.append(t)
        self.tracks = alive
        return finished

    def flush(self) -> list[PlateRead]:
        """End of stream: finalize every open track."""
        out = [r for t in self.tracks if (r := self._finalize(t))]
        self.tracks = []
        return out

    # -- internals ---------------------------------------------------------

    def _finalize(self, t: Track) -> PlateRead | None:
        if len(t.reads) < self.cfg.min_reads or t.best is None:
            self.dropped_short += 1
            return None
        v = vote(t.reads)
        if v is None or not is_plausible(v.plate, self.rules) or v.confidence < self.rules.min_confidence:
            self.dropped_implausible += 1
            return None
        return PlateRead(
            track_id=t.id,
            plate=v.plate,
            confidence=v.confidence,
            n_reads=len(t.reads),
            first_ts=t.first_ts,
            last_ts=t.last_ts,
            box=t.best.box,
            crop=t.best.crop,
            frame=t.best.frame,
            alternatives=v.alternatives,
        )
