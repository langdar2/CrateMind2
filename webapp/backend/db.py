import json
import math
import sqlite3
import time

import numpy as np


def score_of(plays: float, skips: float) -> float:
    """Taste score from play and skip counts, each already aged-weighted.

    log() damps the long tail - 200 plays is not 50x the preference of 4 plays,
    and without it a handful of heavy-rotation artists swamp everything. The
    second factor is a skip *ratio*, not a skip count: favourites get skipped a
    lot simply because they come up a lot, so penalising absolute skips would
    punish exactly the tracks we want to surface.

    Lives here rather than in scripts/import_preferences.py, which imports it:
    the webapp image ships only webapp/backend, so a copy there would be the
    one that drifts.
    """
    if plays <= 0:
        return 0.0
    return math.log(1 + plays) * (1 - skips / (plays + skips))

MOOD_COLUMNS = ["mood_happy", "mood_aggressive", "mood_relaxed", "mood_party", "danceability"]


def artist_of(path: str) -> str:
    """Artist from the folder name, which is laid out as "Artist - Album".

    Deliberately not taken from the Apple match: that is missing for most of
    the library and wrong for about a tenth of what it does cover, whereas the
    folder name is present for 99.9% of files and is what the file itself says.
    Compilation folders all collapse to "various artists", which caps a
    sampler at the same five tracks - fine for the purpose.
    """
    folder = path.rsplit("/", 2)[-2] if path.count("/") >= 2 else ""
    return folder.split(" - ")[0].strip().lower()


def get_connection(db_path: str) -> sqlite3.Connection:
    # ponytail: one shared connection across FastAPI's threadpool; relies on
    # sqlite3's default serialized threading mode. Fine for this single-user
    # home-network app; switch to one connection per request if that
    # assumption ever needs checking. Read-write (not mode=ro) so the retry
    # endpoint can flip failed tracks back to pending.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    # Written by scripts/import_preferences.py, which may never have run on this
    # machine; create it empty so the LEFT JOIN below does not blow up.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preferences (
            path TEXT PRIMARY KEY REFERENCES tracks(path),
            song_key TEXT NOT NULL,
            plays INTEGER NOT NULL,
            skips INTEGER NOT NULL,
            score REAL NOT NULL
        )
        """
    )
    # Plays counted by the player as they happen. Like `ratings`, kept out of
    # `preferences`, which import_preferences rebuilds wholesale from Apple's
    # export; these are the plays Apple never sees.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plays (
            path TEXT PRIMARY KEY,
            plays INTEGER NOT NULL DEFAULT 0,
            skips INTEGER NOT NULL DEFAULT 0,
            last_played REAL NOT NULL
        )
        """
    )
    # Ratings the user gave by hand, in the player or here. Deliberately NOT
    # in `preferences`: that table is rebuilt wholesale by import_preferences
    # (DELETE then INSERT), which would throw hand-made ratings away on the
    # next Apple import. Keyed by path like everything else; rating is +1 for
    # a favourite and -1 for a thumbs-down.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ratings (
            path TEXT PRIMARY KEY,
            rating INTEGER NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    # Playlist recipes are webapp state rather than analysis output, but a
    # second database file for one small table is not worth the moving parts.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS playlist_recipes (
            playlist_id INTEGER PRIMARY KEY,
            recipe TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save_recipe(conn: sqlite3.Connection, playlist_id: int, recipe: dict) -> None:
    conn.execute(
        """
        INSERT INTO playlist_recipes (playlist_id, recipe, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(playlist_id) DO UPDATE SET
            recipe = excluded.recipe, updated_at = excluded.updated_at
        """,
        (playlist_id, json.dumps(recipe), time.time()),
    )
    conn.commit()


def load_recipe(conn: sqlite3.Connection, playlist_id: int):
    row = conn.execute(
        "SELECT recipe FROM playlist_recipes WHERE playlist_id = ?", (playlist_id,)
    ).fetchone()
    return json.loads(row[0]) if row else None


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


# What a hand-rated track counts as on the 0-100 taste scale. A favourite
# rates like the best-liked music in the library rather than above it, so one
# click does not outrank a lifetime of plays; a thumbs-down goes to the floor.
FAVOURITE_PERCENTILE = 95.0
BANNED_PERCENTILE = 0.0


def rated_percentile(played_percentile, rating: int):
    """Taste percentile once a hand rating is taken into account.

    A hand rating speaks for the whole song, so it also stands in for a track
    nothing has ever played. Clearing it restores the rank the plays earned.
    """
    if rating > 0:
        return FAVOURITE_PERCENTILE
    if rating < 0:
        return BANNED_PERCENTILE
    return played_percentile


def _percentiles(scores: dict) -> dict:
    """Rank scores 0-100, matching SQL's PERCENT_RANK: share of tracks strictly
    below each score, so ties share a rank and the lowest scores land at 0."""
    if len(scores) < 2:
        return {p: 0.0 for p in scores}
    ordered = sorted(scores.values())
    n = len(ordered) - 1
    below = {}
    for i, s in enumerate(ordered):
        below.setdefault(s, i)  # first index of this score = how many are below
    return {p: round(below[s] / n * 100) for p, s in scores.items()}


