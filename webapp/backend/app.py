import asyncio
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
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
import wishlist

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
# The analysis service rescans every 30 minutes, so checking every couple of
# minutes picks up new music promptly without polling for nothing.
LIBRARY_CHECK_SECONDS = 120


def reload_library():
    """Re-read the analysed tracks and rebuild the artist graph from them."""
    app.state.tracks = db.load_ok_tracks(app.state.conn)
    app.state.graph = graph.build_index(app.state.tracks)
    app.state.library_fingerprint = db.library_fingerprint(app.state.conn)


async def watch_library():
    """Pick up tracks the analysis service has added since startup.

    The analysis container writes the database on its own schedule and has no
    way to tell us, so new music used to stay invisible until the webapp was
    restarted. Reloading costs ~140ms, the change check 2ms, hence the
    fingerprint rather than an unconditional reload.
    """
    while True:
        await asyncio.sleep(LIBRARY_CHECK_SECONDS)
        try:
            current = await asyncio.to_thread(db.library_fingerprint, app.state.conn)
            if current != app.state.library_fingerprint:
                await asyncio.to_thread(reload_library)
        except asyncio.CancelledError:
            raise
        except Exception:
            continue


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
    tracks = select_tracks(PreviewRequest(**stored))
    count = vuio_client.replace_playlist_tracks(playlist_id, [t["path"] for t in tracks])
    # New tracks deserve a new blurb. VUIO cannot be told about it - there is
    # no tool to change a playlist's description - so ours is the only copy
    # that stays true after a refresh.
    description = omlx_client.suggest_playlist_description(tracks)
    if description:
        db.save_description(app.state.conn, playlist_id, description)
    return count


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
    saved = db.load_settings(conn, "llm.")
    omlx_client.set_config(saved.get("base_url"), saved.get("model"), saved.get("api_key"))
    # Centroids over 33k embeddings are cheap but not free, so the track list
    # and the artist graph are held in memory and refreshed by watch_library
    # when the analysis service adds something.
    reload_library()
    app.state.play_tracker = plays.PlayTracker()
    watcher = asyncio.create_task(watch_playback())
    scheduler = asyncio.create_task(run_schedules())
    librarian = asyncio.create_task(watch_library())
    try:
        yield
    finally:
        watcher.cancel()
        scheduler.cancel()
        librarian.cancel()


app = FastAPI(lifespan=lifespan)


class LlmConfigRequest(BaseModel):
    base_url: str
    model: str
    # None or empty keeps the stored key, so the masked field can be saved untouched.
    api_key: Optional[str] = None


class LlmTestRequest(BaseModel):
    base_url: str
    model: Optional[str] = None
    api_key: Optional[str] = None


def _mask(key: str) -> str:
    return "" if not key else (key[:5] + "…" + key[-3:] if len(key) > 10 else "…")


@app.get("/api/llm/config")
def get_llm_config():
    cfg = omlx_client.get_config()
    return {"base_url": cfg["base_url"], "model": cfg["model"],
            "has_key": bool(cfg["api_key"]), "key_hint": _mask(cfg["api_key"])}


@app.put("/api/llm/config")
def put_llm_config(req: LlmConfigRequest):
    if not req.base_url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Adresse muss mit http:// oder https:// beginnen")
    if not req.model.strip():
        raise HTTPException(status_code=400, detail="Modell fehlt")
    values = {"base_url": req.base_url.strip().rstrip("/"), "model": req.model.strip()}
    if req.api_key:
        values["api_key"] = req.api_key.strip()
    omlx_client.set_config(**values)
    db.save_settings(app.state.conn, "llm.", values)
    return get_llm_config()


