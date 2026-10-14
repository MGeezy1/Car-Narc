"""Where finished plate reads go.

A sink is anything with handle(read). The pipeline calls every sink for each
finished read, and one failing sink never stops the others.
"""

from __future__ import annotations

import logging
from typing import Protocol

from .models import PlateRead
from .storage import HIT_EXACT, HIT_NEAR, SnapshotWriter, Store

log = logging.getLogger(__name__)


class Sink(Protocol):
    def handle(self, read: PlateRead) -> None: ...


class LogSink:
    def handle(self, read: PlateRead) -> None:
        alts = ", ".join(f"{t} ({w:.0%})" for t, w in read.alternatives)
        log.info(
            "PLATE %s  conf=%.2f  reads=%d%s",
            read.plate,
            read.confidence,
            read.n_reads,
            f"  alt: {alts}" if alts else "",
        )


class StoreSink:
    """Saves the read to SQLite and (optionally) writes snapshots."""

    def __init__(self, store: Store, snapshots: SnapshotWriter | None):
        self.store = store
        self.snapshots = snapshots

    def handle(self, read: PlateRead) -> None:
        row = self.store.add_read(read)
        if self.snapshots is not None:
            try:
                frame_rel, crop_rel = self.snapshots.save(read, row["id"])
                self.store.set_snapshots(row["id"], frame_rel, crop_rel)
            except OSError:
                log.exception("could not write snapshots for read %s", row["id"])
        if row["watchlist_hit"] == HIT_EXACT:
            log.warning("WATCHLIST HIT: %s", read.plate)
        elif row["watchlist_hit"] == HIT_NEAR:
            log.warning("WATCHLIST NEAR-MATCH (1 char off): %s", read.plate)
