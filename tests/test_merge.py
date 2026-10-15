import numpy as np

from carnarc.camera import Frame
from carnarc.config import Config, MergeConfig
from carnarc.merge import ReadMerger
from carnarc.models import Box, Detection, PlateRead
from carnarc.pipeline import Pipeline

from conftest import ocr


def mk(plate, n, conf, first, last, alts=()) -> PlateRead:
    return PlateRead(
        track_id=1, plate=plate, confidence=conf, n_reads=n, first_ts=first, last_ts=last,
        box=Box(0, 0, 10, 5), crop=np.zeros((5, 10, 3), np.uint8), frame=np.zeros((10, 10, 3), np.uint8),
        alternatives=list(alts),
    )


def merger(**kw) -> ReadMerger:
    return ReadMerger(MergeConfig(**{"window_s": 3.0, "max_edit_distance": 2, **kw}))


def test_sequential_fragments_merge_and_best_supported_read_wins():
    m = merger()
    m.push(mk("CE61WVL", n=2, conf=0.81, first=51.43, last=51.47))
    m.push(mk("CE61NVL", n=3, conf=0.86, first=51.93, last=52.00))
    m.push(mk("CE61WYL", n=164, conf=0.95, first=52.40, last=58.53))
    out = m.release(0.0, flush=True)
    assert len(out) == 1 and m.merged == 2
    r = out[0]
    assert r.plate == "CE61WYL"  # the long, confident track wins
    assert r.n_reads == 2 + 3 + 164
    assert (r.first_ts, r.last_ts) == (51.43, 58.53)
    assert {t for t, _ in r.alternatives} == {"CE61WVL", "CE61NVL"}  # disagreement stays visible


def test_chain_joins_through_plates_already_merged_in():
    """A~B and B~C (1 edit each) join even though A and C are 2 edits apart."""
    m = merger(max_edit_distance=1)
    m.push(mk("CE61WVL", 5, 0.9, 0.0, 1.0))
    m.push(mk("CE61WYL", 6, 0.9, 1.2, 2.0))  # 1 edit from WVL
    m.push(mk("CE61WYI", 4, 0.9, 2.2, 3.0))  # 1 edit from WYL, 2 from WVL
    assert len(m.release(0.0, flush=True)) == 1


def test_the_trackers_own_alternatives_are_not_used_to_match():
    """Regression: at low frame rates a track can absorb a neighbouring car's reads, so its
    `alternatives` hold that car's plate. Matching on them merged two different vehicles."""
    m = merger()
    contaminated = mk("EF10DZT", n=19, conf=0.9, first=17.7, last=21.5, alts=[("AF65JKI", 0.05), ("AF65JH", 0.05)])
    neighbour = mk("AF65JKV", n=7, conf=0.98, first=21.7, last=23.7)  # sequential, within the window
    m.push(contaminated)
    m.push(neighbour)
    assert sorted(r.plate for r in m.release(0.0, flush=True)) == ["AF65JKV", "EF10DZT"]
    assert m.merged == 0


def test_overlapping_vehicles_are_never_merged():
    """Two cars visible at the same time are two cars, even with near-identical plates."""
    m = merger()
    m.push(mk("AB12CDE", 50, 0.95, first=10.0, last=14.0))
    m.push(mk("AB12CDF", 60, 0.95, first=11.0, last=15.0))
    assert sorted(r.plate for r in m.release(0.0, flush=True)) == ["AB12CDE", "AB12CDF"]
    assert m.merged == 0


def test_different_plates_are_not_merged():
    m = merger()
    m.push(mk("AB12CDE", 50, 0.95, 10.0, 12.0))
    m.push(mk("XY99ZZZ", 50, 0.95, 12.5, 14.0))
    assert len(m.release(0.0, flush=True)) == 2


def test_edit_distance_limit_is_respected():
    m = merger(max_edit_distance=1)
    m.push(mk("AB12CDE", 50, 0.95, 10.0, 12.0))
    m.push(mk("AB12CXY", 50, 0.95, 12.5, 14.0))  # 2 edits away
    assert len(m.release(0.0, flush=True)) == 2


def test_gap_longer_than_window_is_not_merged():
    m = merger(window_s=3.0)
    m.push(mk("AB12CDE", 50, 0.95, 10.0, 12.0))
    m.push(mk("AB12CDE", 50, 0.95, 20.0, 22.0))  # same plate, but 8 s later: a different pass
    assert len(m.release(0.0, flush=True)) == 2


def test_reads_are_held_until_the_window_passes():
    m = merger(window_s=3.0)
    m.push(mk("AB12CDE", 50, 0.95, 10.0, 12.0))
    assert m.release(now=13.0) == []  # only 1 s since last seen
    assert [r.plate for r in m.release(now=15.0)] == ["AB12CDE"]
    assert m.release(now=99.0) == []  # already released


def test_window_zero_disables_merging_and_emits_immediately():
    m = merger(window_s=0)
    m.push(mk("AB12CDE", 50, 0.95, 10.0, 12.0))
    m.push(mk("AB12CDE", 50, 0.95, 12.1, 13.0))
    assert len(m.release(now=13.0)) == 2 and m.merged == 0


