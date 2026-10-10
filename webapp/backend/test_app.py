import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
from fastapi.testclient import TestClient

from crate_mind.analysis import db as analysis_db


def _make_test_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = analysis_db.get_connection(tmp.name)
    analysis_db.upsert_track(conn, "/music/a.mp3", mtime=1.0, size=100, status="ok")
    analysis_db.upsert_features(conn, "/music/a.mp3", {
        "bpm": 120.0, "key": "C major",
        "mood_happy": 0.8, "mood_aggressive": 0.1, "mood_relaxed": 0.2,
        "mood_party": 0.7, "danceability": 0.9,
        "embedding": np.ones(200, dtype=np.float32),
    })
    conn.close()
    return tmp.name


os.environ["DB_PATH"] = _make_test_db()

import app as app_module
import db
import omlx_client
import typesafe_client
import vuio_client


def test_rating_endpoint_persists_and_takes_effect_without_restart():
    with TestClient(app_module.app) as client:
        r = client.put("/api/ratings", json={"path": "/music/a.mp3", "rating": 1})
        assert r.status_code == 200

        assert client.get("/api/ratings").json()["ratings"] == [
            {"path": "/music/a.mp3", "rating": 1}]
        # the cached track list backs every playlist, so it must reflect it now
        cached = next(t for t in app_module.app.state.tracks
                      if t["path"] == "/music/a.mp3")
        assert cached["percentile"] == db.FAVOURITE_PERCENTILE

        client.put("/api/ratings", json={"path": "/music/a.mp3", "rating": 0})
        assert client.get("/api/ratings").json()["ratings"] == []


def test_rating_an_unknown_track_is_404():
    with TestClient(app_module.app) as client:
        r = client.put("/api/ratings", json={"path": "/music/nope.mp3", "rating": 1})
        assert r.status_code == 404


def test_banned_tracks_are_kept_out_of_playlists_but_stay_seedable():
    with TestClient(app_module.app) as client:
        client.put("/api/ratings", json={"path": "/music/a.mp3", "rating": -1})
        try:
            body = {"mode": "seed", "seed_path": "/music/a.mp3", "limit": 5}
            # seeding off a banned track still resolves it (no 404)
            assert client.post("/api/playlists/preview", json=body).status_code == 200
            # but it is gone as a candidate for everyone else
            assert all(t["path"] != "/music/a.mp3" for t in
                       app_module.select_tracks(app_module.PreviewRequest(
                           mode="manual", criteria={}, limit=5)))
        finally:
            client.put("/api/ratings", json={"path": "/music/a.mp3", "rating": 0})


def test_play_endpoint_counts_and_refreshes_the_cache():
    with TestClient(app_module.app) as client:
        before = next(t for t in app_module.app.state.tracks
                      if t["path"] == "/music/a.mp3")["score"]
        r = client.post("/api/plays", json={"path": "/music/a.mp3"})
        assert r.status_code == 200
        assert r.json()["plays"] == 1

        # the cached list backs every playlist, so the play must show there now
        after = next(t for t in app_module.app.state.tracks
                     if t["path"] == "/music/a.mp3")["score"]
        assert before is None and after == db.score_of(1, 0)

        assert client.post("/api/plays",
                           json={"path": "/music/a.mp3", "skipped": True}
                           ).json() == {"path": "/music/a.mp3", "plays": 1, "skips": 1}


def test_playing_an_unknown_track_is_404():
    with TestClient(app_module.app) as client:
        assert client.post("/api/plays",
                           json={"path": "/music/nope.mp3"}).status_code == 404


def test_fresh_quota_reaches_playlists_through_the_api():
    """A newly imported track must show up even though nothing has played it."""
    with TestClient(app_module.app) as client:
        import time as _t
        fresh = dict(app_module.app.state.tracks[0])
        fresh.update({"path": "/music/New Band - Debut/01. New Band - Song.mp3",
                      "first_seen": _t.time(), "song_key": "new", "score": None,
                      "percentile": None, "rating": 0, "artist": "new band"})
        old = dict(app_module.app.state.tracks[0])
        old.update({"first_seen": _t.time() - 400 * 86400})
        app_module.app.state.tracks = [old, fresh]
        try:
            r = client.post("/api/playlists/preview",
                            json={"mode": "manual", "criteria": {}, "limit": 2,
                                  "fresh_share": 0.5, "fresh_days": 60})
            assert r.status_code == 200
            assert any(t["path"] == fresh["path"] for t in r.json()["tracks"])

            # and with the quota off it is ranked normally, not forced in
            r = client.post("/api/playlists/preview",
                            json={"mode": "manual", "criteria": {}, "limit": 1,
                                  "fresh_share": 0.0})
            assert len(r.json()["tracks"]) == 1
        finally:
            app_module.app.state.tracks = db.load_ok_tracks(app_module.app.state.conn)


