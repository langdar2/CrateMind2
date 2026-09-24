import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np

from crate_mind.analysis import db as analysis_db


def _make_test_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = analysis_db.get_connection(tmp.name)

    analysis_db.upsert_track(conn, "/music/a.mp3", mtime=1.0, size=100, status="ok")
    analysis_db.upsert_features(conn, "/music/a.mp3", {
        "bpm": 130.0, "key": "C major",
        "mood_happy": 0.8, "mood_aggressive": 0.1, "mood_relaxed": 0.2,
        "mood_party": 0.7, "danceability": 0.9,
        "embedding": np.ones(200, dtype=np.float32),
    })

    analysis_db.upsert_track(conn, "/music/b.mp3", mtime=1.0, size=100, status="ok")
    analysis_db.upsert_features(conn, "/music/b.mp3", {
        "bpm": 90.0, "key": "A minor",
        "mood_happy": 0.3, "mood_aggressive": 0.2, "mood_relaxed": 0.6,
        "mood_party": 0.2, "danceability": 0.4,
        "embedding": np.zeros(200, dtype=np.float32),
    })

    analysis_db.upsert_track(conn, "/music/c.mp3", mtime=1.0, size=100, status="failed")
    conn.close()
    return tmp.name


_DB_PATH = _make_test_db()
import os
os.environ["DB_PATH"] = _DB_PATH

from fastapi.testclient import TestClient

import app as app_module

app = app_module.app


def test_get_stats():
    with TestClient(app) as client:
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "status_counts" in data
        assert "bpm_histogram" in data
        assert "key_counts" in data
        assert "mood_averages" in data


def test_get_presets():
    with TestClient(app) as client:
        response = client.get("/api/presets")
        assert response.status_code == 200
        data = response.json()
        assert "workout" in data["presets"]


def test_get_tracks_strips_embedding():
    with TestClient(app) as client:
        response = client.get("/api/tracks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        for track in data:
            assert "embedding" not in track


def test_preview_with_preset():
    with TestClient(app) as client:
        response = client.post("/api/playlists/preview", json={"preset": "workout"})
        assert response.status_code == 200
        data = response.json()
        assert "tracks" in data
        assert any(t["path"] == "/music/a.mp3" for t in data["tracks"])


def test_preview_with_both_set_returns_400():
    with TestClient(app) as client:
        response = client.post(
            "/api/playlists/preview",
            json={"preset": "workout", "seed_path": "/music/a.mp3"},
        )
        assert response.status_code == 400


def test_preview_with_neither_set_returns_400():
    with TestClient(app) as client:
        response = client.post("/api/playlists/preview", json={})
        assert response.status_code == 400


def test_preview_unknown_preset_returns_400():
    with TestClient(app) as client:
        response = client.post("/api/playlists/preview", json={"preset": "nope"})
        assert response.status_code == 400


def test_preview_with_seed_path():
    with TestClient(app) as client:
        response = client.post("/api/playlists/preview", json={"seed_path": "/music/a.mp3"})
        assert response.status_code == 200
        data = response.json()
        assert all(t["path"] != "/music/a.mp3" for t in data["tracks"])


def test_preview_with_unknown_seed_path_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/playlists/preview", json={"seed_path": "/nope.mp3"})
        assert response.status_code == 404


def test_create_playlist_with_monkeypatched_vuio(monkeypatch=None):
    def fake_find_file_id(query):
        return 1 if query == "a" else None

    def fake_create_playlist(name):
        return 42

    calls = {}

    def fake_add_tracks(playlist_id, file_ids):
        calls["playlist_id"] = playlist_id
        calls["file_ids"] = file_ids

    original_find_file_id = app_module.vuio_client.find_file_id
    original_create_playlist = app_module.vuio_client.create_playlist
    original_add_tracks = app_module.vuio_client.add_tracks

    app_module.vuio_client.find_file_id = fake_find_file_id
    app_module.vuio_client.create_playlist = fake_create_playlist
    app_module.vuio_client.add_tracks = fake_add_tracks

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/playlists",
                json={"name": "My Playlist", "paths": ["/music/a.mp3", "/music/b.mp3"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["playlist_id"] == 42
            assert data["matched"] == 1
            assert data["total"] == 2
            assert calls["playlist_id"] == 42
            assert calls["file_ids"] == [1]
    finally:
        app_module.vuio_client.find_file_id = original_find_file_id
        app_module.vuio_client.create_playlist = original_create_playlist
        app_module.vuio_client.add_tracks = original_add_tracks


def test_get_renderers_with_monkeypatched_vuio():
    def fake_list_renderers():
        return [{"id": "r1", "name": "Living Room"}]

    original = app_module.vuio_client.list_renderers
    app_module.vuio_client.list_renderers = fake_list_renderers
    try:
        with TestClient(app) as client:
            response = client.get("/api/renderers")
            assert response.status_code == 200
            data = response.json()
            assert data["renderers"] == [{"id": "r1", "name": "Living Room"}]
    finally:
        app_module.vuio_client.list_renderers = original


def test_vuio_error_surfaces_as_502():
    def fake_list_renderers():
        raise app_module.vuio_client.VuioError("boom")

    original = app_module.vuio_client.list_renderers
    app_module.vuio_client.list_renderers = fake_list_renderers
    try:
        with TestClient(app) as client:
            response = client.get("/api/renderers")
            assert response.status_code == 502
            assert "boom" in response.json()["detail"]
    finally:
        app_module.vuio_client.list_renderers = original


def test_cast_playlist_with_monkeypatched_vuio():
    calls = {}

    def fake_cast_playlist(playlist_id, renderer_id):
        calls["playlist_id"] = playlist_id
        calls["renderer_id"] = renderer_id

    original = app_module.vuio_client.cast_playlist
    app_module.vuio_client.cast_playlist = fake_cast_playlist
    try:
        with TestClient(app) as client:
            response = client.post("/api/playlists/42/cast", json={"renderer_id": "r1"})
            assert response.status_code == 200
            assert response.json() == {"status": "casting"}
            assert calls == {"playlist_id": 42, "renderer_id": "r1"}
    finally:
        app_module.vuio_client.cast_playlist = original


def test_playback_status_with_monkeypatched_vuio():
    def fake_get_playback_status(renderer_id=None):
        return {"renderer_id": renderer_id, "state": "playing"}

    original = app_module.vuio_client.get_playback_status
    app_module.vuio_client.get_playback_status = fake_get_playback_status
    try:
        with TestClient(app) as client:
            response = client.get("/api/playback-status", params={"renderer_id": "r1"})
            assert response.status_code == 200
            assert response.json() == {"renderer_id": "r1", "state": "playing"}
    finally:
        app_module.vuio_client.get_playback_status = original


if __name__ == "__main__":
    test_get_stats()
    test_get_presets()
    test_get_tracks_strips_embedding()
    test_preview_with_preset()
    test_preview_with_both_set_returns_400()
    test_preview_with_neither_set_returns_400()
    test_preview_unknown_preset_returns_400()
    test_preview_with_seed_path()
    test_preview_with_unknown_seed_path_returns_404()
    test_create_playlist_with_monkeypatched_vuio()
    test_get_renderers_with_monkeypatched_vuio()
    test_vuio_error_surfaces_as_502()
    test_cast_playlist_with_monkeypatched_vuio()
    test_playback_status_with_monkeypatched_vuio()
    print("All app tests passed.")
