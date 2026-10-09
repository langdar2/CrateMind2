"""Import Apple Music play counts into a `preferences` table keyed by local path.

Run after a fresh Apple Media Services export:

  python3 scripts/import_preferences.py \
      --library-json "Apple Music Library Tracks.json" --db data/library.db \
      --history-csv "Apple Music - Play History Daily Tracks.csv"

Without --history-csv a play from 2012 counts as much as one from last month,
which ranks long-abandoned favourites alongside current ones. With it, plays
decay by age (see --half-life-years).

Matching is done on the file paths. Reading artist/title from the files' own
tags instead was measured and added 2 tracks out of 17747 files examined: the
paths here are well-formed, and what limits coverage is that only about half
the played Apple library exists on disk at all.

Writes only the `preferences` table; `tracks` and `features` are left alone, so
this is safe to run while the analysis service is going.
"""

import argparse
import csv
import json
import math
import sys
from pathlib import Path

# The webapp image ships only webapp/backend, so the scoring formula lives
# there and is imported here -- one definition, no drift between the Apple
# import and the plays the player counts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp" / "backend"))
from db import score_of  # noqa: E402
import sqlite3
import sys
from datetime import date
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


def _decay(day: date, ref: date, half_life_years: float) -> float:
    return 0.5 ** (max(0.0, (ref - day).days / 365.25) / half_life_years)


def load_history(csv_path: str, half_life_years: float) -> tuple:
    """Weight every play by how long ago it happened.

    Returns ({key: (weighted_plays, weighted_skips, raw_plays, raw_skips)},
    history_start_weight). The key is the normalised "artist + title", matching
    how the Apple library spells the same song.

    Taste drifts, so a play from 2013 should not count like one from last month.
    The second return value is the weight a play gets if it is older than this
    file reaches back: tracks missing from it were still played, just before
    Apple started keeping the log.
    """
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            description = (r.get("Track Description") or "").strip()
            day = (r.get("Date Played") or "").strip()
            if not description or len(day) != 8:
                continue
            plays = int(r.get("Play Count") or 0)
            skips = int(r.get("Skip Count") or 0)
            if plays or skips:
                rows.append((norm(description), day, plays, skips))

    if not rows:
        return {}, 1.0
    as_date = lambda d: date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    ref = as_date(max(r[1] for r in rows))
    earliest = as_date(min(r[1] for r in rows))

    history = {}
    for key, day, plays, skips in rows:
        weight = _decay(as_date(day), ref, half_life_years)
        wp, ws, rp, rs = history.get(key, (0.0, 0.0, 0, 0))
        history[key] = (wp + plays * weight, ws + skips * weight, rp + plays, rs + skips)
    return history, _decay(earliest, ref, half_life_years)


def weigh(tracks: list, history: dict, old_weight: float) -> tuple:
    """(weighted_plays, weighted_skips, raw_plays) for one song's library rows.

    The library's lifetime counters and the play history disagree on purpose:
    the counters reach back further than the log, the log also sees streaming
    of songs that never entered the library. So take the dated plays from the
    log, and treat whatever the lifetime counter has on top of them as plays
    from before the log begins - which is the newest they could possibly be.
    """
    lifetime_plays = sum(t.get("Track Play Count") or 0 for t in tracks)
    lifetime_skips = sum(t.get("Skip Count") or 0 for t in tracks)
    key = norm(tracks[0].get("Artist") or "") + norm(tracks[0].get("Title") or "")
    weighted_plays, weighted_skips, logged_plays, logged_skips = history.get(key, (0.0, 0.0, 0, 0))

    weighted_plays += max(0, lifetime_plays - logged_plays) * old_weight
    weighted_skips += max(0, lifetime_skips - logged_skips) * old_weight
    return weighted_plays, weighted_skips, max(lifetime_plays, logged_plays)


def collect(conn: sqlite3.Connection, index: dict, history: dict = None,
            old_weight: float = 1.0) -> list:
    """Resolve every analysed track to (path, song_key, plays, skips, score).

    Tracks with no Apple match, or a match carrying no plays, are left out
    entirely rather than stored with score 0 - a zero would rank them below
    disliked music and bury everything that simply has not been played yet.

    `plays` and `skips` are stored unweighted, so the table still reports what
    actually happened; only `score` reflects the age of those plays.
    """
    history = history or {}
    paths = [r[0] for r in conn.execute("SELECT path FROM tracks WHERE status = 'ok'")
             if Path(r[0]).suffix.lower() in AUDIO_EXT]

    rows = []
    for path in paths:
        tracks, status = match(norm(path), stems_of(path), index)
        if status != "matched":
            continue
        weighted_plays, weighted_skips, plays = weigh(tracks, history, old_weight)
        if plays <= 0:
            continue
        skips = sum(t.get("Skip Count") or 0 for t in tracks)
        song_key = norm(tracks[0].get("Artist") or "") + "|" + norm(tracks[0].get("Title") or "")
        rows.append((path, song_key, plays, skips, score_of(weighted_plays, weighted_skips)))
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
    ap.add_argument("--history-csv",
                    help="'Apple Music - Play History Daily Tracks.csv'. Without it "
                         "every play counts the same no matter how long ago it was.")
    ap.add_argument("--half-life-years", type=float, default=2.0,
                    help="how fast old plays stop counting (default 2.0)")
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args()

    apple_tracks = json.load(open(args.library_json, encoding="utf-8"))
    index = build_index(apple_tracks)
    conn = sqlite3.connect(args.db)

    history, old_weight = {}, 1.0
    if args.history_csv:
        history, old_weight = load_history(args.history_csv, args.half_life_years)
        print(f"history:           {len(history)} songs, half-life {args.half_life_years}y, "
              f"pre-log plays count {old_weight:.3f}")
    else:
        print("note: no --history-csv, scoring without any age weighting.")

    total = conn.execute("SELECT COUNT(*) FROM tracks WHERE status = 'ok'").fetchone()[0]
    rows = collect(conn, index, history, old_weight)
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
