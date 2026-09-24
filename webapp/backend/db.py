import sqlite3

import numpy as np

MOOD_COLUMNS = ["mood_happy", "mood_aggressive", "mood_relaxed", "mood_party", "danceability"]


def get_connection(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)


def _bpm_histogram(bpms: list, bucket_size: int = 20) -> list:
    buckets = {}
    for bpm in bpms:
        lo = int(bpm // bucket_size) * bucket_size
        label = f"{lo}-{lo + bucket_size}"
        buckets[label] = buckets.get(label, 0) + 1
    return [
        {"bucket": label, "count": count}
        for label, count in sorted(buckets.items(), key=lambda kv: int(kv[0].split("-")[0]))
    ]


def fetch_stats(conn: sqlite3.Connection) -> dict:
    status_counts = dict(conn.execute("SELECT status, COUNT(*) FROM tracks GROUP BY status").fetchall())

    bpms = [row[0] for row in conn.execute("SELECT bpm FROM features WHERE bpm IS NOT NULL").fetchall()]
    key_counts = {}
    for (key,) in conn.execute("SELECT key FROM features WHERE key IS NOT NULL").fetchall():
        key_counts[key] = key_counts.get(key, 0) + 1

    mood_averages = {}
    for column in MOOD_COLUMNS:
        avg = conn.execute(f"SELECT AVG({column}) FROM features WHERE {column} IS NOT NULL").fetchone()[0]
        mood_averages[column] = avg if avg is not None else 0.0

    return {
        "status_counts": status_counts,
        "bpm_histogram": _bpm_histogram(bpms),
        "key_counts": key_counts,
        "mood_averages": mood_averages,
    }


def load_ok_tracks(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        """
        SELECT t.path, f.bpm, f.key, f.mood_happy, f.mood_aggressive, f.mood_relaxed,
               f.mood_party, f.danceability, f.embedding
        FROM tracks t JOIN features f ON f.path = t.path
        WHERE t.status = 'ok' AND f.embedding IS NOT NULL
        """
    ).fetchall()

    tracks = []
    for path, bpm, key, happy, aggressive, relaxed, party, dance, emb_blob in rows:
        tracks.append({
            "path": path,
            "bpm": bpm,
            "key": key,
            "mood_happy": happy,
            "mood_aggressive": aggressive,
            "mood_relaxed": relaxed,
            "mood_party": party,
            "danceability": dance,
            "embedding": np.frombuffer(emb_blob, dtype=np.float32),
        })
    return tracks


def search_ok_tracks(conn: sqlite3.Connection, query: str, limit: int = 20) -> list:
    like = f"%{query}%"
    rows = conn.execute(
        """
        SELECT t.path, f.bpm, f.key
        FROM tracks t JOIN features f ON f.path = t.path
        WHERE t.status = 'ok' AND t.path LIKE ?
        LIMIT ?
        """,
        (like, limit),
    ).fetchall()
    return [{"path": path, "bpm": bpm, "key": key} for path, bpm, key in rows]
