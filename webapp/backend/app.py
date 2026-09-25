import os
from contextlib import asynccontextmanager
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.get_connection(DB_PATH)
    app.state.conn = conn
    app.state.tracks = db.load_ok_tracks(conn)
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PreviewRequest(BaseModel):
    mode: str
    preset_name: Optional[str] = None
    seed_path: Optional[str] = None
    limit: int = 30


class CreatePlaylistRequest(BaseModel):
    name: str
    track_paths: list


class CastRequest(BaseModel):
    renderer_id: str


@app.get("/api/stats")
def get_stats():
    return db.fetch_stats(app.state.conn)


@app.get("/api/presets")
def get_presets():
    return presets.PRESETS


@app.get("/api/tracks")
def search_tracks(q: str = "", limit: int = 20):
    return {"tracks": db.search_ok_tracks(app.state.conn, q, limit)}


@app.get("/api/tracks/failed")
def get_failed_tracks(q: str = "", limit: int = 50, offset: int = 0):
    return db.search_failed_tracks(app.state.conn, query=q, limit=limit, offset=offset)


@app.post("/api/playlists/preview")
def preview_playlist(req: PreviewRequest):
    tracks = app.state.tracks
    if not tracks:
        raise HTTPException(status_code=404, detail="Keine analysierten Tracks vorhanden")

    if req.mode == "preset":
        if req.preset_name not in presets.PRESETS:
            raise HTTPException(status_code=400, detail=f"Unbekanntes Preset: {req.preset_name}")
        matches = presets.filter_tracks(tracks, req.preset_name, limit=req.limit)
    elif req.mode == "seed":
        seed = next((t for t in tracks if t["path"] == req.seed_path), None)
        if seed is None:
            raise HTTPException(status_code=404, detail=f"Seed-Track nicht gefunden: {req.seed_path}")
        matches = similarity.top_similar(seed, tracks, limit=req.limit)
    else:
        raise HTTPException(status_code=400, detail=f"Unbekannter Modus: {req.mode}")

    return {"tracks": [{"path": t["path"], "bpm": t["bpm"], "key": t["key"]} for t in matches]}


@app.post("/api/playlists")
def add_playlist(req: CreatePlaylistRequest):
    try:
        playlist_id = vuio_client.create_playlist(req.name, req.track_paths)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"playlist_id": playlist_id}


@app.get("/api/renderers")
def list_renderers():
    try:
        return {"renderers": vuio_client.list_renderers()}
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/playlists/{playlist_id}/cast")
def cast_playlist(playlist_id: int, req: CastRequest):
    try:
        return vuio_client.cast_playlist(playlist_id, req.renderer_id)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/playback-status")
def playback_status(renderer_id: Optional[str] = None):
    try:
        return vuio_client.get_playback_status(renderer_id)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
