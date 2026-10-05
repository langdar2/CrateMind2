"""Import Apple Music play counts into a `preferences` table keyed by local path.

Run after a fresh Apple Media Services export:

  python3 scripts/import_preferences.py \
      --library-json "Apple Music Library Tracks.json" --db data/library.db \
      --music-root /Volumes/Platte/Musik

Pass --music-root (and install mutagen) to match on the files' own tags rather
than on their paths, which roughly doubles the number of tracks that get a score.

Writes only the `preferences` table; `tracks` and `features` are left alone, so
this is safe to run while the analysis service is going.
"""

import argparse
import json
import math
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from match_probe import AUDIO_EXT, build_index, match, norm, stems_of

try:
    import mutagen
except ImportError:
    # Optional: without it we fall back to parsing artist/title out of the
    # path, which matches noticeably fewer tracks. `pip3 install mutagen`.
    mutagen = None

DB_MUSIC_PREFIX = "/music/"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS preferences (
    path TEXT PRIMARY KEY REFERENCES tracks(path),
    song_key TEXT NOT NULL,
    plays INTEGER NOT NULL,
    skips INTEGER NOT NULL,
    score REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_preferences_score ON preferences(score);
CREATE INDEX IF NOT EXISTS idx_preferences_song_key ON preferences(song_key);
"""


def score_of(plays: int, skips: int) -> float:
    """Taste score from play and skip counts.

    log() damps the long tail - 200 plays is not 50x the preference of 4 plays,
    and without it a handful of heavy-rotation artists swamp everything. The
    second factor is a skip *ratio*, not a skip count: favourites get skipped a
    lot simply because they come up a lot, so penalising absolute skips would
    punish exactly the tracks we want to surface.
    """
    if plays <= 0:
        return 0.0
    return math.log(1 + plays) * (1 - skips / (plays + skips))


def host_path(db_path: str, music_root: str) -> str:
    """Translate a DB path into one this machine can open.

    The analysis container records paths under its own /music mount; the host
    sees the same files somewhere else (e.g. /Volumes/Platte/Musik).
    """
    if music_root and db_path.startswith(DB_MUSIC_PREFIX):
        return os.path.join(music_root, db_path[len(DB_MUSIC_PREFIX):])
    return db_path


def read_tags(path: str) -> tuple:
    """(artist, title) from the file's own tags, or (None, None).

    Unreadable or untagged files are not worth reporting individually - the
    caller falls back to the path and the summary counts how often that happened.
    """
    if mutagen is None:
        return None, None
    try:
        audio = mutagen.File(path, easy=True)
    except Exception:
        return None, None
    if not audio:
        return None, None
    artist = (audio.get("artist") or [None])[0]
    title = (audio.get("title") or [None])[0]
    return artist, title


def collect(conn: sqlite3.Connection, index: dict, music_root: str = "") -> list:
    """Resolve every analysed track to (path, song_key, plays, skips, score).

    Tracks with no Apple match, or a match carrying no plays, are left out
    entirely rather than stored with score 0 - a zero would rank them below
    disliked music and bury everything that simply has not been played yet.
    """
    paths = [r[0] for r in conn.execute("SELECT path FROM tracks WHERE status = 'ok'")]
    rows = []
    for path in paths:
        if Path(path).suffix.lower() not in AUDIO_EXT:
            continue
        artist, title = read_tags(host_path(path, music_root)) if music_root else (None, None)
        # The tagged title is the most reliable candidate, so try it first and
        # let the path-derived guesses cover files with missing or odd tags.
        stems = ([norm(title)] if title else []) + stems_of(path)
        tracks, status = match(norm(path) + norm(artist or ""), stems, index)
        if status != "matched":
            continue
        plays = sum(t.get("Track Play Count") or 0 for t in tracks)
        if plays <= 0:
            continue
        skips = sum(t.get("Skip Count") or 0 for t in tracks)
        song_key = norm(tracks[0].get("Artist") or "") + "|" + norm(tracks[0].get("Title") or "")
        rows.append((path, song_key, plays, skips, score_of(plays, skips)))
    return rows


def write(conn: sqlite3.Connection, rows: list) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.execute("DELETE FROM preferences")
    conn.executemany(
        "INSERT INTO preferences (path, song_key, plays, skips, score) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library-json", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--music-root", default="",
                    help="where this machine sees the files the DB records under "
                         "/music (e.g. /Volumes/Platte/Musik). Enables tag reading.")
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args()

    if args.music_root and mutagen is None:
        print("warning: mutagen is not installed, falling back to path parsing.")
        print("         pip3 install mutagen  (roughly doubles the match rate)\n")
    elif not args.music_root:
        print("note: --music-root not given, matching on paths only.\n")

    apple_tracks = json.load(open(args.library_json, encoding="utf-8"))
    index = build_index(apple_tracks)
    conn = sqlite3.connect(args.db)

    total = conn.execute("SELECT COUNT(*) FROM tracks WHERE status = 'ok'").fetchone()[0]
    rows = collect(conn, index, args.music_root)
    songs = len({r[1] for r in rows})

    print(f"analysed tracks:   {total}")
    print(f"scored:            {len(rows)}  ({len(rows) / total * 100:.1f}%)")
    print(f"distinct songs:    {songs}  ({len(rows) / songs:.2f} local copies each)")
    print(f"plays attached:    {sum(r[2] for r in rows)}")

    if args.dry_run:
        print("\ndry run - nothing written")
        print("top 10:")
        for path, _, plays, skips, score in sorted(rows, key=lambda r: -r[4])[:10]:
            print(f"  {score:5.2f}  {plays:4d}p/{skips:3d}s  {Path(path).name[:60]}")
    else:
        write(conn, rows)
        print(f"\nwrote {len(rows)} rows to preferences")
    conn.close()


if __name__ == "__main__":
    main()
