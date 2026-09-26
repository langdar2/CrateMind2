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


def test_search_failed_tracks_returns_error_message_and_total():
    path = _make_test_db()
    conn = analysis_db.get_connection(path)
    analysis_db.upsert_track(conn, "/music/c.mp3", mtime=1.0, size=100, status="failed", error_message="decode error")
    conn.close()
    conn = db.get_connection(path)

    result = db.search_failed_tracks(conn)

    assert result["total"] == 1
    assert result["tracks"] == [{"path": "/music/c.mp3", "error_message": "decode error"}]


def test_search_failed_tracks_filters_by_query():
    path = _make_test_db()
    conn = analysis_db.get_connection(path)
    analysis_db.upsert_track(conn, "/music/c.mp3", mtime=1.0, size=100, status="failed", error_message="decode error")
    analysis_db.upsert_track(conn, "/music/d.mp3", mtime=1.0, size=100, status="failed", error_message="io error")
    conn.close()
    conn = db.get_connection(path)

    result = db.search_failed_tracks(conn, query="d.mp3")

    assert result["total"] == 1
    assert result["tracks"][0]["path"] == "/music/d.mp3"


def test_search_failed_tracks_paginates_with_limit_and_offset():
    path = _make_test_db()
    conn = analysis_db.get_connection(path)
    analysis_db.upsert_track(conn, "/music/c.mp3", mtime=1.0, size=100, status="failed", error_message="e1")
    analysis_db.upsert_track(conn, "/music/d.mp3", mtime=1.0, size=100, status="failed", error_message="e2")
    analysis_db.upsert_track(conn, "/music/e.mp3", mtime=1.0, size=100, status="failed", error_message="e3")
    conn.close()
    conn = db.get_connection(path)

    page1 = db.search_failed_tracks(conn, limit=2, offset=0)
    page2 = db.search_failed_tracks(conn, limit=2, offset=2)

    assert page1["total"] == 3
    assert len(page1["tracks"]) == 2
    assert page2["total"] == 3
    assert len(page2["tracks"]) == 1


def test_retry_failed_tracks_resets_status_and_clears_error():
    path = _make_test_db()
    conn = analysis_db.get_connection(path)
    analysis_db.upsert_track(conn, "/music/c.mp3", mtime=1.0, size=100, status="failed", error_message="decode error")
    conn.close()
    conn = db.get_connection(path)

    retried = db.retry_failed_tracks(conn)

    assert retried == 1
    assert db.search_failed_tracks(conn)["total"] == 0
    row = conn.execute("SELECT status, error_message FROM tracks WHERE path = ?", ("/music/c.mp3",)).fetchone()
    assert row == ("pending", None)


if __name__ == "__main__":
    test_fetch_stats_counts_status_and_aggregates()
    test_load_ok_tracks_returns_only_ok_with_embedding()
    test_search_ok_tracks_matches_substring()
    test_search_failed_tracks_returns_error_message_and_total()
    test_search_failed_tracks_filters_by_query()
    test_search_failed_tracks_paginates_with_limit_and_offset()
    test_retry_failed_tracks_resets_status_and_clears_error()
    print("All db tests passed.")
