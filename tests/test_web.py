import base64

import numpy as np
import pytest
from fastapi.testclient import TestClient

from carnarc.models import Box, PlateRead
from carnarc.storage import SnapshotWriter, Store
from carnarc.web.app import create_app, is_loopback


def basic(password: str, user: str = "me") -> dict[str, str]:
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.fixture
def seeded(cfg):
    store = Store(cfg.db_path)
    frame = np.full((100, 160, 3), 80, np.uint8)
    crop = np.full((20, 50, 3), 200, np.uint8)
    read = PlateRead(1, "ABC1234", 0.93, 4, 99.0, 100.0, Box(5, 5, 55, 25), crop, frame, [])
    row = store.add_read(read)
    frame_rel, crop_rel = SnapshotWriter(cfg).save(read, row["id"])
    store.set_snapshots(row["id"], frame_rel, crop_rel)
    return cfg, store.get(row["id"])  # re-fetch: `row` predates the snapshot paths


def test_open_when_no_token(seeded):
    cfg, row = seeded
    c = TestClient(create_app(cfg))
    assert c.get("/").status_code == 200
    assert "Car Narc" in c.get("/").text
    assert c.get("/api/status").json()["reads"] == 1
    reads = c.get("/api/reads").json()
    assert reads[0]["plate"] == "ABC1234"
    assert c.get(f"/api/reads/{row['id']}").json()["plate"] == "ABC1234"
    assert c.get("/api/reads/999").status_code == 404


def test_token_required_on_every_route(seeded):
    cfg, row = seeded
    c = TestClient(create_app(cfg, token="s3cret"))
    for path in ("/", "/api/status", "/api/reads", "/api/watchlist", f"/snapshots/{row['snapshot']}"):
        r = c.get(path)
        assert r.status_code == 401, path
        assert r.headers["www-authenticate"].startswith("Basic")
    assert c.get("/api/status", headers=basic("wrong")).status_code == 401
    assert c.get("/api/status", headers=basic("s3cret")).status_code == 200
    assert c.get("/api/status", headers=basic("s3cret", user="anyone")).status_code == 200
    assert c.post("/api/watchlist", json={"plate": "X1"}).status_code == 401


def test_snapshots_are_served_and_confined(seeded):
    cfg, row = seeded
    c = TestClient(create_app(cfg))
    r = c.get(f"/snapshots/{row['crop']}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    # traversal attempts, raw and percent-encoded
    assert c.get("/snapshots/../carnarc.db").status_code == 404
    assert c.get("/snapshots/%2e%2e/carnarc.db").status_code == 404
    assert c.get("/snapshots/..%2fcarnarc.db").status_code == 404
    assert c.get("/snapshots/nope.jpg").status_code == 404


def test_only_jpgs_are_served_from_the_snapshot_dir(seeded):
    cfg, _ = seeded
    (cfg.snapshot_dir / "notes.txt").write_text("not an image")
    c = TestClient(create_app(cfg))
    assert c.get("/snapshots/notes.txt").status_code == 404


def test_watchlist_crud(seeded):
    cfg, _ = seeded
    c = TestClient(create_app(cfg))
    r = c.post("/api/watchlist", json={"plate": "abc-9999", "label": "blue van"})
    assert r.status_code == 201 and r.json()["plate"] == "ABC9999"
    assert c.get("/api/watchlist").json()[0]["label"] == "blue van"
    assert c.delete("/api/watchlist/ABC9999").status_code == 204
    assert c.delete("/api/watchlist/ABC9999").status_code == 404
    assert c.post("/api/watchlist", json={"plate": "---"}).status_code == 422


def test_watchlist_rejects_non_json_bodies(seeded):
    """Form-encoded POSTs (what a cross-site <form> can send) must not be accepted."""
    cfg, _ = seeded
    c = TestClient(create_app(cfg))
    r = c.post("/api/watchlist", data={"plate": "ABC9999"})
    assert r.status_code == 422
    assert c.get("/api/watchlist").json() == []


def test_query_limits_are_enforced(seeded):
    cfg, _ = seeded
    c = TestClient(create_app(cfg))
    assert c.get("/api/reads?limit=0").status_code == 422
    assert c.get("/api/reads?limit=501").status_code == 422
    assert c.get("/api/reads?offset=-1").status_code == 422


def test_is_loopback():
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("localhost")
    assert not is_loopback("0.0.0.0") and not is_loopback("100.64.0.5")