@app.post("/api/llm/test")
def test_llm(req: LlmTestRequest):
    """List the server's models with the given (or stored) key, and, when a model is named, run one tiny completion."""
    key = req.api_key or omlx_client.get_config()["api_key"]
    result = {"models": [], "ok": False, "answer": None, "error": None}
    try:
        result["models"] = omlx_client.list_models(req.base_url, key)
        if req.model:
            result["answer"] = omlx_client.test_completion(req.base_url, key, req.model)
        result["ok"] = True
    except omlx_client.OmlxError as e:
        result["error"] = str(e)
    return result
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PreviewRequest(BaseModel):
    mode: str
    prompt: Optional[str] = None
    seed_path: Optional[str] = None
    mood_prompt: Optional[str] = None
    criteria: Optional[dict] = None
    # Graph mode: the artists of a neighbourhood, and how many tracks each.
    artists: Optional[list] = None
    per_artist: int = 3
    # Wishlist mode: "Artist - Title" lines the playlist must contain.
    wishes: Optional[list] = None
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
    # Left out, the local model writes one from the tracks.
    description: Optional[str] = None


class CastRequest(BaseModel):
    renderer_id: str


class GraphPlaylistRequest(BaseModel):
    artists: list
    # Lower than the usual cap: a neighbourhood is already a handful of
    # artists, so five each would let one of them dominate.
    per_artist: int = 3
    limit: int = 30


class WishlistRequest(BaseModel):
    # One song per line, "Artist - Title"; pasted lists are taken as they come.
    text: str
    limit: int = 50


class SuggestNameRequest(BaseModel):
    track_paths: list


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
    # reload rather than patch - and go through reload_library so the artist
    # graph sees the new percentiles too, which it did not before.
    # ponytail: a full reload per play is fine at one listener and ~33k
    # tracks (~140ms); batch it if that changes.
    reload_library()
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
            "description": db.load_description(app.state.conn, playlist_id),
        })
    return {"schedules": out}


@app.get("/api/schedules/candidates")
def schedule_candidates():
    """Playlists that could get a schedule but do not have one yet.

    A playlist without a stored recipe is unusable here - there would be
    nothing to rebuild it from - so those are left out rather than offered
    and then rejected on save.
    """
    try:
        playlists = vuio_client.list_playlists()
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    scheduled = {s["playlist_id"] for s in db.list_schedules(app.state.conn)}
    return {"candidates": [
        {"playlist_id": p["id"], "name": p["name"] or f"Playlist {p['id']}",
         "track_count": p.get("track_count")}
        for p in playlists
        if p["id"] not in scheduled and db.load_recipe(app.state.conn, p["id"]) is not None
    ]}


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
    result = graph.neighbourhood(app.state.graph, db.normalize_name(artist), limit)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Künstler nicht gefunden: {artist}")
    return result


@app.post("/api/graph/playlist")
def graph_playlist(req: GraphPlaylistRequest):
    """Turn a set of artists from the graph into a playlist preview.

    Goes through the same graph-mode recipe that a saved playlist stores, so
    what the user previews is exactly what a later refresh rebuilds - and
    returns that recipe, so the Playlists tab can save it with the playlist.
    """
    recipe = PreviewRequest(mode="graph", artists=req.artists,
                            per_artist=req.per_artist, limit=req.limit)
    response = preview_playlist(recipe)
    response["recipe"] = recipe.model_dump()
    return response


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
        # The mood limits come from a small model and can be unreachable (it
        # wrote "max aggressive 0.0" for a romantic dinner), so loosen them
        # until there is something to choose from rather than return nothing.
        # Fetch a wider pool than asked for: the re-rating below needs room to
        # drop tracks the audio values let through but the titles give away.
        pool_size = min(len(tracks), max(req.limit * 2, 40))
        pool, criteria = presets.filter_with_fallback(
            tracks, criteria, limit=pool_size, discovery=req.discovery)
        scores = omlx_client.rate_fit(req.prompt, pool)
        matches = presets.rerank_by_fit(pool, scores)[:req.limit]
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
    elif req.mode == "graph":
        # A playlist built from the artist graph. Stored as a recipe like any
        # other, so a scheduled refresh draws new tracks by the same artists.
        if not req.artists:
            raise HTTPException(status_code=400, detail="artists fehlt")
        wanted = [db.normalize_name(a) for a in req.artists]
        allowed = {t["path"] for t in tracks}  # thumbs-down already removed
        picked = [t for t in graph.pick_for_artists(app.state.graph, wanted, req.per_artist)
                  if t["path"] in allowed]
        if not picked:
            raise HTTPException(status_code=404, detail="Keine Tracks für diese Künstler")
        matches = presets.cap_per_artist(presets.dedupe_by_song(picked), req.per_artist)[:req.limit]
        fitting = graph.tracks_for_artists(app.state.graph, wanted)
    elif req.mode == "wishlist":
        # Songs asked for by name go in as they are; no fresh-music quota or
        # discovery slots may push one of them out of the list.
        if not req.wishes:
            raise HTTPException(status_code=400, detail="wishes fehlt")
        return wishlist.build(req.wishes, tracks, req.limit)["tracks"]
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