def test_a_read_waits_for_a_live_successor_track_then_merges():
    """The long track of the same car is still being tracked when the fragment's window ends."""
    m = merger(window_s=3.0, max_hold_s=10.0)
    m.push(mk("AB12CDF", n=3, conf=0.6, first=2.13, last=2.33))
    # window (3 s) has long passed, but a track that began at 2.70 is still live: keep waiting
    assert m.release(now=7.0, live_starts=[2.70]) == []
    m.push(mk("AB12CDE", n=163, conf=0.9, first=2.70, last=8.40))  # the live track finishes
    out = m.release(now=8.5, live_starts=[])
    assert [r.plate for r in out] == []  # merged read is itself in its own window now
    out = m.release(now=12.0, live_starts=[])
    assert [(r.plate, r.n_reads) for r in out] == [("AB12CDE", 166)]


def test_the_hold_is_capped_so_a_long_lived_track_cannot_block_forever():
    m = merger(window_s=3.0, max_hold_s=10.0)
    m.push(mk("AB12CDF", n=3, conf=0.6, first=2.13, last=2.33))
    assert m.release(now=12.0, live_starts=[2.70]) == []  # 9.7 s since last seen: still held
    assert [r.plate for r in m.release(now=12.5, live_starts=[2.70])] == ["AB12CDF"]  # cap reached


def test_a_live_track_that_started_outside_the_window_does_not_hold_a_read():
    m = merger(window_s=3.0)
    m.push(mk("AB12CDE", n=50, conf=0.9, first=1.0, last=2.0))
    # began before the read ended, so it is not a successor
    assert [r.plate for r in m.release(now=6.0, live_starts=[0.5])] == ["AB12CDE"]


def test_a_live_track_that_started_too_late_does_not_hold_a_read():
    m = merger(window_s=3.0)
    m.push(mk("AB12CDE", n=50, conf=0.9, first=1.0, last=2.0))
    assert [r.plate for r in m.release(now=6.0, live_starts=[9.0])] == ["AB12CDE"]  # 7 s after: unrelated


def test_merge_does_not_mutate_the_inputs():
    a, b = mk("AB12CDE", 3, 0.5, 0.0, 1.0), mk("AB12CDF", 90, 0.9, 1.2, 2.0)
    m = merger()
    m.push(a)
    m.push(b)
    m.release(0.0, flush=True)
    assert (a.n_reads, a.alternatives) == (3, []) and (b.n_reads, b.alternatives) == (90, [])


# -- through the pipeline ----------------------------------------------------------


class ByCallDetector:
    def __init__(self, schedule):
        self.schedule = schedule

    def detect(self, frame_bgr):
        idx = int(frame_bgr[0, 0, 0])
        return [Detection(b, 0.9) for b in self.schedule.get(idx, [])]


class ByCallReader:
    """First `bad_calls` reads are wrong, the rest are right."""

    def __init__(self, bad_calls):
        self.bad_calls, self.calls = bad_calls, 0

    def read(self, crops):
        out = []
        for _ in crops:
            out.append(ocr("ABC1284" if self.calls < self.bad_calls else "ABC1234", 0.95))
            self.calls += 1
        return out


def frame(idx):
    img = np.full((480, 640, 3), 40, np.uint8)
    img[0, 0, 0] = idx
    return Frame(idx, 1000.0 + idx / 30, img)


def test_pipeline_turns_a_fragmented_vehicle_into_one_correct_read(cfg: Config):
    cfg.tracking.max_missed_frames = 3  # the 12-frame dropout below ends the first track
    box = Box(100, 200, 190, 230)
    # a short blurry fragment (frames 1-3), a 12-frame dropout, then the real track (16-40)
    schedule = {i: [box] for i in [*range(1, 4), *range(16, 41)]}
    got = []

    class Collect:
        def handle(self, read):
            got.append(read)

    pipe = Pipeline(cfg, ByCallDetector(schedule), ByCallReader(bad_calls=3), sinks=[Collect()])
    for i in range(1, 60):
        pipe.process(frame(i))
    pipe.finish()

    assert [r.plate for r in got] == ["ABC1234"]
    assert got[0].n_reads == 3 + 25
    assert [t for t, _ in got[0].alternatives] == ["ABC1284"]
    assert pipe.merger.merged == 1


def test_pipeline_merges_when_the_long_track_outlives_the_fragments_window(cfg: Config):
    """The failure seen on the traffic video: the car's long track is still live when the
    early fragment's merge window runs out, so without the live-successor hold they never join."""
    cfg.tracking.max_missed_frames = 3
    cfg.merge.window_s = 1.0  # 30 frames
    box = Box(100, 200, 190, 230)
    schedule = {i: [box] for i in [*range(1, 4), *range(16, 120)]}  # long track alive past frame 100
    got = []

    class Collect:
        def handle(self, read):
            got.append(read)

    pipe = Pipeline(cfg, ByCallDetector(schedule), ByCallReader(bad_calls=3), sinks=[Collect()])
    for i in range(1, 120):
        pipe.process(frame(i))
    assert got == []  # the fragment is being held, not leaked out on its own
    pipe.finish()
    assert [r.plate for r in got] == ["ABC1234"]
    assert pipe.merger.merged == 1


def test_pipeline_holds_reads_for_the_window_then_emits(cfg: Config):
    cfg.tracking.max_missed_frames = 1
    cfg.merge.window_s = 1.0  # 30 frames
    box = Box(100, 200, 190, 230)
    schedule = {i: [box] for i in range(1, 5)}
    pipe = Pipeline(cfg, ByCallDetector(schedule), ByCallReader(bad_calls=0))
    emitted_at = None
    for i in range(1, 90):
        if pipe.process(frame(i)) and emitted_at is None:
            emitted_at = i
    # plate last seen at frame 4; released once 1.0 s (30 frames) has passed
    assert emitted_at is not None and 34 <= emitted_at <= 36
