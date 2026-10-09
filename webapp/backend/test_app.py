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


def test_now_playing_reports_nothing_when_idle():
    """The old status bar read {renderers:[...]} as truthy and claimed
    playback forever; an idle renderer must resolve to None."""
    with patch.object(vuio_client, "get_playback_status", return_value=IDLE_STATUS):
        with TestClient(app_module.app) as client:
            response = client.get("/api/now-playing")
    assert response.json() == {"playing": None}


def test_now_playing_resolves_the_track():
    with patch.object(vuio_client, "get_playback_status", return_value=PLAYING_STATUS), \
         patch.object(vuio_client, "path_for_media_id", return_value="/music/A - Alb/01. A - Song.flac"):
        with TestClient(app_module.app) as client:
            response = client.get("/api/now-playing")
    assert response.json()["playing"] == {
        "renderer": "Evo One",
        "path": "/music/A - Alb/01. A - Song.flac",
        "title": "01. A - Song",
    }


def test_now_playing_survives_vuio_being_down():
    with patch.object(vuio_client, "get_playback_status",
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