def serialize_track(t: dict, now: float, fresh_days: float) -> dict:
    return {
        "path": t["path"], "bpm": t["bpm"], "key": t["key"],
        "danceability": t["danceability"], "mood_happy": t["mood_happy"],
        "mood_aggressive": t["mood_aggressive"], "mood_relaxed": t["mood_relaxed"],
        "mood_party": t["mood_party"], "percentile": t.get("percentile"),
        "display": t.get("display"),
        # When the library first saw the file, plus the verdict against the
        # request's own window, so a client can badge a track as new without
        # repeating the fresh_days arithmetic.
        "first_seen": t.get("first_seen"),
        "is_new": presets.is_fresh(t, now, fresh_days),
    }


@app.post("/api/playlists/preview")
def preview_playlist(req: PreviewRequest):
    now = time.time()
    return {"tracks": [serialize_track(t, now, req.fresh_days) for t in select_tracks(req)]}


@app.post("/api/playlists/wishlist")
def wishlist_preview(req: WishlistRequest):
    """Preview a playlist built around songs asked for by name.

    Besides the tracks, reports which wished-for songs the library does not
    have, and returns the recipe so the playlist can be saved, refreshed and
    scheduled like any other.
    """
    lines = [line for line in req.text.splitlines() if line.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="Keine Titel angegeben")
    tracks = [t for t in app.state.tracks if t.get("rating", 0) >= 0]
    result = wishlist.build(lines, tracks, req.limit)
    recipe = PreviewRequest(mode="wishlist", wishes=lines, limit=req.limit)
    return {
        "tracks": [serialize_track(t, time.time(), recipe.fresh_days) for t in result["tracks"]],
        "found": result["found"],
        "wished": result["wished"],
        "missing": result["missing"],
        "recipe": recipe.model_dump(),
    }


@app.post("/api/playlists/suggest-name")
def suggest_name(req: SuggestNameRequest):
    """A name for an already-previewed set of tracks.

    Separate from /preview on purpose: the manual tab re-previews on every
    slider move, and the local model takes ~2s per call. Naming happens once,
    when the user is about to save.
    """
    by_path = {t["path"]: t for t in app.state.tracks}
    tracks = [by_path[p] for p in req.track_paths if p in by_path]
    return {"name": omlx_client.suggest_playlist_name(tracks)}


@app.post("/api/playlists")
def add_playlist(req: CreatePlaylistRequest):
    # Written before the playlist exists, since VUIO accepts a description
    # only at creation and has no tool to change one afterwards.
    wanted = set(req.track_paths)
    tracks = [t for t in app.state.tracks if t["path"] in wanted]
    description = req.description or omlx_client.suggest_playlist_description(tracks)

    try:
        playlist_id = vuio_client.create_playlist(req.name, req.track_paths, description)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    if req.recipe is not None:
        db.save_recipe(app.state.conn, playlist_id, req.recipe.model_dump())
    if description:
        db.save_description(app.state.conn, playlist_id, description)
    return {"playlist_id": playlist_id, "description": description}


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
    if req is not None:
        db.save_recipe(app.state.conn, playlist_id, req.model_dump())
    # One rebuild path, shared with the scheduler, so a refresh triggered here
    # also rewrites the description instead of leaving a stale one behind.
    try:
        count = refresh_from_recipe(playlist_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f"Kein Rezept für Playlist {playlist_id} gespeichert - "
                   "Kriterien mitschicken oder die Playlist neu anlegen.",
        ) from None
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


