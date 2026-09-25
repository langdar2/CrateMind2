import sqlite3
import time
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tracks (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_scanned REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS features (
    path TEXT PRIMARY KEY REFERENCES tracks(path),
    bpm REAL,
    key TEXT,
    mood_happy REAL,
    mood_aggressive REAL,
    mood_relaxed REAL,
    mood_party REAL,
    danceability REAL,
    embedding BLOB
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()}
    if "error_message" not in columns:
        conn.execute("ALTER TABLE tracks ADD COLUMN error_message TEXT")
        conn.commit()
    return conn


def get_track_row(conn: sqlite3.Connection, path: str):
    row = conn.execute(
        "SELECT mtime, size, status FROM tracks WHERE path = ?", (path,)
    ).fetchone()
    if row is None:
        return None
    return {"mtime": row[0], "size": row[1], "status": row[2]}


def all_track_paths(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT path FROM tracks").fetchall()
    return {r[0] for r in rows}


def upsert_track(
    conn: sqlite3.Connection, path: str, mtime: float, size: int, status: str, error_message: str = None
) -> None:
    conn.execute(
        """
        INSERT INTO tracks (path, mtime, size, status, last_scanned, error_message)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            mtime = excluded.mtime,
            size = excluded.size,
            status = excluded.status,
            last_scanned = excluded.last_scanned,
            error_message = excluded.error_message
        """,
        (path, mtime, size, status, time.time(), error_message),
    )
    conn.commit()


def reset_failed_without_reason(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE tracks SET status = 'pending' WHERE status = 'failed' AND error_message IS NULL")
    conn.commit()


def upsert_features(conn: sqlite3.Connection, path: str, features: dict) -> None:
    conn.execute(
        """
        INSERT INTO features
            (path, bpm, key, mood_happy, mood_aggressive, mood_relaxed, mood_party, danceability, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            bpm = excluded.bpm,
            key = excluded.key,
            mood_happy = excluded.mood_happy,
            mood_aggressive = excluded.mood_aggressive,
            mood_relaxed = excluded.mood_relaxed,
            mood_party = excluded.mood_party,
            danceability = excluded.danceability,
            embedding = excluded.embedding
        """,
        (
            path,
            features["bpm"],
            features["key"],
            features["mood_happy"],
            features["mood_aggressive"],
            features["mood_relaxed"],
            features["mood_party"],
            features["danceability"],
            features["embedding"].tobytes(),
        ),
    )
    conn.commit()


def delete_features(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM features WHERE path = ?", (path,))
    conn.commit()


def delete_track(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM features WHERE path = ?", (path,))
    conn.execute("DELETE FROM tracks WHERE path = ?", (path,))
    conn.commit()
