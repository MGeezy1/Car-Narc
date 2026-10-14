"""Plate accuracy benchmark.

Point it at a folder of images and a CSV of ground-truth plates:

    carnarc bench ./labeled ./labeled/labels.csv            # full frames: detect + OCR
    carnarc bench ./crops   ./crops/labels.csv --crops      # images are already plate crops

labels.csv has one `filename,PLATE` row per image (a header row is fine; lines
starting with # are ignored). This scores *single-frame* reads. To see what
multi-frame voting adds, replay a video through the pipeline with
`carnarc run --source clip.mp4 --dry-run`.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from .detect import PlateDetectorLike
from .ocr import PlateReaderLike
from .plates import normalize


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass
class Score:
    total: int = 0
    detected: int = 0  # images where a plate was found and read
    exact: int = 0
    edit_distance: int = 0
    truth_chars: int = 0
    misses: list[tuple[str, str, str]] = field(default_factory=list)  # (file, truth, predicted)

    def add(self, filename: str, truth: str, pred: str) -> None:
        self.total += 1
        self.truth_chars += len(truth)
        self.edit_distance += levenshtein(truth, pred)
        if pred:
            self.detected += 1
        if pred == truth:
            self.exact += 1
        else:
            self.misses.append((filename, truth, pred))

    @property
    def exact_rate(self) -> float:
        return self.exact / self.total if self.total else 0.0

    @property
    def char_error_rate(self) -> float:
        return self.edit_distance / self.truth_chars if self.truth_chars else 0.0

    def report(self, max_misses: int = 15) -> str:
        lines = [
            f"images:            {self.total}",
            f"plate found+read:  {self.detected} ({self.detected / self.total:.1%})" if self.total else "images: 0",
            f"exact match:       {self.exact} ({self.exact_rate:.1%})",
            f"char error rate:   {self.char_error_rate:.1%}",
        ]
        if self.misses:
            lines.append("")
            lines.append(f"misses (showing {min(len(self.misses), max_misses)} of {len(self.misses)}):")
            for fname, truth, pred in self.misses[:max_misses]:
                lines.append(f"  {fname}: expected {truth}, got {pred or '(nothing)'}")
        return "\n".join(lines)


def load_labels(path: str | Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with open(path, newline="") as fh:
        for i, row in enumerate(csv.reader(fh)):
            if len(row) < 2 or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            if i == 0 and row[0].strip().lower() in {"file", "filename", "image"}:
                continue
            plate = normalize(row[1])
            if plate:
                rows.append((row[0].strip(), plate))
    return rows


def run_bench(
    image_dir: str | Path,
    labels: list[tuple[str, str]],
    reader: PlateReaderLike,
    detector: PlateDetectorLike | None,
    crop_margin: float = 0.08,
) -> Score:
    """detector=None means the images are already plate crops."""
    score = Score()
    for filename, truth in labels:
        img = cv2.imread(str(Path(image_dir) / filename))
        if img is None:
            print(f"warning: cannot read {filename}; counted as a miss")
            score.add(filename, truth, "")
            continue

        if detector is None:
            res = reader.read([img])[0]
            score.add(filename, truth, res.text)
            continue

        h, w = img.shape[:2]
        dets = detector.detect(img)
        crops = []
        for d in dets:
            pb = d.box.padded(crop_margin, w, h)
            crop = img[int(pb.y1) : int(pb.y2) + 1, int(pb.x1) : int(pb.x2) + 1]
            crops.append(crop)
        usable = [(d, c) for d, c in zip(dets, crops) if c.size > 0]
        if not usable:
            score.add(filename, truth, "")
            continue
        results = reader.read([c for _, c in usable])
        # If several plates are in the image, take the most confident read.
        best = max(zip(usable, results), key=lambda pr: pr[0][0].confidence * pr[1].mean_conf)
        score.add(filename, truth, best[1].text)
    return score
