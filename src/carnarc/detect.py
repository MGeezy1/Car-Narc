"""Plate detection (wraps open-image-models)."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from .config import DetectionConfig
from .models import Box, Detection


class PlateDetectorLike(Protocol):
    def detect(self, frame_bgr: np.ndarray) -> list[Detection]: ...


class PlateDetector:
    """Finds license plates in a BGR frame.

    Detection runs on the configured region of interest only, then boxes are
    mapped back to full-frame coordinates. A tight ROI over the lane is the
    cheapest way to make distant plates larger relative to the model's input size.
    """

    def __init__(self, cfg: DetectionConfig, providers: list[str] | None = None):
        # Imported lazily so config/tracker/web code and tests don't need the
        # ONNX stack (or a model download) just to import this module.
        from open_image_models import create_detector

        self.cfg = cfg
        self._model = create_detector(
            cfg.plate_model,
            conf_thresh=cfg.conf_thresh,
            providers=providers,
        )

    def _roi_pixels(self, w: int, h: int) -> tuple[int, int, int, int]:
        rx, ry, rw, rh = self.cfg.roi
        x1, y1 = int(round(rx * w)), int(round(ry * h))
        x2, y2 = int(round((rx + rw) * w)), int(round((ry + rh) * h))
        return x1, y1, min(x2, w), min(y2, h)

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = self._roi_pixels(w, h)
        roi = frame_bgr[y1:y2, x1:x2]
        if roi.size == 0:
            return []
        out: list[Detection] = []
        for r in self._model.predict(roi):
            b = r.bounding_box
            out.append(
                Detection(
                    box=Box(b.x1 + x1, b.y1 + y1, b.x2 + x1, b.y2 + y1),
                    confidence=float(r.confidence),
                )
            )
        return out
