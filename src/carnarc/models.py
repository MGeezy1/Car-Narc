"""Plain data types shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Box:
    """Axis-aligned box in full-frame pixel coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def shifted(self, dx: float, dy: float) -> "Box":
        return Box(self.x1 + dx, self.y1 + dy, self.x2 + dx, self.y2 + dy)

    def iou(self, other: "Box") -> float:
        ix1, iy1 = max(self.x1, other.x1), max(self.y1, other.y1)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def padded(self, margin: float, frame_w: int, frame_h: int) -> "Box":
        """Grow by a fraction of width/height, clamped to the frame."""
        mx, my = self.width * margin, self.height * margin
        return Box(
            max(0.0, self.x1 - mx),
            max(0.0, self.y1 - my),
            min(float(frame_w), self.x2 + mx),
            min(float(frame_h), self.y2 + my),
        )


@dataclass(frozen=True)
class Detection:
    box: Box
    confidence: float


@dataclass(frozen=True)
class OcrResult:
    text: str  # normalized: uppercase A-Z / 0-9 only
    char_conf: tuple[float, ...]  # one entry per character of `text`

    @property
    def mean_conf(self) -> float:
        return float(np.mean(self.char_conf)) if self.char_conf else 0.0


@dataclass
class Observation:
    """One OCR read of one plate in one frame."""

    frame_idx: int
    ts: float
    box: Box
    det_conf: float
    ocr: OcrResult
    crop: np.ndarray  # BGR plate crop
    frame: np.ndarray  # full BGR frame (reference, not a copy)


@dataclass
class PlateRead:
    """Final, voted result for one vehicle's plate."""

    track_id: int
    plate: str
    confidence: float  # 0..1, see tracker.vote()
    n_reads: int
    first_ts: float
    last_ts: float
    box: Box  # plate box in the best frame
    crop: np.ndarray  # best plate crop (BGR)
    frame: np.ndarray  # best full frame (BGR)
    alternatives: list[tuple[str, float]] = field(default_factory=list)
