"""SQLite storage for reads and the watchlist, plus snapshot files.

WAL mode lets the capture process write while the web dashboard reads.
A connection is opened per call, which is cheap for SQLite and keeps the
class safe to share across threads.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import cv2

from .config import Config
from .models import PlateRead
from .plates import normalize

SCHEMA = """
CREATE TABLE IF NOT EXISTS reads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    plate         TEXT    NOT NULL,
    confidence    REAL    NOT NULL,
    n_reads       INTEGER NOT NULL,
    alternatives  TEXT    NOT NULL DEFAULT '[]',
    snapshot      TEXT,
    crop          TEXT,
    watchlist_hit INTEGER NOT NULL DEFAULT 0   -- 0 none, 1 exact, 2 near (1 char off)
);
CREATE INDEX IF NOT EXISTS idx_reads_ts    ON reads(ts);
CREATE INDEX IF NOT EXISTS idx_reads_plate ON reads(plate);

CREATE TABLE IF NOT EXISTS watchlist (
    plate    TEXT PRIMARY KEY,
    label    TEXT NOT NULL DEFAULT '',
    added_ts REAL NOT NULL
);
"""

HIT_NONE, HIT_EXACT, HIT_NEAR = 0, 1, 2


def _one_char_off(a: str, b: str) -> bool:
    """True if a and b have the same length and differ in exactly one position."""
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


class Store:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commit / rollback
                yield conn
        finally:
            conn.close()

    # -- reads -----------------------------------------------------------------

    def add_read(self, read: PlateRead, snapshot: str | None = None, crop: str | None = None) -> dict[str, Any]:
        hit = self.watchlist_match(read.plate)
        alts = json.dumps([[t, round(w, 4)] for t, w in read.alternatives])
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO reads (ts, plate, confidence, n_reads, alternatives, snapshot, crop, watchlist_hit)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (read.last_ts, read.plate, read.confidence, read.n_reads, alts, snapshot, crop, hit),
            )
            rid = cur.lastrowid
        row = self.get(int(rid))
        assert row is not None
        return row

    def set_snapshots(self, read_id: int, snapshot: str | None, crop: str | None) -> None:
        with self._conn() as c:
            c.execute("UPDATE reads SET snapshot=?, crop=? WHERE id=?", (snapshot, crop, read_id))

    def get(self, read_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM reads WHERE id=?", (read_id,)).fetchone()
        return self._read_dict(row) if row else None

    def recent(self, limit: int = 50, offset: int = 0, plate_prefix: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        sql, args = "SELECT * FROM reads", []
        if plate_prefix:
            sql += " WHERE plate LIKE ? ESCAPE '\\'"
            safe = normalize(plate_prefix)  # alnum only, so no LIKE wildcards can sneak in
            args.append(safe + "%")
        sql += " ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?"
        args += [limit, max(0, int(offset))]
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [self._read_dict(r) for r in rows]

    def count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM reads").fetchone()[0])

    @staticmethod
    def _read_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["alternatives"] = json.loads(d["alternatives"])
        return d

    # -- watchlist ---------------------------------------------------------------

    def watchlist_add(self, plate: str, label: str = "") -> str:
        p = normalize(plate)
        if not p:
            raise ValueError("plate must contain letters or digits")
        with self._conn() as c:
            c.execute(
                "INSERT INTO watchlist (plate, label, added_ts) VALUES (?,?,?)"
                " ON CONFLICT(plate) DO UPDATE SET label=excluded.label",
                (p, label.strip(), time.time()),
            )
        return p

    def watchlist_remove(self, plate: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM watchlist WHERE plate=?", (normalize(plate),))
            return cur.rowcount > 0

    def watchlist(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM watchlist ORDER BY plate").fetchall()
        return [dict(r) for r in rows]

    def watchlist_match(self, plate: str) -> int:
        """HIT_EXACT, HIT_NEAR (same length, one character off), or HIT_NONE.

        Near matches exist because one misread character is the most common OCR
        failure, and it would otherwise hide exactly the plates you care about.
        """
        p = normalize(plate)
        entries = [e["plate"] for e in self.watchlist()]
        if p in entries:
            return HIT_EXACT
        if any(_one_char_off(p, e) for e in entries):
            return HIT_NEAR
        return HIT_NONE


class SnapshotWriter:
    """Writes the best frame (with the plate boxed) and the plate crop as JPEGs."""

    def __init__(self, cfg: Config):
        self.root = cfg.snapshot_dir
        self.quality = cfg.storage.jpeg_quality

    def save(self, read: PlateRead, read_id: int) -> tuple[str, str]:
        day = time.strftime("%Y-%m-%d", time.localtime(read.last_ts))
        stamp = time.strftime("%H%M%S", time.localtime(read.last_ts))
        folder = self.root / day
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{stamp}_{read_id}_{read.plate}"
        params = [cv2.IMWRITE_JPEG_QUALITY, self.quality]

        frame = read.frame.copy()  # draw on a copy; the original is shared with the pipeline
        b = read.box
        cv2.rectangle(frame, (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2)), (0, 255, 0), 3)
        frame_rel = f"{day}/{stem}.jpg"
        crop_rel = f"{day}/{stem}_plate.jpg"
        if not cv2.imwrite(str(self.root / frame_rel), frame, params):
            raise OSError(f"failed to write {frame_rel}")
        if not cv2.imwrite(str(self.root / crop_rel), read.crop, params):
            raise OSError(f"failed to write {crop_rel}")
        return frame_rel, crop_rel