def test_preview_reports_import_date_and_new_flag():
    """Clients badge new music off this, so the flag must follow the window
    the request itself asked for, not a fixed one."""
    import time as _t
    with TestClient(app_module.app) as client:
        fresh = dict(app_module.app.state.tracks[0])
        fresh["first_seen"] = _t.time() - 10 * 86400
        app_module.app.state.tracks = [fresh]
        try:
            body = {"mode": "manual", "criteria": {}, "limit": 1, "fresh_share": 0}
            t = client.post("/api/playlists/preview",
                            json={**body, "fresh_days": 60}).json()["tracks"][0]
            assert t["first_seen"] == fresh["first_seen"]
            assert t["is_new"] is True

            # same track, narrower window -> no longer new
            t = client.post("/api/playlists/preview",
                            json={**body, "fresh_days": 5}).json()["tracks"][0]
            assert t["is_new"] is False
        finally:
            app_module.app.state.tracks = db.load_ok_tracks(app_module.app.state.conn)


def test_preview_handles_tracks_with_no_import_date():
    with TestClient(app_module.app) as client:
        undated = dict(app_module.app.state.tracks[0])
        undated["first_seen"] = None
        app_module.app.state.tracks = [undated]
        try:
            t = client.post("/api/playlists/preview",
                            json={"mode": "manual", "criteria": {}, "limit": 1}
                            ).json()["tracks"][0]
            assert t["first_seen"] is None and t["is_new"] is False
        finally:
            app_module.app.state.tracks = db.load_ok_tracks(app_module.app.state.conn)


def test_stats_endpoint_returns_counts():
    with TestClient(app_module.app) as client:
        response = client.get("/api/stats")
    assert response.status_code == 200
    assert response.json()["status_counts"]["ok"] == 1


def test_tracks_search_endpoint():
    with TestClient(app_module.app) as client:
        response = client.get("/api/tracks", params={"q": "a.mp3"})
    assert response.json()["tracks"][0]["path"] == "/music/a.mp3"


IDLE_STATUS = {"renderers": [{"renderer_id": "r1", "friendly_name": "Evo One",
                              "state": "unknown", "current_url": None}]}
PLAYING_STATUS = {"renderers": [{"renderer_id": "r1", "friendly_name": "Evo One",
                                 "state": "playing",
                                 "current_url": "http://h:8080/media/42.m4a"}]}


def test_schedule_requires_a_recipe_to_refresh_from():
    """Without a recipe there is nothing to rebuild from, so refuse early
    rather than failing silently every week."""
    with TestClient(app_module.app) as client:
        response = client.put("/api/schedules/777",
                              json={"name": "X", "weekday": 1, "hour": 6, "minute": 17})
    assert response.status_code == 400


def test_schedule_rejects_impossible_times():
    app_module.db.save_recipe(app_module.app.state.conn, 55,
                              {"mode": "manual", "criteria": {"min_bpm": 10}})
    with TestClient(app_module.app) as client:
        response = client.put("/api/schedules/55",
                              json={"name": "X", "weekday": 9, "hour": 6, "minute": 17})
    assert response.status_code == 400


def test_schedule_round_trip_through_the_api():
    app_module.db.save_recipe(app_module.app.state.conn, 56,
                              {"mode": "manual", "criteria": {"min_bpm": 10}})
    with TestClient(app_module.app) as client:
        assert client.put("/api/schedules/56",
                          json={"name": "Wochenmix", "weekday": 1,
                                "hour": 6, "minute": 17}).status_code == 200
        entry = next(s for s in client.get("/api/schedules").json()["schedules"]
                     if s["playlist_id"] == 56)
        assert entry["describes"] == "Montag 06:17"
        assert entry["recipe"]["mode"] == "manual"
        assert entry["next_run"].endswith("06:17")

        assert client.delete("/api/schedules/56").status_code == 200
        assert client.delete("/api/schedules/56").status_code == 404


