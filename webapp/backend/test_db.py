import sqlite3
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


def test_load_ok_tracks_joins_preferences_and_leaves_unscored_null():
    path = _make_test_db()
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO preferences (path, song_key, plays, skips, score) VALUES (?, ?, ?, ?, ?)",
        ("/music/a.mp3", "artist|title", 100, 5, 4.2),
    )
    conn.commit()

    tracks = {t["path"]: t for t in db.load_ok_tracks(conn)}

    assert tracks["/music/a.mp3"]["score"] == 4.2
    assert tracks["/music/a.mp3"]["song_key"] == "artist|title"
    # Never imported -> None, so it sorts out of the way instead of ranking as 0.
    assert tracks["/music/b.mp3"]["score"] is None
    assert tracks["/music/b.mp3"]["song_key"] is None
    assert tracks["/music/b.mp3"]["percentile"] is None


def test_percentile_ranks_scores_among_scored_tracks_only():
    path = _make_test_db()
    conn = analysis_db.get_connection(path)
    for i in range(5):
        p = f"/music/p{i}.mp3"
        analysis_db.upsert_track(conn, p, mtime=1.0, size=100, status="ok")
        analysis_db.upsert_features(conn, p, {
            "bpm": 100.0, "key": "C major", "mood_happy": 0.5, "mood_aggressive": 0.5,
            "mood_relaxed": 0.5, "mood_party": 0.5, "danceability": 0.5,
            "embedding": np.ones(200, dtype=np.float32),
        })
    conn.close()
    conn = db.get_connection(path)
    for i in range(5):
        conn.execute(
            "INSERT INTO preferences (path, song_key, plays, skips, score) VALUES (?, ?, ?, ?, ?)",
            (f"/music/p{i}.mp3", f"song{i}", 10, 0, float(i)),
        )
    conn.commit()

    tracks = {t["path"]: t for t in db.load_ok_tracks(conn)}

    # PERCENT_RANK over 5 scores: lowest 0, highest 100.
    assert tracks["/music/p0.mp3"]["percentile"] == 0
    assert tracks["/music/p4.mp3"]["percentile"] == 100
    assert tracks["/music/p2.mp3"]["percentile"] == 50
    # The unscored tracks from the fixture must not dilute the ranking.
    assert tracks["/music/a.mp3"]["percentile"] is None


def test_record_play_accumulates_plays_and_skips_separately():
    path = _make_test_db()
    conn = db.get_connection(path)

    db.record_play(conn, "/music/a.mp3", seconds=180, completed=True)
    db.record_play(conn, "/music/a.mp3", seconds=5, completed=False)
    db.record_play(conn, "/music/a.mp3", seconds=200, completed=True)

    row = conn.execute(
        "SELECT plays, skips, seconds FROM local_plays WHERE path = ?", ("/music/a.mp3",)
    ).fetchone()
    assert row == (2, 1, 385)


def test_fetch_local_plays_is_most_recent_first():
    path = _make_test_db()
    conn = db.get_connection(path)
    db.record_play(conn, "/music/a.mp3", seconds=100, completed=True)
    time.sleep(0.01)
    db.record_play(conn, "/music/b.mp3", seconds=100, completed=True)

    assert [p["path"] for p in db.fetch_local_plays(conn)] == ["/music/b.mp3", "/music/a.mp3"]


def test_description_round_trips_alongside_the_recipe():
    path = _make_test_db()
    conn = db.get_connection(path)
    db.save_recipe(conn, 3, {"mode": "manual", "limit": 30})

    db.save_description(conn, 3, "Treibende Gitarren für den Feierabend.")

    assert db.load_description(conn, 3) == "Treibende Gitarren für den Feierabend."
    # Saving a description must not clobber the recipe it sits next to.
    assert db.load_recipe(conn, 3) == {"mode": "manual", "limit": 30}


def test_description_works_without_a_recipe():
    """A hand-built playlist has no recipe but can still be described."""
    path = _make_test_db()
    conn = db.get_connection(path)

    db.save_description(conn, 9, "Von Hand zusammengestellt.")

    assert db.load_description(conn, 9) == "Von Hand zusammengestellt."
    assert db.load_description(conn, 404) is None


