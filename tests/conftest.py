import numpy as np
import pytest

from carnarc.config import Config
from carnarc.models import Box, Observation, OcrResult


def ocr(text: str, conf: float | list[float] = 0.95) -> OcrResult:
    confs = [conf] * len(text) if isinstance(conf, (int, float)) else list(conf)
    return OcrResult(text, tuple(confs))


def make_obs(frame_idx: int, box: Box, text: str, conf: float = 0.95, det_conf: float = 0.9) -> Observation:
    frame = np.zeros((480, 640, 3), np.uint8)
    crop = np.zeros((20, 60, 3), np.uint8)
    return Observation(frame_idx, float(frame_idx) / 30, box, det_conf, ocr(text, conf), crop, frame)


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config()
    c.storage.data_dir = str(tmp_path / "data")
    return c
