from types import SimpleNamespace

import cv2
import numpy as np

from carnarc.bench import Score, levenshtein, load_labels, run_bench
from carnarc.config import DetectionConfig
from carnarc.detect import PlateDetector
from carnarc.models import Box, Detection

from conftest import ocr


def test_levenshtein():
    assert levenshtein("ABC123", "ABC123") == 0
    assert levenshtein("ABC123", "ABC128") == 1
    assert levenshtein("ABC123", "AC123") == 1
    assert levenshtein("", "ABC") == 3
    assert levenshtein("KITTEN", "SITTING") == 3


def test_score_math():
    s = Score()
    s.add("a.jpg", "ABC1234", "ABC1234")
    s.add("b.jpg", "XYZ7890", "XYZ7B90")  # one wrong char
    s.add("c.jpg", "QQQ1111", "")  # nothing found
    assert s.total == 3 and s.exact == 1 and s.detected == 2
    assert abs(s.exact_rate - 1 / 3) < 1e-9
    assert abs(s.char_error_rate - (0 + 1 + 7) / 21) < 1e-9
    report = s.report()
    assert "expected XYZ7890, got XYZ7B90" in report
    assert "(nothing)" in report


def test_load_labels_handles_header_comments_and_formatting(tmp_path):
    p = tmp_path / "labels.csv"
    p.write_text("filename,plate\n# a comment\nimg1.jpg, abc-1234\n\nimg2.jpg,XYZ 99\nbroken\n")
    assert load_labels(p) == [("img1.jpg", "ABC1234"), ("img2.jpg", "XYZ99")]


class FixedReader:
    def __init__(self, text="ABC1234"):
        self.text = text

    def read(self, crops):
        return [ocr(self.text, 0.9) for _ in crops]


class FixedDetector:
    def __init__(self, boxes):
        self.boxes = boxes

    def detect(self, frame):
        return [Detection(b, 0.9) for b in self.boxes]


def write_img(path, w=200, h=100):
    cv2.imwrite(str(path), np.full((h, w, 3), 128, np.uint8))


def test_run_bench_on_crops(tmp_path):
    write_img(tmp_path / "a.png")
    s = run_bench(tmp_path, [("a.png", "ABC1234")], FixedReader("ABC1234"), detector=None)
    assert s.exact == 1


def test_run_bench_full_frame_and_missing_detection(tmp_path):
    write_img(tmp_path / "a.png")
    labels = [("a.png", "ABC1234")]
    hit = run_bench(tmp_path, labels, FixedReader("ABC1234"), FixedDetector([Box(20, 20, 120, 60)]))
    assert hit.exact == 1
    none = run_bench(tmp_path, labels, FixedReader("ABC1234"), FixedDetector([]))
    assert none.exact == 0 and none.detected == 0


def test_run_bench_unreadable_image_counts_as_a_miss(tmp_path):
    s = run_bench(tmp_path, [("missing.png", "ABC1234")], FixedReader(), detector=None)
    assert s.total == 1 and s.exact == 0


def test_run_bench_picks_the_most_confident_of_several_plates(tmp_path):
    write_img(tmp_path / "a.png")

    class TwoReads:
        def read(self, crops):
            return [ocr("WRONG11", 0.4), ocr("ABC1234", 0.95)][: len(crops)]

    dets = FixedDetector([Box(10, 10, 60, 30), Box(100, 50, 190, 90)])
    s = run_bench(tmp_path, [("a.png", "ABC1234")], TwoReads(), dets)
    assert s.exact == 1


def test_detector_maps_roi_boxes_back_to_full_frame_coordinates():
    d = PlateDetector.__new__(PlateDetector)  # skip __init__ so no model is loaded
    d.cfg = DetectionConfig(roi=[0.25, 0.5, 0.5, 0.5])
    seen = {}

    class FakeModel:
        def predict(self, img):
            seen["shape"] = img.shape
            return [SimpleNamespace(bounding_box=SimpleNamespace(x1=10, y1=20, x2=60, y2=40), confidence=0.8)]

    d._model = FakeModel()
    frame = np.zeros((400, 800, 3), np.uint8)
    out = d.detect(frame)
    assert seen["shape"] == (200, 400, 3)  # only the ROI is sent to the model
    assert out == [Detection(Box(210, 220, 260, 240), 0.8)]  # x + 200, y + 200