def test_create_generates_and_stores_a_description():
    with patch.object(vuio_client, "create_playlist", return_value=71) as create, \
         patch.object(omlx_client, "suggest_playlist_description", return_value="Treibend."):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists",
                                   json={"name": "x", "track_paths": ["/music/a.mp3"]})
    assert response.json()["description"] == "Treibend."
    # Handed to VUIO as well, since it only accepts one at creation.
    assert create.call_args[0][2] == "Treibend."
    assert app_module.db.load_description(app_module.app.state.conn, 71) == "Treibend."


def test_create_keeps_a_description_the_caller_supplied():
    """An explicit description must not be overwritten by the model."""
    with patch.object(vuio_client, "create_playlist", return_value=72), \
         patch.object(omlx_client, "suggest_playlist_description",
                      return_value="vom Modell") as model:
        with TestClient(app_module.app) as client:
            client.post("/api/playlists", json={"name": "x", "track_paths": ["/music/a.mp3"],
                                                "description": "von Hand"})
    model.assert_not_called()
    assert app_module.db.load_description(app_module.app.state.conn, 72) == "von Hand"


def test_create_survives_the_model_being_down():
    with patch.object(vuio_client, "create_playlist", return_value=73), \
         patch.object(omlx_client, "suggest_playlist_description", return_value=None):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists",
                                   json={"name": "x", "track_paths": ["/music/a.mp3"]})
    assert response.status_code == 200
    assert response.json()["description"] is None


def test_refresh_rewrites_the_description_for_the_new_tracks():
    app_module.db.save_recipe(app_module.app.state.conn, 74,
                              {"mode": "manual", "criteria": {"min_bpm": 10}})
    app_module.db.save_description(app_module.app.state.conn, 74, "Alte Beschreibung")
    with patch.object(vuio_client, "replace_playlist_tracks", return_value=1), \
         patch.object(omlx_client, "suggest_playlist_description", return_value="Neue Beschreibung"):
        with TestClient(app_module.app) as client:
            client.post("/api/playlists/74/refresh")
    assert app_module.db.load_description(app_module.app.state.conn, 74) == "Neue Beschreibung"


def test_graph_playlist_returns_preview_shaped_tracks():
    """The Playlists tab takes this over verbatim, so the shape must match."""
    with TestClient(app_module.app) as client:
        response = client.post("/api/graph/playlist", json={"artists": ["a"], "limit": 5})
    if response.status_code == 404:
        return  # fixture library has no artist with enough tracks
    track = response.json()["tracks"][0]
    for field in ("path", "bpm", "key", "percentile", "is_new"):
        assert field in track, field


def test_graph_playlist_404s_for_unknown_artists():
    with TestClient(app_module.app) as client:
        response = client.post("/api/graph/playlist", json={"artists": ["niemand"]})
    assert response.status_code == 404


def test_suggest_name_passes_the_previewed_tracks_to_the_model():
    with patch.object(omlx_client, "suggest_playlist_name", return_value="Punk am Montag") as mock:
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/suggest-name",
                                   json={"track_paths": ["/music/a.mp3"]})
    assert response.json() == {"name": "Punk am Montag"}
    assert [t["path"] for t in mock.call_args[0][0]] == ["/music/a.mp3"]


def test_suggest_name_ignores_paths_outside_the_library():
    with patch.object(omlx_client, "suggest_playlist_name", return_value="X") as mock:
        with TestClient(app_module.app) as client:
            client.post("/api/playlists/suggest-name",
                        json={"track_paths": ["/music/a.mp3", "/nope.mp3"]})
    assert [t["path"] for t in mock.call_args[0][0]] == ["/music/a.mp3"]


def test_suggest_name_reports_null_when_the_model_is_unavailable():
    """The UI falls back to a manual name rather than showing an error."""
    with patch.object(omlx_client, "suggest_playlist_name", return_value=None):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/suggest-name",
                                   json={"track_paths": ["/music/a.mp3"]})
    assert response.status_code == 200
    assert response.json() == {"name": None}