def test_refreshing_replaces_the_description():
    path = _make_test_db()
    conn = db.get_connection(path)
    db.save_description(conn, 3, "Alte Beschreibung")
    db.save_description(conn, 3, "Neue Beschreibung")
    assert db.load_description(conn, 3) == "Neue Beschreibung"


def test_display_parses_the_usual_layout():
    d = db.display_of("/music/Amorphis - Halo/06. Amorphis - When The Gods Came.flac")
    assert d == {"artist": "Amorphis", "album": "Halo", "title": "When The Gods Came"}


def test_display_prefers_the_filename_artist_on_compilations():
    """The folder names the compilation, the filename names who plays it."""
    d = db.display_of("/music/Various Artists - Hits 95/03. Nena - 99 Luftballons.flac")
    assert d["artist"] == "Nena"
    assert d["album"] == "Hits 95"


def test_display_handles_track_number_variants():
    for stem, expected in [("1. A - X", "X"), ("03. A - X", "X"),
                           ("406. A - X", "X"), ("6 - A - X", "X")]:
        assert db.display_of(f"/music/A - Alb/{stem}.flac")["title"] == expected


def test_display_survives_a_filename_without_the_dash():
    """2.5% of the library does not follow the pattern; show something sane."""
    d = db.display_of("/music/DUNE - Dune/04 Future Is Now.flac")
    assert d == {"artist": "DUNE", "album": "Dune", "title": "Future Is Now"}


def test_display_never_leaks_a_path():
    for path in ["/music/loose.flac", "loose.flac", ""]:
        values = db.display_of(path).values()
        assert not any("/" in v for v in values), path


def test_fingerprint_changes_when_a_track_is_analysed():
    """The watcher reloads on this, so it has to move when the library does."""
    path = _make_test_db()
    conn = db.get_connection(path)
    before = db.library_fingerprint(conn)

    analysis_db.upsert_track(conn, "/music/new.mp3", mtime=1.0, size=100, status="ok")
    analysis_db.upsert_features(conn, "/music/new.mp3", {
        "bpm": 128.0, "key": "D minor", "mood_happy": 0.5, "mood_aggressive": 0.5,
        "mood_relaxed": 0.5, "mood_party": 0.5, "danceability": 0.5,
        "embedding": np.ones(200, dtype=np.float32),
    })

    assert db.library_fingerprint(conn) != before


def test_fingerprint_is_stable_when_nothing_changed():
    path = _make_test_db()
    conn = db.get_connection(path)
    assert db.library_fingerprint(conn) == db.library_fingerprint(conn)


def test_schedule_round_trips_and_updates_in_place():
    path = _make_test_db()
    conn = db.get_connection(path)

    db.save_schedule(conn, 3, "Wochenmix", weekday=1, hour=6, minute=17)
    db.save_schedule(conn, 4, "Energiegeladen", weekday=4, hour=17, minute=43)
    rows = db.list_schedules(conn)

    assert [r["name"] for r in rows] == ["Wochenmix", "Energiegeladen"]
    assert rows[0]["enabled"] is True
    assert rows[0]["last_run"] is None

    db.save_schedule(conn, 3, "Wochenmix", weekday=2, hour=8, minute=0, enabled=False)
    again = db.list_schedules(conn)
    assert len(again) == 2
    updated = next(r for r in again if r["playlist_id"] == 3)
    assert (updated["weekday"], updated["hour"], updated["enabled"]) == (2, 8, False)


def test_editing_a_schedule_keeps_its_last_run():
    """Otherwise changing the time would make it fire again straight away."""
    path = _make_test_db()
    conn = db.get_connection(path)
    db.save_schedule(conn, 3, "Wochenmix", weekday=1, hour=6, minute=17)
    db.mark_schedule_run(conn, 3, "40 Tracks")
    before = db.list_schedules(conn)[0]["last_run"]

    db.save_schedule(conn, 3, "Wochenmix", weekday=3, hour=9, minute=30)

    after = db.list_schedules(conn)[0]
    assert after["last_run"] == before
    assert after["last_result"] == "40 Tracks"


def test_delete_schedule_reports_what_it_removed():
    path = _make_test_db()
    conn = db.get_connection(path)
    db.save_schedule(conn, 3, "Wochenmix", weekday=1, hour=6, minute=17)

    assert db.delete_schedule(conn, 3) == 1
    assert db.delete_schedule(conn, 3) == 0
    assert db.list_schedules(conn) == []


