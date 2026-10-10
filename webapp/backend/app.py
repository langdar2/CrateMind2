import asyncio
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import graph
import omlx_client
import plays
import schedules
import presets
import similarity
import typesafe_client
import vuio_client

DB_PATH = os.environ.get("DB_PATH", "/data/library.db")
# ponytail: caps Jev API calls (and cost) per smart preview; raise if the
# candidate pool ever needs to be broader than the BPM/key/embedding shortlist.
MAX_SMART_CANDIDATES = 150
# How often to ask the renderers what is playing. Short enough that a 3-minute
# track is not mistaken for a skip, long enough to stay cheap.
PLAYBACK_POLL_SECONDS = 15
# Schedules are weekly, so minute-level granularity is plenty and a cheap
# query every minute keeps UI edits effective without a restart.
SCHEDULE_CHECK_SECONDS = 60


async def watch_playback():
    """Poll the renderers and persist finished listening events.

    VUIO has no "track finished" signal, so a play is inferred from the same
    URL persisting across polls. Runs for the life of the process; every
    failure is swallowed because a renderer going offline must never take the
    API down with it.
    """
    while True:
        await asyncio.sleep(PLAYBACK_POLL_SECONDS)
        try:
            status = await asyncio.to_thread(vuio_client.all_playback_status)
            event = app.state.play_tracker.observe(
                plays.current_media_id(status), time.monotonic()
            )
            if event is None:
                continue
            media_id, seconds, completed = event
            path = await asyncio.to_thread(vuio_client.path_for_media_id, media_id)
            if path:
                db.record_play(app.state.conn, path, seconds, completed)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Renderer offline, VUIO restarting, a track outside the library:
            # none of it is worth a crash, and the next poll starts clean.
            continue


def refresh_from_recipe(playlist_id: int) -> int:
    """Rebuild a playlist from its stored recipe. Returns the track count."""
    stored = db.load_recipe(app.state.conn, playlist_id)
    if stored is None:
        raise ValueError(f"kein Rezept für Playlist {playlist_id}")
    paths = [t["path"] for t in select_tracks(PreviewRequest(**stored))]
    return vuio_client.replace_playlist_tracks(playlist_id, paths)


