"""Plate OCR (wraps fast-plate-ocr)."""

from __future__ import annotations

from typing import Protocol

import cv2
import numpy as np

from .config import OcrConfig
from .models import OcrResult
from .plates import normalize


class PlateReaderLike(Protocol):
    def read(self, crops_bgr: list[np.ndarray]) -> list[OcrResult]: ...


class PlateReader:
    """Reads plate text from BGR crops.

    Two details that are easy to get wrong and silently hurt accuracy:
    - OpenCV frames are BGR, but the model config says what it was trained on
      (RGB or grayscale); crops are converted to match.
    - fast-plate-ocr returns a fixed number of character slots (padded), so
      per-character confidences are trimmed to the decoded text length.
    """

    def __init__(self, cfg: OcrConfig):
        from fast_plate_ocr import LicensePlateRecognizer

        self._model = LicensePlateRecognizer(cfg.model, device=cfg.device)
        self._color_mode = str(self._model.config.image_color_mode)

    def _prepare(self, crop_bgr: np.ndarray) -> np.ndarray:
        if self._color_mode == "grayscale":
            return cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)

    def read(self, crops_bgr: list[np.ndarray]) -> list[OcrResult]:
        if not crops_bgr:
            return []
        preds = self._model.run([self._prepare(c) for c in crops_bgr], return_confidence=True)
        results: list[OcrResult] = []
        for p in preds:
            raw = p.plate
            probs = p.char_probs
            if probs is None:
                results.append(OcrResult("", ()))
                continue
            # Normalize character-by-character so text and confidences stay aligned
            # even if a non-alphanumeric character were ever decoded.
            kept = [(ch, float(probs[i])) for i, ch in enumerate(raw) if i < len(probs)]
            text_chars = [(normalize(ch), c) for ch, c in kept]
            # len == 1 keeps text and confidences index-aligned (.upper() can expand some chars)
            text_chars = [(ch, c) for ch, c in text_chars if len(ch) == 1]
            text = "".join(ch for ch, _ in text_chars)
            conf = tuple(c for _, c in text_chars)
            results.append(OcrResult(text, conf))
        return results