def test_recipe_round_trips_and_overwrites():
    path = _make_test_db()
    conn = db.get_connection(path)

    assert db.load_recipe(conn, 7) is None
    db.save_recipe(conn, 7, {"mode": "manual", "limit": 30})
    assert db.load_recipe(conn, 7) == {"mode": "manual", "limit": 30}
    # Refreshing with new criteria replaces the recipe rather than adding one.
    db.save_recipe(conn, 7, {"mode": "seed", "seed_path": "/music/a.mp3"})
    assert db.load_recipe(conn, 7) == {"mode": "seed", "seed_path": "/music/a.mp3"}
    assert conn.execute("SELECT COUNT(*) FROM playlist_recipes").fetchone()[0] == 1


def test_recent_ok_tracks_orders_by_last_scanned_desc():
    path = _make_test_db()
    conn = db.get_connection(path)

    recent = db.recent_ok_tracks(conn, limit=10)

    assert [t["path"] for t in recent] == ["/music/b.mp3", "/music/a.mp3"]
    assert recent[0]["bpm"] == 90.0


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


def test_rating_overrides_taste_percentile_and_survives_clearing():
    path = _make_test_db()
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO preferences (path, song_key, plays, skips, score) "
        "VALUES ('/music/a.mp3', 'a', 10, 0, 2.4)"
    )
    conn.commit()
    apple = next(t for t in db.load_ok_tracks(conn)
                 if t["path"] == "/music/a.mp3")["percentile"]

    db.set_rating(conn, "/music/b.mp3", 1)
    db.set_rating(conn, "/music/a.mp3", -1)
    by_path = {t["path"]: t for t in db.load_ok_tracks(conn)}
    assert by_path["/music/b.mp3"]["percentile"] == db.FAVOURITE_PERCENTILE
    assert by_path["/music/a.mp3"]["percentile"] == db.BANNED_PERCENTILE

    # clearing restores what Apple said, rather than leaving the override
    db.set_rating(conn, "/music/a.mp3", 0)
    cleared = next(t for t in db.load_ok_tracks(conn) if t["path"] == "/music/a.mp3")
    assert cleared["percentile"] == apple
    assert cleared["rating"] == 0
    assert db.load_ratings(conn) == {"/music/b.mp3": 1}


def test_ratings_survive_a_preferences_reimport():
    """import_preferences wipes `preferences` wholesale; hand ratings must not
    be collateral damage."""
    path = _make_test_db()
    conn = db.get_connection(path)
    db.set_rating(conn, "/music/a.mp3", 1)

    conn.execute("DELETE FROM preferences")  # what the Apple import does first
    conn.commit()

    assert db.load_ratings(conn) == {"/music/a.mp3": 1}


def test_counted_plays_rank_like_apple_plays():
    """A play in the player must count exactly as one in Apple Music: both
    feed the same score, so neither source outranks the other."""
    path = _make_test_db()
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO preferences (path, song_key, plays, skips, score) "
        "VALUES ('/music/a.mp3', 'a', 4, 0, ?)", (db.score_of(4, 0),)
    )
    conn.commit()

    for _ in range(4):
        db.count_play(conn, "/music/b.mp3")
    by_path = {t["path"]: t for t in db.load_ok_tracks(conn)}
    assert by_path["/music/b.mp3"]["score"] == by_path["/music/a.mp3"]["score"]

    # a fifth play puts it ahead, and the percentile follows the score
    db.count_play(conn, "/music/b.mp3")
    by_path = {t["path"]: t for t in db.load_ok_tracks(conn)}
    assert by_path["/music/b.mp3"]["score"] > by_path["/music/a.mp3"]["score"]
    assert by_path["/music/b.mp3"]["percentile"] > by_path["/music/a.mp3"]["percentile"]


def test_counted_plays_add_to_apple_plays_for_the_same_track():
    path = _make_test_db()
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO preferences (path, song_key, plays, skips, score) "
        "VALUES ('/music/a.mp3', 'a', 3, 1, ?)", (db.score_of(3, 1),)
    )
    conn.commit()

    db.count_play(conn, "/music/a.mp3")
    db.count_play(conn, "/music/a.mp3", skipped=True)
    a = next(t for t in db.load_ok_tracks(conn) if t["path"] == "/music/a.mp3")
    assert a["score"] == db.score_of(4, 2)


