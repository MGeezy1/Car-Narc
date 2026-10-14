import numpy as np
import pytest

from carnarc.models import Box, PlateRead
from carnarc.storage import HIT_EXACT, HIT_NEAR, HIT_NONE, SnapshotWriter, Store


def make_read(plate="ABC1234", ts=1_700_000_000.0, conf=0.9) -> PlateRead:
    frame = np.full((120, 200, 3), 90, np.uint8)
    crop = np.full((20, 60, 3), 200, np.uint8)
    return PlateRead(1, plate, conf, 5, ts - 1, ts, Box(10, 10, 70, 30), crop, frame, [("ABC1284", 0.12)])


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "t.db")


def test_add_and_get_round_trip(store):
    row = store.add_read(make_read())
    assert row["plate"] == "ABC1234"
    assert row["alternatives"] == [["ABC1284", 0.12]]
    assert store.get(row["id"])["n_reads"] == 5
    assert store.get(9999) is None
    assert store.count() == 1


def test_recent_is_newest_first_and_paginates(store):
    for i in range(5):
        store.add_read(make_read(plate=f"CAR{i}000", ts=1_700_000_000.0 + i))
    plates = [r["plate"] for r in store.recent(limit=3)]
    assert plates == ["CAR4000", "CAR3000", "CAR2000"]
    assert [r["plate"] for r in store.recent(limit=3, offset=3)] == ["CAR1000", "CAR0000"]


def test_prefix_filter_and_wildcard_safety(store):
    store.add_read(make_read("ABC1234"))
    store.add_read(make_read("XYZ9999"))
    assert [r["plate"] for r in store.recent(plate_prefix="abc")] == ["ABC1234"]
    # Input is reduced to A-Z/0-9 before it reaches LIKE, so wildcards are inert:
    assert [r["plate"] for r in store.recent(plate_prefix="A%")] == ["ABC1234"]  # behaves as "A"
    assert [r["plate"] for r in store.recent(plate_prefix="_BC")] == []  # "_" is not a one-char wildcard
    assert len(store.recent(plate_prefix="%")) == 2  # nothing left after stripping = no filter


def test_watchlist_exact_near_and_none(store):
    store.watchlist_add("abc-1234", "red truck")
    assert store.watchlist()[0]["plate"] == "ABC1234"
    assert store.watchlist_match("ABC1234") == HIT_EXACT
    assert store.watchlist_match("ABC1284") == HIT_NEAR  # one char off
    assert store.watchlist_match("ABC12345") == HIT_NONE  # different length is not "near"
    assert store.watchlist_match("XYZ9999") == HIT_NONE
    assert store.watchlist_match("ABX1284") == HIT_NONE  # two chars off


def test_watchlist_hit_is_recorded_on_the_read(store):
    store.watchlist_add("ABC1234")
    assert store.add_read(make_read("ABC1234"))["watchlist_hit"] == HIT_EXACT
    assert store.add_read(make_read("ABC1235"))["watchlist_hit"] == HIT_NEAR
    assert store.add_read(make_read("ZZZ0000"))["watchlist_hit"] == HIT_NONE


def test_watchlist_add_updates_label_and_remove(store):
    store.watchlist_add("ABC1234", "old")
    store.watchlist_add("ABC1234", "new")
    assert store.watchlist()[0]["label"] == "new"
    assert store.watchlist_remove("abc1234") is True
    assert store.watchlist_remove("ABC1234") is False
    with pytest.raises(ValueError):
        store.watchlist_add("---")


def test_snapshot_writer_boxes_a_copy_not_the_original(cfg):
    read = make_read()
    before = read.frame.copy()
    frame_rel, crop_rel = SnapshotWriter(cfg).save(read, 7)
    assert (cfg.snapshot_dir / frame_rel).is_file()
    assert (cfg.snapshot_dir / crop_rel).is_file()
    assert "7_ABC1234" in frame_rel
    assert np.array_equal(read.frame, before)  # the shared frame is untouched