# --- Browsing and streaming VuIO's library ---------------------------------

def _vuio(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


ARTIST_GROUPS_TTL = 300
_artist_groups = {"at": 0.0, "items": [], "variants": {}}


def _folded_artists():
    """Artists with guest credits folded into their lead, cached for a few minutes.

    VuIO matches artists by their exact tag, so "Darude, Zans" is a different
    artist from "Darude". Folding needs the whole list, which is a few
    thousand names - cheap to hold, worth not fetching on every tap.
    """
    if time.time() - _artist_groups["at"] > ARTIST_GROUPS_TTL or not _artist_groups["items"]:
        items = vuio_client.fold_artists(vuio_client.list_categories("artist"))
        _artist_groups.update(at=time.time(), items=items,
                              variants={g["name"]: g["variants"] for g in items})
    return _artist_groups


def _artist_variants(name: str) -> list:
    try:
        return _folded_artists()["variants"].get(name) or [name]
    except vuio_client.VuioError:
        return [name]


def _find_for_artist(artist: str, album, album_artist, genre, year) -> list:
    """Tracks credited to an artist or to any guest credit folded into them."""
    variants = _artist_variants(artist)
    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(
            lambda a: vuio_client.find_music(a, album, album_artist, genre, year), variants))
    seen, files = set(), []
    for batch in batches:
        for f in batch:
            if f.get("id") not in seen:
                seen.add(f.get("id"))
                files.append(f)
    return files


@app.get("/api/library/categories")
def library_categories(kind: str, artist: Optional[str] = None, genre: Optional[str] = None):
    if kind not in ("artist", "album", "album_artist", "genre", "year"):
        raise HTTPException(status_code=400, detail="unknown kind")
    if kind == "artist" and not artist and not genre:
        groups = _vuio(_folded_artists)["items"]
        return {"items": [{"name": g["name"], "count": g["count"]} for g in groups]}
    return {"items": _vuio(vuio_client.list_categories, kind, artist, genre)}


@app.get("/api/library/tracks")
def library_tracks(artist: Optional[str] = None, album: Optional[str] = None,
                   album_artist: Optional[str] = None, genre: Optional[str] = None,
                   year: Optional[int] = None):
    if not any([artist, album, album_artist, genre, year]):
        raise HTTPException(status_code=400, detail="give at least one filter")
    if artist:
        files = _vuio(_find_for_artist, artist, album, album_artist, genre, year)
    else:
        files = _vuio(vuio_client.find_music, artist, album, album_artist, genre, year)
    tracks = [vuio_client.track_summary(f) for f in files]
    # Album order first, then the order within a disc.
    tracks.sort(key=lambda t: (t["album"] or "", t["disc_number"] or 1, t["track_number"] or 0))
    return {"tracks": tracks}


