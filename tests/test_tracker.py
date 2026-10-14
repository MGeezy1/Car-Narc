from carnarc.config import PlateRulesConfig, TrackingConfig
from carnarc.models import Box
from carnarc.tracker import PlateTracker, vote

from conftest import make_obs, ocr


def box_at(x: float, y: float = 200, w: float = 80, h: float = 30) -> Box:
    return Box(x, y, x + w, y + h)


# -- vote ------------------------------------------------------------------------


def test_vote_empty_returns_none():
    assert vote([]) is None
    assert vote([ocr("")]) is None


def test_vote_corrects_a_single_bad_read():
    reads = [
        ocr("ABC1234", 0.97),
        ocr("ABC1234", 0.95),
        # one blurry frame misread the B as 8, with lower confidence on that character
        ocr("A8C1234", [0.95, 0.40, 0.9, 0.9, 0.9, 0.9, 0.9]),
        ocr("ABC1234", 0.93),
    ]
    v = vote(reads)
    assert v.plate == "ABC1234"
    assert v.confidence > 0.8
    assert v.alternatives[0][0] == "A8C1234"  # the dissenting read is surfaced, not hidden


def test_vote_prefers_heavier_length_group():
    reads = [ocr("XYZ789", 0.95), ocr("XYZ789", 0.94), ocr("XYZ7890", 0.5)]
    v = vote(reads)
    assert v.plate == "XYZ789"
    assert v.n_reads == 2


def test_vote_confidence_drops_with_disagreement():
    agree = vote([ocr("ABC1234", 0.9)] * 3)
    split = vote([ocr("ABC1234", 0.9), ocr("ABC1284", 0.9), ocr("ABC1234", 0.9), ocr("ABD1284", 0.9)])
    assert agree.confidence > split.confidence


def test_vote_single_read_is_allowed_by_vote_itself():
    v = vote([ocr("ABC1234", 0.9)])
    assert v.plate == "ABC1234"
    assert v.n_reads == 1


def test_vote_ignores_reads_with_mismatched_confidence_length():
    bad = ocr("ABC1234", [0.9, 0.9])  # malformed: 2 confidences for 7 chars
    assert vote([bad]) is None


# -- tracker ---------------------------------------------------------------------


def make_tracker(**overrides) -> PlateTracker:
    t = TrackingConfig(**{"max_missed_frames": 3, "min_reads": 2, **overrides})
    return PlateTracker(t, PlateRulesConfig())


def test_follows_moving_plate_and_emits_one_read_after_it_leaves():
    tr = make_tracker()
    emitted = []
    for i in range(1, 7):
        emitted += tr.update([make_obs(i, box_at(100 + 10 * i), "ABC1234")], i)
    assert emitted == []  # still in view
    for i in range(7, 12):
        emitted += tr.update([], i)
    assert len(emitted) == 1
    assert emitted[0].plate == "ABC1234"
    assert emitted[0].n_reads == 6
    assert len(tr.tracks) == 0


def test_fast_jump_with_zero_overlap_still_associates():
    tr = make_tracker()
    # moves 120px per frame (more than 1.5 plate widths): consecutive boxes never overlap
    for i in range(1, 5):
        tr.update([make_obs(i, box_at(20 + 120 * i), "QRS5678")], i)
    assert len(tr.tracks) == 1
    assert len(tr.tracks[0].reads) == 4


def test_two_plates_make_two_tracks():
    tr = make_tracker()
    for i in range(1, 5):
        tr.update(
            [
                make_obs(i, box_at(50 + 5 * i, y=100), "AAA1111"),
                make_obs(i, box_at(400 - 5 * i, y=350), "BBB2222"),
            ],
            i,
        )
    assert len(tr.tracks) == 2
    out = tr.flush()
    assert sorted(r.plate for r in out) == ["AAA1111", "BBB2222"]


def test_flush_finalizes_open_tracks():
    tr = make_tracker()
    for i in range(1, 4):
        tr.update([make_obs(i, box_at(100), "ABC1234")], i)
    out = tr.flush()
    assert [r.plate for r in out] == ["ABC1234"]
    assert tr.tracks == []


def test_too_few_reads_is_dropped():
    tr = make_tracker(min_reads=3)
    tr.update([make_obs(1, box_at(100), "ABC1234")], 1)
    tr.update([make_obs(2, box_at(110), "ABC1234")], 2)
    assert tr.flush() == []
    assert tr.dropped_short == 1


def test_implausible_length_is_dropped():
    tr = make_tracker()
    for i in range(1, 4):
        tr.update([make_obs(i, box_at(100), "AB")], i)  # min_length default is 5
    assert tr.flush() == []
    assert tr.dropped_implausible == 1


def test_low_confidence_is_dropped():
    tr = PlateTracker(TrackingConfig(min_reads=2), PlateRulesConfig(min_confidence=0.9))
    for i in range(1, 4):
        tr.update([make_obs(i, box_at(100), "ABC1234", conf=0.6)], i)
    assert tr.flush() == []


def test_best_snapshot_comes_from_the_most_confident_read():
    tr = make_tracker()
    tr.update([make_obs(1, box_at(100), "ABC1234", conf=0.5)], 1)
    tr.update([make_obs(2, box_at(110), "ABC1234", conf=0.99)], 2)
    tr.update([make_obs(3, box_at(120), "ABC1234", conf=0.6)], 3)
    out = tr.flush()[0]
    assert out.box == box_at(110)


def test_empty_ocr_text_keeps_box_tracking_but_adds_no_read():
    tr = make_tracker()
    tr.update([make_obs(1, box_at(100), "ABC1234")], 1)
    tr.update([make_obs(2, box_at(110), "")], 2)  # OCR failed, detection still there
    tr.update([make_obs(3, box_at(120), "ABC1234")], 3)
    assert len(tr.tracks) == 1
    assert len(tr.tracks[0].reads) == 2