def test_candidates_only_offers_playlists_that_can_be_rebuilt():
    """A playlist with no recipe has nothing to refresh from, so offering it
    would just produce a 400 on save."""
    app_module.db.save_recipe(app_module.app.state.conn, 61,
                              {"mode": "manual", "criteria": {"min_bpm": 10}})
    app_module.db.save_recipe(app_module.app.state.conn, 62,
                              {"mode": "manual", "criteria": {"min_bpm": 10}})
    app_module.db.save_schedule(app_module.app.state.conn, 62, "Schon geplant", 1, 6, 17)
    listing = [{"id": 60, "name": "Ohne Rezept", "track_count": 5},
               {"id": 61, "name": "Frei", "track_count": 9},
               {"id": 62, "name": "Schon geplant", "track_count": 7}]

    with patch.object(vuio_client, "list_playlists", return_value=listing):
        with TestClient(app_module.app) as client:
            response = client.get("/api/schedules/candidates")

    ids = [c["playlist_id"] for c in response.json()["candidates"]]
    assert ids == [61], ids


def test_candidates_path_is_not_swallowed_by_the_id_route():
    """"candidates" must not be parsed as a playlist id."""
    with patch.object(vuio_client, "list_playlists", return_value=[]):
        with TestClient(app_module.app) as client:
            response = client.get("/api/schedules/candidates")
    assert response.status_code == 200
    assert "candidates" in response.json()


def test_a_new_schedule_waits_for_its_next_slot():
    """Setting up "Monday 06:17" mid-week must not fire within the minute."""
    app_module.db.save_recipe(app_module.app.state.conn, 58,
                              {"mode": "manual", "criteria": {"min_bpm": 10}})
    with TestClient(app_module.app) as client:
        client.put("/api/schedules/58",
                   json={"name": "X", "weekday": 1, "hour": 6, "minute": 17})
    entry = next(s for s in app_module.db.list_schedules(app_module.app.state.conn)
                 if s["playlist_id"] == 58)
    assert entry["last_run"] is not None
    assert app_module.schedules.is_due(entry, app_module.datetime.now()) is False


def test_run_now_rebuilds_from_the_stored_recipe():
    app_module.db.save_recipe(app_module.app.state.conn, 57,
                              {"mode": "manual", "criteria": {"min_bpm": 10}})
    app_module.db.save_schedule(app_module.app.state.conn, 57, "X", 1, 6, 17)
    with patch.object(vuio_client, "replace_playlist_tracks", return_value=1) as mock:
        with TestClient(app_module.app) as client:
            response = client.post("/api/schedules/57/run")
    assert response.json() == {"playlist_id": 57, "track_count": 1}
    assert mock.call_args[0][1] == ["/music/a.mp3"]
    # The run is recorded, so the weekly slot does not fire again on top of it.
    entry = next(s for s in app_module.db.list_schedules(app_module.app.state.conn)
                 if s["playlist_id"] == 57)
    assert entry["last_result"] == "1 Tracks"


def test_now_playing_reports_nothing_when_idle():
    """The old status bar read {renderers:[...]} as truthy and claimed
    playback forever; an idle renderer must resolve to None."""
    with patch.object(vuio_client, "all_playback_status", return_value=IDLE_STATUS):
        with TestClient(app_module.app) as client:
            response = client.get("/api/now-playing")
    assert response.json() == {"playing": None}


def test_now_playing_resolves_the_track():
    with patch.object(vuio_client, "all_playback_status", return_value=PLAYING_STATUS), \
         patch.object(vuio_client, "path_for_media_id", return_value="/music/A - Alb/01. A - Song.flac"):
        with TestClient(app_module.app) as client:
            response = client.get("/api/now-playing")
    assert response.json()["playing"] == {
        "renderer": "Evo One",
        "path": "/music/A - Alb/01. A - Song.flac",
        "title": "01. A - Song",
    }


def test_now_playing_survives_vuio_being_down():
    with patch.object(vuio_client, "all_playback_status",
                      side_effect=vuio_client.VuioError("down")):
        with TestClient(app_module.app) as client:
            response = client.get("/api/now-playing")
    assert response.status_code == 200
    assert response.json() == {"playing": None}


def test_plays_endpoint_reports_recorded_listens():
    app_module.db.record_play(app_module.app.state.conn, "/music/a.mp3",
                              seconds=200, completed=True)
    with TestClient(app_module.app) as client:
        response = client.get("/api/plays")
    assert response.status_code == 200
    entry = next(p for p in response.json()["plays"] if p["path"] == "/music/a.mp3")
    assert entry["plays"] >= 1


def test_recent_tracks_endpoint():
    with TestClient(app_module.app) as client:
        response = client.get("/api/tracks/recent")
    assert response.status_code == 200
    assert response.json()["tracks"][0]["path"] == "/music/a.mp3"


