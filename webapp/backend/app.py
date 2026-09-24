import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import presets
import similarity
import vuio_client

DB_PATH = os.environ.get("DB_PATH", "/data/library.db")
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.get_connection(DB_PATH)
    app.state.db_conn = conn
    app.state.tracks = db.load_ok_tracks(conn)
    try:
        yield
    finally:
        conn.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _strip_embedding(track: dict) -> dict:
    copy = dict(track)
    copy.pop("embedding", None)
    return copy


class PlaylistPreviewRequest(BaseModel):
    preset: Optional[str] = None
    seed_path: Optional[str] = None


class CreatePlaylistRequest(BaseModel):
    name: str
    paths: list[str]


class CastRequest(BaseModel):
    renderer_id: str


@app.get("/api/stats")
async def get_stats():
    return db.fetch_stats(app.state.db_conn)


@app.get("/api/presets")
async def get_presets():
    return {"presets": list(presets.PRESETS.keys())}


@app.get("/api/tracks")
async def get_tracks(q: Optional[str] = None, limit: Optional[int] = None):
    if q:
        tracks = db.search_ok_tracks(app.state.db_conn, q, limit or 20)
    else:
        tracks = app.state.tracks[: (limit or 20)]
    return [_strip_embedding(t) for t in tracks]


@app.post("/api/playlists/preview")
async def preview_playlist(request: PlaylistPreviewRequest):
    if (request.preset is None) == (request.seed_path is None):
        raise HTTPException(400, "must provide exactly one of preset or seed_path")

    if request.preset is not None:
        try:
            tracks = presets.filter_tracks(app.state.tracks, request.preset, limit=30)
        except KeyError:
            raise HTTPException(400, f"unknown preset: {request.preset}")
    else:
        seed = next((t for t in app.state.tracks if t["path"] == request.seed_path), None)
        if seed is None:
            raise HTTPException(404, "seed track not found")
        tracks = similarity.top_similar(seed, app.state.tracks, limit=30)

    return {"tracks": [_strip_embedding(t) for t in tracks]}


@app.post("/api/playlists")
async def create_playlist(request: CreatePlaylistRequest):
    try:
        file_ids = []
        for path in request.paths:
            file_id = vuio_client.find_file_id(Path(path).stem)
            if file_id is not None:
                file_ids.append(file_id)

        playlist_id = vuio_client.create_playlist(request.name)
        if file_ids:
            vuio_client.add_tracks(playlist_id, file_ids)
    except vuio_client.VuioError as e:
        raise HTTPException(502, str(e))

    return {"playlist_id": playlist_id, "matched": len(file_ids), "total": len(request.paths)}


@app.get("/api/renderers")
async def get_renderers():
    try:
        renderers = vuio_client.list_renderers()
    except vuio_client.VuioError as e:
        raise HTTPException(502, str(e))
    return {"renderers": renderers}


@app.post("/api/playlists/{playlist_id}/cast")
async def cast_playlist(playlist_id: int, request: CastRequest):
    try:
        vuio_client.cast_playlist(playlist_id, request.renderer_id)
    except vuio_client.VuioError as e:
        raise HTTPException(502, str(e))
    return {"status": "casting"}


@app.get("/api/playback-status")
async def playback_status(renderer_id: Optional[str] = None):
    try:
        return vuio_client.get_playback_status(renderer_id)
    except vuio_client.VuioError as e:
        raise HTTPException(502, str(e))


if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