async def run_schedules():
    """Refresh playlists whose weekly slot has come round.

    Checks on a timer rather than sleeping until the next slot, so a schedule
    edited in the UI takes effect without restarting anything, and a slot
    missed while the container was down is caught up at the next check.
    """
    while True:
        await asyncio.sleep(SCHEDULE_CHECK_SECONDS)
        try:
            now = datetime.now()
            for schedule in db.list_schedules(app.state.conn):
                if not schedules.is_due(schedule, now):
                    continue
                playlist_id = schedule["playlist_id"]
                try:
                    count = await asyncio.to_thread(refresh_from_recipe, playlist_id)
                    result = f"{count} Tracks"
                except Exception as e:
                    result = f"Fehler: {e}"
                # Recorded either way: a failing schedule must not retry in a
                # tight loop until the next slot.
                db.mark_schedule_run(app.state.conn, playlist_id, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.get_connection(DB_PATH)
    app.state.conn = conn
    app.state.tracks = db.load_ok_tracks(conn)
    # Centroids over 33k embeddings take a moment, so build them once here
    # rather than per request. Picks up new tracks whenever the container
    # restarts; the analysis service writes the DB but cannot reload us.
    app.state.graph = graph.build_index(app.state.tracks)
    app.state.play_tracker = plays.PlayTracker()
    watcher = asyncio.create_task(watch_playback())
    scheduler = asyncio.create_task(run_schedules())
    try:
        yield
    finally:
        watcher.cancel()
        scheduler.cancel()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PreviewRequest(BaseModel):
    mode: str
    prompt: Optional[str] = None
    seed_path: Optional[str] = None
    mood_prompt: Optional[str] = None
    criteria: Optional[dict] = None
    # These defaults are the behaviour, not a UI preference - a caller reaching
    # for the API directly should get the same playlist the app would build.
    # Seed mode only: 0 ranks purely by sound, 1 purely by taste.
    taste_weight: float = 0.3
    # Share of the list reserved for tracks the Apple export never scored.
    discovery: float = 0.1
    # Share reserved for recently imported music, and how long "recent" lasts.
    # Separate from discovery: that one is about music never *played*, this one
    # about music newly *owned* - a fresh import by a long-time favourite
    # artist is well-scored and still deserves to surface.
    fresh_share: float = 0.15
    fresh_days: float = 60.0
    limit: int = 30


class PlayRequest(BaseModel):
    path: str
    skipped: bool = False


class RatingRequest(BaseModel):
    path: str
    rating: int  # +1 favourite, -1 thumbs-down, 0 clears


class CreatePlaylistRequest(BaseModel):
    name: str
    track_paths: list
    # The preview request these tracks came from. Stored so the playlist can
    # be rebuilt later without the caller having to repeat the criteria.
    recipe: Optional[PreviewRequest] = None


class CastRequest(BaseModel):
    renderer_id: str


class ScheduleRequest(BaseModel):
    name: str
    weekday: int
    hour: int
    minute: int
    enabled: bool = True


@app.get("/api/stats")
def get_stats():
    return db.fetch_stats(app.state.conn)


@app.get("/api/tracks")
def search_tracks(q: str = "", limit: int = 20):
    return {"tracks": db.search_ok_tracks(app.state.conn, q, limit)}


@app.post("/api/plays")
def post_play(req: PlayRequest):
    if not any(t["path"] == req.path for t in app.state.tracks):
        raise HTTPException(status_code=404, detail=f"Track nicht gefunden: {req.path}")
    result = db.count_play(app.state.conn, req.path, req.skipped)
    # One play shifts this track's score and therefore every percentile, so
    # reload rather than patch. ponytail: a full reload per play is fine at
    # one listener and ~33k tracks (tens of ms); batch it if that changes.
    app.state.tracks = db.load_ok_tracks(app.state.conn)
    return result


@app.get("/api/ratings")
def get_ratings():
    return {"ratings": [{"path": p, "rating": r}
                        for p, r in db.load_ratings(app.state.conn).items()]}


@app.put("/api/ratings")
def put_rating(req: RatingRequest):
    if not any(t["path"] == req.path for t in app.state.tracks):
        raise HTTPException(status_code=404, detail=f"Track nicht gefunden: {req.path}")
    db.set_rating(app.state.conn, req.path, req.rating)
    # The track list is loaded once at startup and carries the percentile the
    # rating changes, so patch it in place rather than make the user restart.
    for t in app.state.tracks:
        if t["path"] == req.path:
            t["rating"] = req.rating
            t["percentile"] = db.rated_percentile(t["played_percentile"], req.rating)
            break
    return {"path": req.path, "rating": req.rating}


@app.get("/api/schedules")
def get_schedules():
    """Every scheduled playlist, with its recipe and when it next runs."""
    now = datetime.now()
    out = []
    for schedule in db.list_schedules(app.state.conn):
        playlist_id = schedule["playlist_id"]
        out.append({
            **schedule,
            "describes": schedules.describe(schedule),
            "next_run": schedules.next_occurrence(
                schedule["weekday"], schedule["hour"], schedule["minute"], now
            ).isoformat(timespec="minutes"),
            "recipe": db.load_recipe(app.state.conn, playlist_id),
        })
    return {"schedules": out}


@app.put("/api/schedules/{playlist_id}")
def put_schedule(playlist_id: int, req: ScheduleRequest):
    try:
        schedules.validate(req.weekday, req.hour, req.minute)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if db.load_recipe(app.state.conn, playlist_id) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Playlist {playlist_id} hat kein Rezept - ohne Rezept kann "
                   "sie nicht automatisch neu befüllt werden.",
        )
    # Treat the slot just gone as already served, so a new schedule waits for
    # its next real occurrence rather than firing on the next check.
    previous = schedules.previous_occurrence(
        req.weekday, req.hour, req.minute, datetime.now()
    ).timestamp()
    db.save_schedule(app.state.conn, playlist_id, req.name,
                     req.weekday, req.hour, req.minute, req.enabled,
                     starts_run_at=previous)
    return {"playlist_id": playlist_id}