def test_skips_lower_the_score_and_plays_survive_a_reimport():
    path = _make_test_db()
    conn = db.get_connection(path)
    for _ in range(3):
        db.count_play(conn, "/music/a.mp3")
    db.count_play(conn, "/music/b.mp3")
    db.count_play(conn, "/music/b.mp3")
    db.count_play(conn, "/music/b.mp3")
    db.count_play(conn, "/music/b.mp3", skipped=True)

    by_path = {t["path"]: t for t in db.load_ok_tracks(conn)}
    assert by_path["/music/b.mp3"]["score"] < by_path["/music/a.mp3"]["score"]

    conn.execute("DELETE FROM preferences")  # what the Apple import does first
    conn.commit()
    assert db.load_plays(conn)["/music/a.mp3"] == (3, 0)


def test_unplayed_tracks_keep_a_null_score():
    """Never ranked below disliked music - that is what null is for."""
    path = _make_test_db()
    conn = db.get_connection(path)
    assert all(t["score"] is None for t in db.load_ok_tracks(conn))


def test_webapp_migrates_tracks_when_analysis_has_not_yet():
    """The webapp must boot against a database the analysis service has not
    upgraded yet -- it starts first about half the time, and a missing column
    is a crash on startup, not a degraded playlist."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    pre = sqlite3.connect(tmp.name)
    pre.executescript(
        """
        CREATE TABLE tracks (path TEXT PRIMARY KEY, mtime REAL NOT NULL,
          size INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          last_scanned REAL NOT NULL);
        CREATE TABLE features (path TEXT PRIMARY KEY, bpm REAL, key TEXT,
          mood_happy REAL, mood_aggressive REAL, mood_relaxed REAL,
          mood_party REAL, danceability REAL, embedding BLOB);
        INSERT INTO tracks VALUES ('/music/a.mp3', 12345.0, 10, 'ok', 99999.0);
        """
    )
    pre.commit()
    pre.close()

    conn = db.get_connection(tmp.name)
    assert conn.execute("SELECT first_seen FROM tracks").fetchone()[0] == 12345.0
    db.load_ok_tracks(conn)      # the query that failed on the host
    db.get_connection(tmp.name)  # idempotent


def test_connecting_to_an_empty_database_does_not_fail():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db.get_connection(tmp.name)  # analysis will create tracks later


if __name__ == "__main__":
    test_webapp_migrates_tracks_when_analysis_has_not_yet()
    test_connecting_to_an_empty_database_does_not_fail()
    test_counted_plays_rank_like_apple_plays()
    test_counted_plays_add_to_apple_plays_for_the_same_track()
    test_skips_lower_the_score_and_plays_survive_a_reimport()
    test_unplayed_tracks_keep_a_null_score()
    test_rating_overrides_taste_percentile_and_survives_clearing()
    test_ratings_survive_a_preferences_reimport()
    test_fetch_stats_counts_status_and_aggregates()
    test_load_ok_tracks_returns_only_ok_with_embedding()
    test_load_ok_tracks_joins_preferences_and_leaves_unscored_null()
    test_percentile_ranks_scores_among_scored_tracks_only()
    test_description_round_trips_alongside_the_recipe()
    test_description_works_without_a_recipe()
    test_refreshing_replaces_the_description()
    test_display_parses_the_usual_layout()
    test_display_prefers_the_filename_artist_on_compilations()
    test_display_handles_track_number_variants()
    test_display_survives_a_filename_without_the_dash()
    test_display_never_leaks_a_path()
    test_fingerprint_changes_when_a_track_is_analysed()
    test_fingerprint_is_stable_when_nothing_changed()
    test_schedule_round_trips_and_updates_in_place()
    test_editing_a_schedule_keeps_its_last_run()
    test_delete_schedule_reports_what_it_removed()
    test_recipe_round_trips_and_overwrites()
    test_recent_ok_tracks_orders_by_last_scanned_desc()
    test_search_ok_tracks_matches_substring()
    test_search_failed_tracks_returns_error_message_and_total()
    test_search_failed_tracks_filters_by_query()
    test_search_failed_tracks_paginates_with_limit_and_offset()
    test_retry_failed_tracks_resets_status_and_clears_error()
    print("All db tests passed.")
