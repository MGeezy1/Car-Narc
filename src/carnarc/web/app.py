"""FastAPI dashboard and JSON API.

Security model (this app serves plate data, so it is locked down by default):
- When a token is configured, every route requires HTTP Basic auth; the password
  is the token (any username). Compared in constant time.
- The CLI refuses to bind a non-loopback address without a token.
- Mutating routes only accept JSON bodies / non-simple methods, so a page on
  another site cannot forge them through a logged-in browser.
- Snapshot paths are resolved and confined to the snapshot directory.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from .. import __version__
from ..config import Config
from ..storage import Store
from .page import INDEX_HTML


class WatchlistEntry(BaseModel):
    plate: str = Field(min_length=1, max_length=10)
    label: str = Field(default="", max_length=60)


def create_app(cfg: Config, token: str | None = None) -> FastAPI:
    store = Store(cfg.db_path)
    snapshot_root = cfg.snapshot_dir.resolve()
    basic = HTTPBasic(auto_error=False)

    def require_auth(creds: HTTPBasicCredentials | None = Depends(basic)) -> None:
        if token is None:
            return
        supplied = creds.password.encode() if creds else b""
        if not secrets.compare_digest(supplied, token.encode()):
            raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": 'Basic realm="Car Narc"'})

    app = FastAPI(title="Car Narc", version=__version__, dependencies=[Depends(require_auth)])

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/api/status")
    def status() -> dict:
        return {"version": __version__, "reads": store.count(), "watchlist": len(store.watchlist())}

    @app.get("/api/reads")
    def reads(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        plate: str | None = Query(None, max_length=10, description="plate prefix"),
    ) -> list[dict]:
        return store.recent(limit=limit, offset=offset, plate_prefix=plate)

    @app.get("/api/reads/{read_id}")
    def read_one(read_id: int) -> dict:
        row = store.get(read_id)
        if row is None:
            raise HTTPException(404, "no such read")
        return row

    @app.get("/snapshots/{rel_path:path}")
    def snapshot(rel_path: str) -> FileResponse:
        target = (snapshot_root / rel_path).resolve()
        if not target.is_relative_to(snapshot_root) or not target.is_file() or target.suffix.lower() != ".jpg":
            raise HTTPException(404, "not found")
        return FileResponse(target, media_type="image/jpeg")

    @app.get("/api/watchlist")
    def watchlist() -> list[dict]:
        return store.watchlist()

    @app.post("/api/watchlist", status_code=201)
    def watchlist_add(entry: WatchlistEntry) -> dict:
        try:
            plate = store.watchlist_add(entry.plate, entry.label)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"plate": plate, "label": entry.label.strip()}

    @app.delete("/api/watchlist/{plate}", status_code=204)
    def watchlist_remove(plate: str) -> Response:
        if not store.watchlist_remove(plate):
            raise HTTPException(404, "not on watchlist")
        return Response(status_code=204)

    return app


def is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}