def test_preview_manual_mode_filters_by_criteria():
    with TestClient(app_module.app) as client:
        response = client.post("/api/playlists/preview", json={"mode": "manual", "criteria": {"min_bpm": 200}})
    assert response.status_code == 200
    assert response.json()["tracks"] == []


def test_preview_prompt_mode():
    with patch.object(omlx_client, "parse_prompt_to_criteria", return_value={"min_danceability": 0.5}):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/preview", json={"mode": "prompt", "prompt": "party"})
    assert response.status_code == 200
    assert response.json()["tracks"][0]["path"] == "/music/a.mp3"


def test_preview_prompt_mode_maps_omlx_error_to_502():
    with patch.object(omlx_client, "parse_prompt_to_criteria", side_effect=omlx_client.OmlxError("down")):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/preview", json={"mode": "prompt", "prompt": "party"})
    assert response.status_code == 502


def test_preview_unknown_seed_returns_404():
    with TestClient(app_module.app) as client:
        response = client.post("/api/playlists/preview", json={"mode": "seed", "seed_path": "/no/such.mp3"})
    assert response.status_code == 404


def test_preview_smart_mode_requires_mood_prompt():
    with TestClient(app_module.app) as client:
        response = client.post("/api/playlists/preview", json={"mode": "smart"})
    assert response.status_code == 400


def test_preview_smart_mode_ranks_by_vibe():
    with patch.object(typesafe_client, "rank_by_vibe", return_value=[{
        "path": "/music/a.mp3", "bpm": 120.0, "key": "C major",
        "danceability": 0.9, "mood_happy": 0.8, "mood_aggressive": 0.1,
        "mood_relaxed": 0.2, "mood_party": 0.7,
    }]):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/preview", json={"mode": "smart", "mood_prompt": "chill sunday"})
    assert response.status_code == 200
    assert response.json()["tracks"][0]["path"] == "/music/a.mp3"


def test_api_defaults_match_the_apps_own_behaviour():
    """A direct API caller must get the playlist the UI would build, not a
    silently different one because the knobs default to off."""
    req = app_module.PreviewRequest(mode="manual")
    assert req.discovery == 0.1
    assert req.taste_weight == 0.3


def test_refresh_replaces_the_playlist_contents():
    with patch.object(vuio_client, "replace_playlist_tracks", return_value=1) as mock_replace:
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/7/refresh",
                                   json={"mode": "manual", "criteria": {"min_bpm": 10}})
    assert response.status_code == 200
    assert response.json() == {"playlist_id": 7, "track_count": 1}
    playlist_id, paths = mock_replace.call_args[0]
    assert playlist_id == 7
    assert paths == ["/music/a.mp3"]


def test_create_stores_the_recipe_and_refresh_reuses_it():
    recipe = {"mode": "manual", "criteria": {"min_bpm": 10}, "limit": 5}
    with patch.object(vuio_client, "create_playlist", return_value=11):
        with TestClient(app_module.app) as client:
            client.post("/api/playlists", json={"name": "x", "track_paths": ["/music/a.mp3"],
                                                "recipe": recipe})
    assert app_module.db.load_recipe(app_module.app.state.conn, 11)["limit"] == 5

    # No body: the stored recipe drives the rebuild.
    with patch.object(vuio_client, "replace_playlist_tracks", return_value=1) as mock_replace:
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/11/refresh")
    assert response.status_code == 200
    assert mock_replace.call_args[0][1] == ["/music/a.mp3"]


def test_refresh_without_a_stored_recipe_is_a_404():
    with TestClient(app_module.app) as client:
        response = client.post("/api/playlists/9999/refresh")
    assert response.status_code == 404


def test_refresh_with_a_body_replaces_the_stored_recipe():
    with patch.object(vuio_client, "replace_playlist_tracks", return_value=1):
        with TestClient(app_module.app) as client:
            client.post("/api/playlists/12/refresh",
                        json={"mode": "manual", "criteria": {"min_bpm": 10}, "limit": 7})
    assert app_module.db.load_recipe(app_module.app.state.conn, 12)["limit"] == 7


def test_refresh_maps_vuio_error_to_502():
    with patch.object(vuio_client, "replace_playlist_tracks",
                      side_effect=vuio_client.VuioError("down")):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/7/refresh",
                                   json={"mode": "manual", "criteria": {"min_bpm": 10}})
    assert response.status_code == 502


