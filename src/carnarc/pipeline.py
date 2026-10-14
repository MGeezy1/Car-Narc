"""The capture pipeline: frame -> plate boxes -> OCR -> tracker -> sinks."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .camera import Frame, FrameSource
from .config import Config
from .detect import PlateDetectorLike
from .models import Observation, PlateRead
from .ocr import PlateReaderLike
from .outputs import LogSink, Sink, StoreSink
from .storage import SnapshotWriter, Store
from .tracker import PlateTracker

log = logging.getLogger(__name__)

# Crops smaller than this are skipped: OCR resizes to 128x64, so a smaller plate
# is mostly interpolation and its reads would pollute the vote.
MIN_PLATE_W = 24
MIN_PLATE_H = 8


@dataclass
class Stats:
    frames: int = 0
    detections: int = 0
    reads: int = 0
    busy_seconds: float = 0.0
    started: float = field(default_factory=time.time)

    def summary(self) -> str:
        wall = max(time.time() - self.started, 1e-6)
        per_frame = 1000 * self.busy_seconds / self.frames if self.frames else 0.0
        return (
            f"frames={self.frames} ({self.frames / wall:.1f}/s, {per_frame:.0f} ms inference/frame) "
            f"plate-detections={self.detections} reads={self.reads}"
        )


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        detector: PlateDetectorLike,
        reader: PlateReaderLike,
        tracker: PlateTracker | None = None,
        sinks: Sequence[Sink] = (),
    ):
        self.cfg = cfg
        self.detector = detector
        self.reader = reader
        self.tracker = tracker or PlateTracker(cfg.tracking, cfg.plate_rules)
        self.sinks = list(sinks)
        self.stats = Stats()

    def process(self, frame: Frame) -> list[PlateRead]:
        t0 = time.perf_counter()
        h, w = frame.image.shape[:2]

        kept = []
        crops = []
        for det in self.detector.detect(frame.image):
            pb = det.box.padded(self.cfg.detection.crop_margin, w, h)
            x1, y1 = int(math.floor(pb.x1)), int(math.floor(pb.y1))
            x2, y2 = int(math.ceil(pb.x2)), int(math.ceil(pb.y2))
            if (x2 - x1) < MIN_PLATE_W or (y2 - y1) < MIN_PLATE_H:
                continue
            kept.append(det)
            crops.append(frame.image[y1:y2, x1:x2])

        results = self.reader.read(crops)
        observations = [
            Observation(frame.idx, frame.ts, det.box, det.confidence, res, crop, frame.image)
            for det, res, crop in zip(kept, results, crops)
        ]
        # Always call update(), even with no detections: that is how tracks age out.
        reads = self.tracker.update(observations, frame.idx)

        self.stats.frames += 1
        self.stats.detections += len(kept)
        self.stats.busy_seconds += time.perf_counter() - t0
        self._emit(reads)
        return reads

    def finish(self) -> list[PlateRead]:
        reads = self.tracker.flush()
        self._emit(reads)
        return reads

    def run(self, frames: Iterable[Frame]) -> None:
        last_log = time.time()
        try:
            for frame in frames:
                self.process(frame)
                if time.time() - last_log >= 30:
                    log.info(self.stats.summary())
                    last_log = time.time()
        finally:
            # Also runs on Ctrl-C, so plates still being tracked are not lost.
            self.finish()
            log.info("done: %s", self.stats.summary())

    def _emit(self, reads: list[PlateRead]) -> None:
        for read in reads:
            self.stats.reads += 1
            for sink in self.sinks:
                try:
                    sink.handle(read)
                except Exception:
                    log.exception("sink %s failed", type(sink).__name__)


def build_pipeline(cfg: Config) -> Pipeline:
    """Construct the real pipeline (loads models; downloads them on first run)."""
    from .detect import PlateDetector
    from .ocr import PlateReader

    store = Store(cfg.db_path)
    snapshots = SnapshotWriter(cfg) if cfg.storage.save_snapshots else None
    return Pipeline(
        cfg,
        PlateDetector(cfg.detection),
        PlateReader(cfg.ocr),
        sinks=[LogSink(), StoreSink(store, snapshots)],
    )


def run_capture(cfg: Config, source: FrameSource) -> None:
    pipeline = build_pipeline(cfg)
    try:
        pipeline.run(source.frames())
    finally:
        source.close()
