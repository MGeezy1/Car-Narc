"""Runs the real ONNX models. Downloads them on first run (a few MB), so it is
opt-in:  pytest -m slow
"""

import cv2
import numpy as np
import pytest

from carnarc.config import Config
from carnarc.ocr import PlateReader

pytestmark = pytest.mark.slow


def render_plate(text: str) -> np.ndarray:
    img = np.full((80, 280, 3), 255, np.uint8)  # BGR, white
    cv2.putText(img, text, (8, 56), cv2.FONT_HERSHEY_DUPLEX, 1.6, (20, 20, 20), 3, cv2.LINE_AA)
    return img


@pytest.fixture(scope="module")
def reader() -> PlateReader:
    return PlateReader(Config().ocr)


def test_ocr_reads_rendered_plates_with_aligned_confidences(reader):
    results = reader.read([render_plate("ABC1234"), render_plate("KLM5678")])
    assert [r.text for r in results] == ["ABC1234", "KLM5678"]
    for r in results:
        assert len(r.char_conf) == len(r.text)  # padding slots were trimmed
        assert all(0.0 <= c <= 1.0 for c in r.char_conf)
        assert r.mean_conf > 0.8


def test_ocr_empty_input(reader):
    assert reader.read([]) == []


def test_plate_detector_loads_and_returns_nothing_on_a_blank_frame():
    from carnarc.detect import PlateDetector

    det = PlateDetector(Config().detection)
    assert det.detect(np.zeros((720, 1280, 3), np.uint8)) == []