@app.get("/api/library/albums")
def library_albums(artist: Optional[str] = None, album_artist: Optional[str] = None):
    """The albums of one artist or album artist, with their track counts.

    VuIO counts albums per track artist itself, exactly. It has no such view
    for album artists, so those are grouped from their tracks - and VuIO hands
    out at most 500 of those, which `complete` says when it may have cut off.
    """
    if artist:
        merged = {}
        for variant in _artist_variants(artist):
            for item in _vuio(vuio_client.list_categories, "album", variant):
                m = merged.setdefault(item["name"], {"name": item["name"], "count": 0})
                m["count"] = None if item["count"] is None or m["count"] is None else m["count"] + item["count"]
        items = sorted(merged.values(), key=lambda x: x["name"].lower())
        return {"albums": items, "complete": True}
    if album_artist:
        files = _vuio(vuio_client.find_music, None, None, album_artist)
        counts, years = {}, {}
        for f in files:
            name = f.get("album") or ""
            counts[name] = counts.get(name, 0) + 1
            years[name] = min(years.get(name) or 9999, f.get("year") or 9999)
        albums = [{"name": n, "count": c, "year": years[n] if years[n] != 9999 else None}
                  for n, c in sorted(counts.items(), key=lambda kv: kv[0].lower())]
        return {"albums": albums, "complete": len(files) < 500}
    raise HTTPException(status_code=400, detail="give an artist or an album artist")


@app.get("/api/library/search")
def library_search(q: str):
    if len(q.strip()) < 2:
        return {"tracks": []}
    return {"tracks": [vuio_client.track_summary(f) for f in _vuio(vuio_client.search_audio, q.strip())]}


@app.get("/api/library/folders")
def library_folders(path: Optional[str] = None, offset: int = 0):
    if not path:
        return {"path": None, "folders": [{"name": r.get("name"), "path": r.get("path")}
                                           for r in _vuio(vuio_client.list_roots) if r.get("available", True)],
                "tracks": [], "next_offset": None}
    page = _vuio(vuio_client.browse_folder, path, offset)
    # VuIO calls its subfolders "directories" and counts folders and files
    # together in `total`, so the next page starts after everything seen so far.
    folders = [{"name": f.get("name"), "path": f.get("path"), "count": f.get("file_count")}
               for f in page.get("directories") or page.get("folders") or page.get("subfolders") or []]
    files = page.get("files") or []
    tracks = [vuio_client.track_summary(f) for f in files]
    total = page.get("total") or page.get("total_files")
    seen = offset + len(folders) + len(files)
    next_offset = seen if (folders or files) and total and seen < total else None
    return {"path": path, "parent": page.get("parent"), "folders": folders, "tracks": tracks,
            "next_offset": next_offset}


@app.get("/api/library/playlists")
def library_playlists():
    return {"playlists": [
        {"id": p["id"], "name": p.get("name") or f"Playlist {p['id']}",
         "description": p.get("description"), "track_count": p.get("track_count")}
        for p in _vuio(vuio_client.list_playlists)
        if not (p.get("name") or "").startswith(vuio_client.PLAY_QUEUE_PREFIX)
    ]}


@app.get("/api/library/playlists/{playlist_id}")
def library_playlist(playlist_id: int):
    return {"tracks": [vuio_client.track_summary(f) for f in _vuio(vuio_client.playlist_tracks, playlist_id)]}


class PlayOnRequest(BaseModel):
    file_ids: list[int]
    renderer_id: str
    start: int = 0


@app.post("/api/library/play")
def library_play(req: PlayOnRequest):
    if not req.file_ids or len(req.file_ids) > 500:
        raise HTTPException(status_code=400, detail="give between 1 and 500 tracks")
    return _vuio(vuio_client.play_on_renderer, req.file_ids, req.renderer_id, req.start)


class CastMediaRequest(BaseModel):
    file_id: int
    renderer_id: str


@app.post("/api/library/cast")
def library_cast(req: CastMediaRequest):
    return _vuio(vuio_client.cast_media, req.file_id, req.renderer_id)


class ControlRequest(BaseModel):
    action: str
    renderer_id: Optional[str] = None


@app.post("/api/library/control")
def library_control(req: ControlRequest):
    if req.action not in ("play", "pause", "stop"):
        raise HTTPException(status_code=400, detail="unknown action")
    return _vuio(vuio_client.control_renderer, req.action, req.renderer_id)


# Where a track's bytes live on VuIO changes only when the library does.
_media_urls = {}