@app.delete("/api/schedules/{playlist_id}")
def remove_schedule(playlist_id: int):
    if db.delete_schedule(app.state.conn, playlist_id) == 0:
        raise HTTPException(status_code=404, detail=f"Kein Zeitplan für Playlist {playlist_id}")
    return {"deleted": playlist_id}


@app.post("/api/schedules/{playlist_id}/run")
def run_schedule_now(playlist_id: int):
    """Refresh immediately, without waiting for the weekly slot."""
    try:
        count = refresh_from_recipe(playlist_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    db.mark_schedule_run(app.state.conn, playlist_id, f"{count} Tracks")
    return {"playlist_id": playlist_id, "track_count": count}


@app.get("/api/now-playing")
def now_playing():
    """What is on a renderer right now, resolved to a track.

    Uses the same detection as the play counter, so the status bar cannot
    disagree with what gets counted. Only reports casts this server knows
    about; playback started from another app may not show up.
    """
    try:
        status = vuio_client.all_playback_status()
    except vuio_client.VuioError:
        return {"playing": None}

    media_id = plays.current_media_id(status)
    if media_id is None:
        return {"playing": None}

    renderer = next(
        (r for r in status.get("renderers") or []
         if plays.media_id_from_url(r.get("current_url")) == media_id),
        {},
    )
    try:
        path = vuio_client.path_for_media_id(media_id)
    except vuio_client.VuioError:
        path = None
    return {"playing": {
        "renderer": renderer.get("friendly_name"),
        "path": path,
        "title": path.rsplit("/", 1)[-1].rsplit(".", 1)[0] if path else None,
    }}


@app.get("/api/plays")
def get_local_plays(limit: int = 50):
    return {"plays": db.fetch_local_plays(app.state.conn, limit)}


@app.get("/api/graph/artists")
def list_graph_artists():
    return {"artists": graph.list_artists(app.state.graph)}


@app.get("/api/graph/{artist}")
def get_artist_graph(artist: str, limit: int = 20):
    result = graph.neighbourhood(app.state.graph, artist.lower(), limit)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Künstler nicht gefunden: {artist}")
    return result


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


def select_tracks(req: PreviewRequest) -> list:
    """Run one playlist recipe. Shared by preview and refresh so a refreshed
    playlist is composed exactly like the preview the user approved."""
    tracks = app.state.tracks
    if not tracks:
        raise HTTPException(status_code=404, detail="Keine analysierten Tracks vorhanden")
    # A thumbs-down means "never play this", which a low taste score alone
    # would not guarantee - taste_weight 0 ignores the score entirely. Keep it
    # seedable, so rating a track still lets you ask for more like it.
    tracks = [t for t in tracks if t.get("rating", 0) >= 0 or t["path"] == req.seed_path]

    # What each mode considered suitable, so the fresh-music quota below can
    # draw from the same brief rather than from the whole library.
    fitting = tracks
    if req.mode == "manual":
        matches = presets.filter_by_criteria(tracks, req.criteria or {}, limit=req.limit,
                                             discovery=req.discovery)
        fitting = presets.filter_by_criteria(tracks, req.criteria or {},
                                             limit=len(tracks))
    elif req.mode == "prompt":
        if not req.prompt:
            raise HTTPException(status_code=400, detail="prompt fehlt")
        try:
            criteria = omlx_client.parse_prompt_to_criteria(req.prompt)
        except omlx_client.OmlxError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        matches = presets.filter_by_criteria(tracks, criteria, limit=req.limit,
                                             discovery=req.discovery)
        fitting = presets.filter_by_criteria(tracks, criteria, limit=len(tracks))
    elif req.mode == "seed":
        seed = next((t for t in tracks if t["path"] == req.seed_path), None)
        if seed is None:
            raise HTTPException(status_code=404, detail=f"Seed-Track nicht gefunden: {req.seed_path}")
        # Ask for extra, since de-duplicating and capping thin the list out.
        similar = similarity.top_similar(seed, tracks, limit=req.limit * 3,
                                         taste_weight=req.taste_weight)
        matches = presets.cap_per_artist(presets.dedupe_by_song(similar))[:req.limit]
        fitting = similar  # already ranked by closeness to the seed
    elif req.mode == "smart":
        if not req.mood_prompt:
            raise HTTPException(status_code=400, detail="mood_prompt fehlt")
        if req.seed_path:
            seed = next((t for t in tracks if t["path"] == req.seed_path), None)
            if seed is None:
                raise HTTPException(status_code=404, detail=f"Seed-Track nicht gefunden: {req.seed_path}")
            candidates = similarity.top_similar(seed, tracks, limit=MAX_SMART_CANDIDATES)
        else:
            # Without a seed there is nothing to make the shortlist relevant, so
            # send Jev the best-liked tracks rather than whatever the database
            # happens to return first - but reserve a slice for music the Apple
            # export never scored, which would otherwise never reach Jev at all.
            scored = sorted((t for t in tracks if t["score"] is not None),
                            key=lambda t: t["score"], reverse=True)
            unscored = [t for t in tracks if t["score"] is None]
            reserved = round(MAX_SMART_CANDIDATES * req.discovery)
            picks = random.sample(unscored, min(reserved, len(unscored)))
            candidates = scored[:MAX_SMART_CANDIDATES - len(picks)] + picks
        candidates = presets.cap_per_artist(presets.dedupe_by_song(candidates))
        fitting = candidates
        try:
            matches = typesafe_client.rank_by_vibe(req.mood_prompt, candidates, limit=req.limit)
        except typesafe_client.TypesafeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
    else:
        raise HTTPException(status_code=400, detail=f"Unbekannter Modus: {req.mode}")

    return presets.weave_in_fresh(matches, fitting, req.limit, req.fresh_share,
                                  req.fresh_days, time.time())


@app.post("/api/playlists/preview")
def preview_playlist(req: PreviewRequest):
    now = time.time()
    return {"tracks": [
        {
            "path": t["path"], "bpm": t["bpm"], "key": t["key"],
            "danceability": t["danceability"], "mood_happy": t["mood_happy"],
            "mood_aggressive": t["mood_aggressive"], "mood_relaxed": t["mood_relaxed"],
            "mood_party": t["mood_party"], "percentile": t.get("percentile"),
            # When the library first saw the file, plus the verdict against
            # this request's own window, so a client can badge a track as new
            # without repeating the fresh_days arithmetic.
            "first_seen": t.get("first_seen"),
            "is_new": presets.is_fresh(t, now, req.fresh_days),
        }
        for t in select_tracks(req)
    ]}


@app.post("/api/playlists")
def add_playlist(req: CreatePlaylistRequest):
    try:
        playlist_id = vuio_client.create_playlist(req.name, req.track_paths)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    if req.recipe is not None:
        db.save_recipe(app.state.conn, playlist_id, req.recipe.model_dump())
    return {"playlist_id": playlist_id}


@app.get("/api/renderers")
def list_renderers():
    try:
        return {"renderers": vuio_client.list_renderers()}
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/playlists/{playlist_id}/refresh")
def refresh_playlist(playlist_id: int, req: Optional[PreviewRequest] = None):
    """Rebuild an existing VUIO playlist.

    Without a body the recipe stored when the playlist was created is reused,
    so a scheduled refresh is a one-liner. With a body the recipe is replaced,
    and later bodyless refreshes follow the new one.

    Discovery slots are drawn fresh each run, so repeated refreshes keep
    putting unheard music in front of you without a new playlist appearing.
    """
    if req is None:
        stored = db.load_recipe(app.state.conn, playlist_id)
        if stored is None:
            raise HTTPException(
                status_code=404,
                detail=f"Kein Rezept für Playlist {playlist_id} gespeichert - "
                       "Kriterien mitschicken oder die Playlist neu anlegen.",
            )
        req = PreviewRequest(**stored)
    else:
        db.save_recipe(app.state.conn, playlist_id, req.model_dump())

    paths = [t["path"] for t in select_tracks(req)]
    try:
        count = vuio_client.replace_playlist_tracks(playlist_id, paths)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"playlist_id": playlist_id, "track_count": count}


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
