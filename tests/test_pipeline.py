import cv2
import numpy as np

from carnarc.camera import Frame
from carnarc.models import Box, Detection
from carnarc.outputs import StoreSink
from carnarc.pipeline import MIN_PLATE_W, Pipeline
from carnarc.storage import SnapshotWriter, Store

from conftest import ocr


class ScriptedDetector:
    """Returns the boxes scheduled for each frame index."""

    def __init__(self, schedule: dict[int, list[Box]]):
        self.schedule = schedule

    def detect(self, frame_bgr):
        idx = int(frame_bgr[0, 0, 0])  # frame index is smuggled in pixel (0,0)
        return [Detection(b, 0.9) for b in self.schedule.get(idx, [])]


class ScriptedReader:
    def __init__(self, texts: list[str]):
        self.texts = texts
        self.calls = 0

    def read(self, crops):
        out = []
        for _ in crops:
            out.append(ocr(self.texts[self.calls % len(self.texts)], 0.95))
            self.calls += 1
        return out


def frame(idx: int) -> Frame:
    img = np.full((480, 640, 3), 40, np.uint8)
    img[0, 0, 0] = idx
    return Frame(idx, 1000.0 + idx / 30, img)


def plate_box(x: float) -> Box:
    return Box(x, 200, x + 90, 230)


def test_plate_seen_over_several_frames_yields_one_voted_read(cfg):
    cfg.tracking.max_missed_frames = 3
    schedule = {i: [plate_box(100 + 12 * i)] for i in range(1, 7)}
    # one frame misreads the plate; voting should outvote it
    reader = ScriptedReader(["ABC1234", "ABC1234", "A8C1234", "ABC1234", "ABC1234", "ABC1234"])
    got = []

    class Collect:
        def handle(self, read):
            got.append(read)

    pipe = Pipeline(cfg, ScriptedDetector(schedule), reader, sinks=[Collect()])
    for i in range(1, 13):
        pipe.process(frame(i))
    pipe.finish()

    assert [r.plate for r in got] == ["ABC1234"]
    assert got[0].n_reads == 6
    assert pipe.stats.frames == 12
    assert pipe.stats.reads == 1


def test_tiny_plate_detections_are_skipped(cfg):
    tiny = Box(100, 100, 100 + MIN_PLATE_W - 10, 130)
    reader = ScriptedReader(["ABC1234"])
    pipe = Pipeline(cfg, ScriptedDetector({1: [tiny]}), reader)
    pipe.process(frame(1))
    assert reader.calls == 0
    assert pipe.stats.detections == 0


def test_failing_sink_does_not_stop_others(cfg):
    cfg.tracking.max_missed_frames = 1
    seen = []

    class Boom:
        def handle(self, read):
            raise RuntimeError("sink down")

    class Collect:
        def handle(self, read):
            seen.append(read.plate)

    schedule = {i: [plate_box(100)] for i in range(1, 4)}
    pipe = Pipeline(cfg, ScriptedDetector(schedule), ScriptedReader(["ABC1234"]), sinks=[Boom(), Collect()])
    for i in range(1, 8):
        pipe.process(frame(i))
    pipe.finish()
    assert seen == ["ABC1234"]


def test_store_sink_persists_read_and_snapshots(cfg):
    cfg.tracking.max_missed_frames = 1
    store = Store(cfg.db_path)
    sink = StoreSink(store, SnapshotWriter(cfg))
    store.watchlist_add("ABC1234", "test")

    schedule = {i: [plate_box(100)] for i in range(1, 4)}
    pipe = Pipeline(cfg, ScriptedDetector(schedule), ScriptedReader(["ABC1234"]), sinks=[sink])
    for i in range(1, 8):
        pipe.process(frame(i))
    pipe.finish()

    rows = store.recent()
    assert len(rows) == 1
    row = rows[0]
    assert row["plate"] == "ABC1234"
    assert row["watchlist_hit"] == 1
    for rel in (row["snapshot"], row["crop"]):
        path = cfg.snapshot_dir / rel
        assert path.is_file()
        assert cv2.imread(str(path)) is not None


def test_run_flushes_open_tracks_when_the_stream_ends(cfg):
    got = []

    class Collect:
        def handle(self, read):
            got.append(read.plate)

    schedule = {i: [plate_box(100)] for i in range(1, 4)}
    pipe = Pipeline(cfg, ScriptedDetector(schedule), ScriptedReader(["ABC1234"]), sinks=[Collect()])
    pipe.run(frame(i) for i in range(1, 4))  # stream ends while the plate is still in view
    assert got == ["ABC1234"]
