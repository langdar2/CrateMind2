import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from crate_mind.analysis import db


def test_get_connection_adds_error_message_column_to_existing_table():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    # Simulate a pre-existing DB from before this feature: tracks table
    # without error_message, already containing a failed row.
    legacy_conn = sqlite3.connect(tmp.name)
    legacy_conn.executescript(
        """
        CREATE TABLE tracks (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            last_scanned REAL NOT NULL
        );
        """
    )
    legacy_conn.execute(
        "INSERT INTO tracks (path, mtime, size, status, last_scanned) VALUES (?, ?, ?, ?, ?)",
        ("/music/old-failed.mp3", 1.0, 100, "failed", 1.0),
    )
    legacy_conn.commit()
    legacy_conn.close()

    conn = db.get_connection(tmp.name)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()}
    assert "error_message" in columns


def test_get_connection_is_idempotent_when_column_already_exists():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    conn1 = db.get_connection(tmp.name)
    conn1.close()

    # Reconnecting must not raise "duplicate column name".
    conn2 = db.get_connection(tmp.name)
    columns = {row[1] for row in conn2.execute("PRAGMA table_info(tracks)").fetchall()}
    assert "error_message" in columns


def test_upsert_track_sets_error_message_on_failed():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = db.get_connection(tmp.name)

    db.upsert_track(conn, "/music/bad.mp3", mtime=1.0, size=100, status="failed", error_message="boom")

    row = conn.execute("SELECT status, error_message FROM tracks WHERE path = ?", ("/music/bad.mp3",)).fetchone()
    assert row == ("failed", "boom")


def test_upsert_track_clears_error_message_on_ok():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = db.get_connection(tmp.name)

    db.upsert_track(conn, "/music/a.mp3", mtime=1.0, size=100, status="failed", error_message="boom")
    db.upsert_track(conn, "/music/a.mp3", mtime=2.0, size=200, status="ok")

    row = conn.execute("SELECT status, error_message FROM tracks WHERE path = ?", ("/music/a.mp3",)).fetchone()
    assert row == ("ok", None)


def test_reset_failed_without_reason_resets_to_pending():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = db.get_connection(tmp.name)

    db.upsert_track(conn, "/music/old.mp3", mtime=1.0, size=100, status="failed", error_message=None)
    db.upsert_track(conn, "/music/new.mp3", mtime=1.0, size=100, status="failed", error_message="boom")

    db.reset_failed_without_reason(conn)

    old_status = conn.execute("SELECT status FROM tracks WHERE path = ?", ("/music/old.mp3",)).fetchone()[0]
    new_status = conn.execute("SELECT status FROM tracks WHERE path = ?", ("/music/new.mp3",)).fetchone()[0]
    assert old_status == "pending"
    assert new_status == "failed"


if __name__ == "__main__":
    test_get_connection_adds_error_message_column_to_existing_table()
    test_get_connection_is_idempotent_when_column_already_exists()
    test_upsert_track_sets_error_message_on_failed()
    test_upsert_track_clears_error_message_on_ok()
    test_reset_failed_without_reason_resets_to_pending()
    print("All analysis db tests passed.")
