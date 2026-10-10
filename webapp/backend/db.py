import json
import math
import re
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


# "01. ", "1 - ", "406. " - the track number some filenames carry up front.
_TRACK_NUMBER = re.compile(r"^\s*\d+\s*[.\-)]?\s+")


def display_of(path: str) -> dict:
    """Artist, album and title for display, parsed from the path.

    The database stores paths and nothing else - no tags are read during
    analysis - so the layout is the only source: "Artist - Album/NN. Artist
    - Title.ext". It holds for 99.9% of folders and 97.5% of filenames here.
    Anything that does not parse falls back to the bare filename, which is
    still better than showing a full path.
    """
    folder = path.rsplit("/", 2)[-2] if path.count("/") >= 2 else ""
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    album = folder.split(" - ", 1)[1].strip() if " - " in folder else folder.strip()
    name = _TRACK_NUMBER.sub("", stem)
    # Filenames repeat the artist; prefer that one, since a compilation folder
    # names the compilation rather than whoever plays this particular track.
    if " - " in name:
        artist, title = name.split(" - ", 1)
    else:
        artist, title = folder.split(" - ")[0].strip(), name
    # One file in the library is named only after its artists, leaving nothing
    # for the title; the filename stem beats an empty row in the list.
    return {"artist": artist.strip(), "album": album, "title": title.strip() or stem}


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
    # The analysis service owns `tracks` and migrates it on ITS next start,
    # which may be after this one -- and a missing column here is not a
    # degraded playlist but a webapp that will not boot at all. Same migration,
    # idempotent, so whoever starts first does it.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()}
    if columns and "first_seen" not in columns:
        conn.execute("ALTER TABLE tracks ADD COLUMN first_seen REAL")
        conn.execute("UPDATE tracks SET first_seen = mtime WHERE first_seen IS NULL")
        conn.commit()
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS local_plays (
            path TEXT PRIMARY KEY REFERENCES tracks(path),
            plays INTEGER NOT NULL DEFAULT 0,
            skips INTEGER NOT NULL DEFAULT 0,
            seconds REAL NOT NULL DEFAULT 0,
            last_played REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS playlist_schedules (
            playlist_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            weekday INTEGER NOT NULL,
            hour INTEGER NOT NULL,
            minute INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run REAL,
            last_result TEXT
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
    # Added after the table shipped, so existing rows need the column grafted
    # on. VUIO takes a description when a playlist is created but offers no
    # tool to change one, so the current text has to live here: a refreshed
    # playlist gets new tracks and needs a new description to match.
    recipe_columns = {row[1] for row in conn.execute("PRAGMA table_info(playlist_recipes)")}
    if recipe_columns and "description" not in recipe_columns:
        conn.execute("ALTER TABLE playlist_recipes ADD COLUMN description TEXT")
    conn.commit()
    return conn


def record_play(conn: sqlite3.Connection, path: str, seconds: float, completed: bool) -> None:
    """Count one listening event against a track.

    Kept apart from `preferences`, which the Apple import rewrites wholesale -
    these counts are the only ones that survive a re-import, and the only
    source of taste data for the two thirds of the library Apple never saw.
    """
    conn.execute(
        """
        INSERT INTO local_plays (path, plays, skips, seconds, last_played)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            plays = plays + excluded.plays,
            skips = skips + excluded.skips,
            seconds = seconds + excluded.seconds,
            last_played = excluded.last_played
        """,
        (path, 1 if completed else 0, 0 if completed else 1, seconds, time.time()),
    )
    conn.commit()


def fetch_local_plays(conn: sqlite3.Connection, limit: int = 50) -> list:
    rows = conn.execute(
        """
        SELECT path, plays, skips, seconds, last_played
        FROM local_plays ORDER BY last_played DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {"path": p, "plays": pl, "skips": sk, "seconds": round(s), "last_played": lp}
        for p, pl, sk, s, lp in rows
    ]


def save_schedule(conn: sqlite3.Connection, playlist_id: int, name: str,
                  weekday: int, hour: int, minute: int, enabled: bool = True,
                  starts_run_at: float = None) -> None:
    """Create or update the weekly slot for a playlist.

    A new schedule starts out marked as having run at its previous slot
    (`starts_run_at`), so setting up "Monday 06:17" on a Saturday waits for
    Monday instead of firing within the minute. last_run is preserved on
    update for the same reason: changing the time must not trigger a run.
    """
    conn.execute(
        """
        INSERT INTO playlist_schedules
            (playlist_id, name, weekday, hour, minute, enabled, last_run)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(playlist_id) DO UPDATE SET
            name = excluded.name, weekday = excluded.weekday,
            hour = excluded.hour, minute = excluded.minute, enabled = excluded.enabled
        """,
        (playlist_id, name, weekday, hour, minute, 1 if enabled else 0, starts_run_at),
    )
    conn.commit()


def _schedule_row(row) -> dict:
    playlist_id, name, weekday, hour, minute, enabled, last_run, last_result = row
    return {"playlist_id": playlist_id, "name": name, "weekday": weekday,
            "hour": hour, "minute": minute, "enabled": bool(enabled),
            "last_run": last_run, "last_result": last_result}


def list_schedules(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        """
        SELECT playlist_id, name, weekday, hour, minute, enabled, last_run, last_result
        FROM playlist_schedules ORDER BY weekday, hour, minute
        """
    ).fetchall()
    return [_schedule_row(r) for r in rows]


def delete_schedule(conn: sqlite3.Connection, playlist_id: int) -> int:
    cur = conn.execute("DELETE FROM playlist_schedules WHERE playlist_id = ?", (playlist_id,))
    conn.commit()
    return cur.rowcount


def mark_schedule_run(conn: sqlite3.Connection, playlist_id: int, result: str) -> None:
    conn.execute(
        "UPDATE playlist_schedules SET last_run = ?, last_result = ? WHERE playlist_id = ?",
        (time.time(), result, playlist_id),
    )
    conn.commit()


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


def save_description(conn: sqlite3.Connection, playlist_id: int, description: str) -> None:
    """Store the blurb for a playlist, creating the row if the recipe is absent.

    A playlist built by hand has no recipe but can still be described, so the
    row is created with an empty recipe rather than the description dropped.
    """
    conn.execute(
        """
        INSERT INTO playlist_recipes (playlist_id, recipe, updated_at, description)
        VALUES (?, '{}', ?, ?)
        ON CONFLICT(playlist_id) DO UPDATE SET description = excluded.description
        """,
        (playlist_id, time.time(), description),
    )
    conn.commit()


def load_description(conn: sqlite3.Connection, playlist_id: int):
    row = conn.execute(
        "SELECT description FROM playlist_recipes WHERE playlist_id = ?", (playlist_id,)
    ).fetchone()
    return row[0] if row else None


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


def library_fingerprint(conn: sqlite3.Connection) -> tuple:
    """Cheap signal for "the analysed library changed".

    Counting rows and taking the newest scan timestamp costs a couple of
    milliseconds, against ~140ms to reload and reindex everything, so the
    watcher can check often and only reload when it matters.
    """
    return conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(last_scanned), 0) FROM tracks WHERE status = 'ok'"
    ).fetchone()


def load_ok_tracks(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        """
        SELECT t.path, f.bpm, f.key, f.mood_happy, f.mood_aggressive, f.mood_relaxed,
               f.mood_party, f.danceability, f.embedding,
               p.plays, p.skips, p.score, p.song_key, t.first_seen
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
         _apple_plays, _apple_skips, _apple_score, song_key, first_seen) in rows:
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
            # When the scanner first saw the file; None for rows written
            # before the column existed and never rescanned since.
            "first_seen": first_seen,
            "artist": artist_of(path),
            # Artist/album/title for display. The analysis never reads tags,
            # so these are parsed from the path - see display_of.
            "display": display_of(path),
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
    return [{"path": path, "bpm": bpm, "key": key, "display": display_of(path)}
            for path, bpm, key in rows]


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