async def _proxy_media(file_id: int, kind: str, request: Request):
    """Pass VuIO's audio or cover through, Range requests included.

    The browser could use VuIO's URL directly, but that only works while the
    device can reach VuIO and VuIO advertises an address it can use; a phone
    on the same network, or behind a proxy, often cannot. Seeking needs the
    Range header, so it is forwarded and VuIO's 206 answer returned as is.
    """
    key = (file_id, kind)
    if key not in _media_urls:
        try:
            _media_urls[key] = await asyncio.to_thread(vuio_client.media_url, file_id, kind)
        except vuio_client.VuioError as e:
            # A track without artwork is normal, not a gateway failure.
            raise HTTPException(status_code=404 if kind == "cover" else 502, detail=str(e)) from e
    headers = {k: v for k, v in (("Range", request.headers.get("range")),) if v}
    if vuio_client.VUIO_TOKEN:
        headers["Authorization"] = f"Bearer {vuio_client.VUIO_TOKEN}"
    client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=None))
    try:
        upstream = await client.send(client.build_request("GET", _media_urls[key], headers=headers), stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        _media_urls.pop(key, None)
        raise HTTPException(status_code=502, detail=f"VuIO unreachable: {e}") from e
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        _media_urls.pop(key, None)
        raise HTTPException(status_code=404 if kind == "cover" else 502, detail=f"VuIO answered {upstream.status_code}")

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    passthrough = {k: v for k, v in upstream.headers.items()
                   if k.lower() in ("content-type", "content-length", "content-range", "accept-ranges")}
    if kind == "cover":
        passthrough["Cache-Control"] = "public, max-age=86400"
    return StreamingResponse(body(), status_code=upstream.status_code, headers=passthrough)


# Which track stands in for an album or artist on the grids.
_cover_tracks = {}


@app.get("/api/library/cover")
async def library_cover(request: Request, album: Optional[str] = None, artist: Optional[str] = None,
                        album_artist: Optional[str] = None):
    """Artwork for a whole album or artist: the cover of its first track.

    The grids show hundreds of albums, so the browser asks for these lazily,
    one image at a time, as they scroll into view.
    """
    if not album and not artist and not album_artist:
        raise HTTPException(status_code=400, detail="give an album, an artist or an album artist")
    key = (album, artist, album_artist)
    if key not in _cover_tracks:
        files = await asyncio.to_thread(_vuio, vuio_client.find_music, artist, album, album_artist, None, None, 1)
        _cover_tracks[key] = files[0].get("id") if files else None
    if _cover_tracks[key] is None:
        raise HTTPException(status_code=404, detail="nothing found")
    return await _proxy_media(_cover_tracks[key], "cover", request)


@app.get("/api/media/{file_id}/stream")
async def media_stream(file_id: int, request: Request):
    return await _proxy_media(file_id, "stream", request)


@app.get("/api/media/{file_id}/cover")
async def media_cover(file_id: int, request: Request):
    return await _proxy_media(file_id, "cover", request)


class FrontendFiles(StaticFiles):
    """Static frontend with cache rules that survive a redeploy.

    Without a Cache-Control header a browser may reuse index.html on its own
    judgement, and with the old HTML it loads the old JavaScript bundle - a
    deploy then looks like it did nothing. no-cache does not mean "never
    store": the browser keeps the file but asks the server first, and the
    ETag turns that into a cheap 304 when nothing changed.

    Vite names its bundles by content hash, so those files can never change
    under the same name and are safe to keep for a year.
    """

    async def get_response(self, path, scope):
        # The pages are client-side routes: reloading /library or opening a
        # bookmark must still get the app, which then shows that page. Files
        # with an extension (a missing asset) stay a real 404.
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or "." in path.rsplit("/", 1)[-1] or path.startswith("api/"):
                raise
            response = await super().get_response("index.html", scope)
        if response.status_code in (200, 304):
            immutable = path.startswith("assets/")
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable" if immutable else "no-cache"
            )
        return response


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/", FrontendFiles(directory=STATIC_DIR, html=True), name="static")