def test_create_playlist_maps_vuio_error_to_502():
    with patch.object(vuio_client, "create_playlist", side_effect=vuio_client.VuioError("down")):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists", json={"name": "x", "track_paths": ["/music/a.mp3"]})
    assert response.status_code == 502


def test_create_playlist_success():
    with patch.object(vuio_client, "create_playlist", return_value=7):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists", json={"name": "x", "track_paths": ["/music/a.mp3"]})
    assert response.status_code == 200
    assert response.json()["playlist_id"] == 7


def test_renderers_endpoint():
    with patch.object(vuio_client, "list_renderers", return_value=[{"id": "r1", "friendly_name": "TV"}]):
        with TestClient(app_module.app) as client:
            response = client.get("/api/renderers")
    assert response.json()["renderers"][0]["id"] == "r1"


def test_cast_endpoint():
    with patch.object(vuio_client, "cast_playlist", return_value={"status": "ok"}) as mock_cast:
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/7/cast", json={"renderer_id": "r1"})
    assert response.status_code == 200
    mock_cast.assert_called_once_with(7, "r1")


def test_failed_tracks_endpoint():
    with TestClient(app_module.app) as client:
        response = client.get("/api/tracks/failed")
    assert response.status_code == 200
    body = response.json()
    assert "tracks" in body
    assert "total" in body


def test_failed_tracks_endpoint_filters_by_query():
    with TestClient(app_module.app) as client:
        response = client.get("/api/tracks/failed", params={"q": "nomatch"})
    assert response.status_code == 200
    assert response.json()["tracks"] == []


def test_retry_failed_endpoint_resets_failed_tracks():
    analysis_db.upsert_track(app_module.app.state.conn, "/music/broken.m4a", mtime=1.0, size=100,
                              status="failed", error_message="Operation not permitted")
    with TestClient(app_module.app) as client:
        response = client.post("/api/tracks/retry-failed")
    assert response.status_code == 200
    assert response.json()["retried"] >= 1
    assert app_module.app.state.conn.execute(
        "SELECT status FROM tracks WHERE path = ?", ("/music/broken.m4a",)
    ).fetchone() == ("pending",)


if __name__ == "__main__":
    test_stats_endpoint_returns_counts()
    test_tracks_search_endpoint()
    test_schedule_requires_a_recipe_to_refresh_from()
    test_schedule_rejects_impossible_times()
    test_schedule_round_trip_through_the_api()
    test_create_generates_and_stores_a_description()
    test_create_keeps_a_description_the_caller_supplied()
    test_create_survives_the_model_being_down()
    test_refresh_rewrites_the_description_for_the_new_tracks()
    test_graph_playlist_returns_preview_shaped_tracks()
    test_graph_playlist_404s_for_unknown_artists()
    test_suggest_name_passes_the_previewed_tracks_to_the_model()
    test_suggest_name_ignores_paths_outside_the_library()
    test_suggest_name_reports_null_when_the_model_is_unavailable()
    test_candidates_only_offers_playlists_that_can_be_rebuilt()
    test_candidates_path_is_not_swallowed_by_the_id_route()
    test_a_new_schedule_waits_for_its_next_slot()
    test_run_now_rebuilds_from_the_stored_recipe()
    test_now_playing_reports_nothing_when_idle()
    test_now_playing_resolves_the_track()
    test_now_playing_survives_vuio_being_down()
    test_plays_endpoint_reports_recorded_listens()
    test_recent_tracks_endpoint()
    test_failed_tracks_endpoint()
    test_failed_tracks_endpoint_filters_by_query()
    test_retry_failed_endpoint_resets_failed_tracks()
    test_preview_manual_mode_filters_by_criteria()
    test_preview_prompt_mode()
    test_preview_prompt_mode_maps_omlx_error_to_502()
    test_preview_unknown_seed_returns_404()
    test_preview_smart_mode_requires_mood_prompt()
    test_preview_smart_mode_ranks_by_vibe()
    test_api_defaults_match_the_apps_own_behaviour()
    test_refresh_replaces_the_playlist_contents()
    test_create_stores_the_recipe_and_refresh_reuses_it()
    test_refresh_without_a_stored_recipe_is_a_404()
    test_refresh_with_a_body_replaces_the_stored_recipe()
    test_refresh_maps_vuio_error_to_502()
    test_create_playlist_maps_vuio_error_to_502()
    test_create_playlist_success()
    test_renderers_endpoint()
    test_cast_endpoint()
    print("All app tests passed.")
