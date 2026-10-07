"""Import Apple Music play counts into a `preferences` table keyed by local path.

Run after a fresh Apple Media Services export:

  python3 scripts/import_preferences.py \
      --library-json "Apple Music Library Tracks.json" --db data/library.db

Matching is done on the file paths. Reading artist/title from the files' own
tags instead was measured and added 2 tracks out of 17747 files examined: the
paths here are well-formed, and what limits coverage is that only about half
the played Apple library exists on disk at all.

Writes only the `preferences` table; `tracks` and `features` are left alone, so
this is safe to run while the analysis service is going.
"""

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from match_probe import AUDIO_EXT, build_index, match, norm, stems_of

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


def collect(conn: sqlite3.Connection, index: dict) -> list:
    """Resolve every analysed track to (path, song_key, plays, skips, score).

    Tracks with no Apple match, or a match carrying no plays, are left out
    entirely rather than stored with score 0 - a zero would rank them below
    disliked music and bury everything that simply has not been played yet.
    """
    paths = [r[0] for r in conn.execute("SELECT path FROM tracks WHERE status = 'ok'")
             if Path(r[0]).suffix.lower() in AUDIO_EXT]

    rows = []
    for path in paths:
        tracks, status = match(norm(path), stems_of(path), index)
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
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args()

    apple_tracks = json.load(open(args.library_json, encoding="utf-8"))
    index = build_index(apple_tracks)
    conn = sqlite3.connect(args.db)

    total = conn.execute("SELECT COUNT(*) FROM tracks WHERE status = 'ok'").fetchone()[0]
    rows = collect(conn, index)
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
