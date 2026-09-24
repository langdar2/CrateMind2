import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np

from crate_mind.analysis import db as analysis_db
import db


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


def test_fetch_stats_counts_status_and_aggregates():
    path = _make_test_db()
    conn = db.get_connection(path)

    stats = db.fetch_stats(conn)

    assert stats["status_counts"]["ok"] == 2
    assert stats["status_counts"]["failed"] == 1
    assert stats["key_counts"] == {"C major": 1, "A minor": 1}
    assert any(b["bucket"] == "120-140" and b["count"] == 1 for b in stats["bpm_histogram"])
    assert any(b["bucket"] == "80-100" and b["count"] == 1 for b in stats["bpm_histogram"])
    assert abs(stats["mood_averages"]["mood_happy"] - 0.55) < 1e-6


def test_load_ok_tracks_returns_only_ok_with_embedding():
    path = _make_test_db()
    conn = db.get_connection(path)

    tracks = db.load_ok_tracks(conn)

    assert {t["path"] for t in tracks} == {"/music/a.mp3", "/music/b.mp3"}
    a = next(t for t in tracks if t["path"] == "/music/a.mp3")
    assert a["embedding"].shape == (200,)
    assert a["bpm"] == 120.0


def test_search_ok_tracks_matches_substring():
    path = _make_test_db()
    conn = db.get_connection(path)

    results = db.search_ok_tracks(conn, "a.mp3")

    assert [r["path"] for r in results] == ["/music/a.mp3"]


if __name__ == "__main__":
    test_fetch_stats_counts_status_and_aggregates()
    test_load_ok_tracks_returns_only_ok_with_embedding()
    test_search_ok_tracks_matches_substring()
    print("All db tests passed.")
