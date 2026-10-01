import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import omlx_client
import presets
import similarity
import typesafe_client
import vuio_client

DB_PATH = os.environ.get("DB_PATH", "/data/library.db")
# ponytail: caps Jev API calls (and cost) per smart preview; raise if the
# candidate pool ever needs to be broader than the BPM/key/embedding shortlist.
MAX_SMART_CANDIDATES = 150


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
    prompt: Optional[str] = None
    seed_path: Optional[str] = None
    mood_prompt: Optional[str] = None
    criteria: Optional[dict] = None
    limit: int = 30


class CreatePlaylistRequest(BaseModel):
    name: str
    track_paths: list


class CastRequest(BaseModel):
    renderer_id: str


@app.get("/api/stats")
def get_stats():
    return db.fetch_stats(app.state.conn)


@app.get("/api/tracks")
def search_tracks(q: str = "", limit: int = 20):
    return {"tracks": db.search_ok_tracks(app.state.conn, q, limit)}


@app.get("/api/tracks/recent")
def get_recent_tracks(limit: int = 10):
    return {"tracks": db.recent_ok_tracks(app.state.conn, limit)}


@app.get("/api/tracks/failed")
def get_failed_tracks(q: str = "", limit: int = 50, offset: int = 0):
    return db.search_failed_tracks(app.state.conn, query=q, limit=limit, offset=offset)


@app.post("/api/tracks/retry-failed")
def retry_failed_tracks():
    count = db.retry_failed_tracks(app.state.conn)
    return {"retried": count}


@app.post("/api/playlists/preview")
def preview_playlist(req: PreviewRequest):
    tracks = app.state.tracks
    if not tracks:
        raise HTTPException(status_code=404, detail="Keine analysierten Tracks vorhanden")

    if req.mode == "manual":
        matches = presets.filter_by_criteria(tracks, req.criteria or {}, limit=req.limit)
    elif req.mode == "prompt":
        if not req.prompt:
            raise HTTPException(status_code=400, detail="prompt fehlt")
        try:
            criteria = omlx_client.parse_prompt_to_criteria(req.prompt)
        except omlx_client.OmlxError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        matches = presets.filter_by_criteria(tracks, criteria, limit=req.limit)
    elif req.mode == "seed":
        seed = next((t for t in tracks if t["path"] == req.seed_path), None)
        if seed is None:
            raise HTTPException(status_code=404, detail=f"Seed-Track nicht gefunden: {req.seed_path}")
        matches = similarity.top_similar(seed, tracks, limit=req.limit)
    elif req.mode == "smart":
        if not req.mood_prompt:
            raise HTTPException(status_code=400, detail="mood_prompt fehlt")
        if req.seed_path:
            seed = next((t for t in tracks if t["path"] == req.seed_path), None)
            if seed is None:
                raise HTTPException(status_code=404, detail=f"Seed-Track nicht gefunden: {req.seed_path}")
            candidates = similarity.top_similar(seed, tracks, limit=MAX_SMART_CANDIDATES)
        else:
            candidates = tracks[:MAX_SMART_CANDIDATES]
        try:
            matches = typesafe_client.rank_by_vibe(req.mood_prompt, candidates, limit=req.limit)
        except typesafe_client.TypesafeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
    else:
        raise HTTPException(status_code=400, detail=f"Unbekannter Modus: {req.mode}")

    return {"tracks": [
        {
            "path": t["path"], "bpm": t["bpm"], "key": t["key"],
            "danceability": t["danceability"], "mood_happy": t["mood_happy"],
            "mood_aggressive": t["mood_aggressive"], "mood_relaxed": t["mood_relaxed"],
            "mood_party": t["mood_party"],
        }
        for t in matches
    ]}


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