def count_play(conn: sqlite3.Connection, path: str, skipped: bool = False) -> dict:
    """Record one play (or skip) of a track by the player."""
    col = "skips" if skipped else "plays"
    conn.execute(
        f"INSERT INTO plays (path, {col}, last_played) VALUES (?, 1, ?) "
        f"ON CONFLICT(path) DO UPDATE SET {col} = {col} + 1, "
        "last_played = excluded.last_played",
        (path, time.time()),
    )
    conn.commit()
    row = conn.execute("SELECT plays, skips FROM plays WHERE path = ?", (path,)).fetchone()
    return {"path": path, "plays": row[0], "skips": row[1]}


def load_plays(conn: sqlite3.Connection) -> dict:
    return {p: (pl, sk) for p, pl, sk
            in conn.execute("SELECT path, plays, skips FROM plays").fetchall()}


def set_rating(conn: sqlite3.Connection, path: str, rating: int) -> None:
    """Record +1 (favourite) or -1 (thumbs-down); 0 clears the rating."""
    if rating == 0:
        conn.execute("DELETE FROM ratings WHERE path = ?", (path,))
    else:
        conn.execute(
            "INSERT INTO ratings (path, rating, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET rating = excluded.rating, "
            "updated_at = excluded.updated_at",
            (path, 1 if rating > 0 else -1, time.time()),
        )
    conn.commit()


def load_ratings(conn: sqlite3.Connection) -> dict:
    return dict(conn.execute("SELECT path, rating FROM ratings").fetchall())


def load_ok_tracks(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        """
        SELECT t.path, f.bpm, f.key, f.mood_happy, f.mood_aggressive, f.mood_relaxed,
               f.mood_party, f.danceability, f.embedding,
               p.plays, p.skips, p.score, p.song_key
        FROM tracks t
        JOIN features f ON f.path = t.path
        LEFT JOIN preferences p ON p.path = t.path
        WHERE t.status = 'ok' AND f.embedding IS NOT NULL
        """
    ).fetchall()

    ratings = load_ratings(conn)
    # Plays this player counted are added to Apple's before scoring, so a
    # track played here ranks exactly like one played in Apple Music. The
    # percentile is therefore ranked in Python rather than SQL: the window
    # function could only see the stored preferences score, which these plays
    # are not part of.
    counted = load_plays(conn)
    scores = {}
    for row in rows:
        path, apple_plays, apple_skips, apple_score = row[0], row[9], row[10], row[11]
        extra_plays, extra_skips = counted.get(path, (0, 0))
        if not extra_plays and not extra_skips:
            if apple_score is not None:
                scores[path] = apple_score
            continue
        scores[path] = score_of((apple_plays or 0) + extra_plays,
                                (apple_skips or 0) + extra_skips)
    percentiles = _percentiles(scores)

    tracks = []
    for (path, bpm, key, happy, aggressive, relaxed, party, dance, emb_blob,
         _apple_plays, _apple_skips, _apple_score, song_key) in rows:
        rating = ratings.get(path, 0)
        score = scores.get(path)  # None while nothing has ever played it
        percentile = percentiles.get(path)
        tracks.append({
            "path": path,
            "bpm": bpm,
            "key": key,
            "mood_happy": happy,
            "mood_aggressive": aggressive,
            "mood_relaxed": relaxed,
            "mood_party": party,
            "danceability": dance,
            # None for anything the Apple import could not score - deliberately
            # not 0.0, which would rank unplayed music below disliked music.
            # score is the precise internal value used for ordering; percentile
            # is its rank among scored tracks, which is what users can read.
            "score": score,
            "percentile": rated_percentile(percentile, rating),
            # kept so clearing a rating can restore the play-based rank
            "played_percentile": percentile,
            "rating": rating,
            "song_key": song_key,
            "artist": artist_of(path),
            "embedding": np.frombuffer(emb_blob, dtype=np.float32),
        })
    return tracks


def recent_ok_tracks(conn: sqlite3.Connection, limit: int = 10) -> list:
    rows = conn.execute(
        """
        SELECT t.path, f.bpm, f.key, f.mood_happy, f.mood_aggressive, f.mood_relaxed,
               f.mood_party, f.danceability, t.last_scanned
        FROM tracks t JOIN features f ON f.path = t.path
        WHERE t.status = 'ok'
        ORDER BY t.last_scanned DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "path": path, "bpm": bpm, "key": key, "mood_happy": happy,
            "mood_aggressive": aggressive, "mood_relaxed": relaxed, "mood_party": party,
            "danceability": dance, "analyzed_at": last_scanned,
        }
        for path, bpm, key, happy, aggressive, relaxed, party, dance, last_scanned in rows
    ]


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


def search_failed_tracks(conn: sqlite3.Connection, query: str = "", limit: int = 50, offset: int = 0) -> dict:
    like = f"%{query}%"
    total = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE status = 'failed' AND path LIKE ?",
        (like,),
    ).fetchone()[0]
    rows = conn.execute(
        """
        SELECT path, error_message
        FROM tracks
        WHERE status = 'failed' AND path LIKE ?
        ORDER BY path
        LIMIT ? OFFSET ?
        """,
        (like, limit, offset),
    ).fetchall()
    return {
        "tracks": [{"path": path, "error_message": error_message} for path, error_message in rows],
        "total": total,
    }


def retry_failed_tracks(conn: sqlite3.Connection) -> int:
    cur = conn.execute("UPDATE tracks SET status = 'pending', error_message = NULL WHERE status = 'failed'")
    conn.commit()
    return cur.rowcount
