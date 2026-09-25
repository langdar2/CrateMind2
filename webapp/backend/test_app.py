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
import vuio_client


def test_stats_endpoint_returns_counts():
    with TestClient(app_module.app) as client:
        response = client.get("/api/stats")
    assert response.status_code == 200
    assert response.json()["status_counts"]["ok"] == 1


def test_presets_endpoint_lists_presets():
    with TestClient(app_module.app) as client:
        response = client.get("/api/presets")
    assert "workout" in response.json()


def test_tracks_search_endpoint():
    with TestClient(app_module.app) as client:
        response = client.get("/api/tracks", params={"q": "a.mp3"})
    assert response.json()["tracks"][0]["path"] == "/music/a.mp3"


def test_preview_preset_mode():
    with TestClient(app_module.app) as client:
        response = client.post("/api/playlists/preview", json={"mode": "preset", "preset_name": "party"})
    assert response.status_code == 200
    assert response.json()["tracks"][0]["path"] == "/music/a.mp3"


def test_preview_unknown_seed_returns_404():
    with TestClient(app_module.app) as client:
        response = client.post("/api/playlists/preview", json={"mode": "seed", "seed_path": "/no/such.mp3"})
    assert response.status_code == 404


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


if __name__ == "__main__":
    test_stats_endpoint_returns_counts()
    test_presets_endpoint_lists_presets()
    test_tracks_search_endpoint()
    test_failed_tracks_endpoint()
    test_failed_tracks_endpoint_filters_by_query()
    test_preview_preset_mode()
    test_preview_unknown_seed_returns_404()
    test_create_playlist_maps_vuio_error_to_502()
    test_create_playlist_success()
    test_renderers_endpoint()
    test_cast_endpoint()
    print("All app tests passed.")
