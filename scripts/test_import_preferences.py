import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_preferences import collect, load_history, score_of, weigh, write
from match_probe import build_index

APPLE = [
    {"Artist": "Falco", "Title": "Vienna Calling", "Track Play Count": 202, "Skip Count": 5},
    {"Artist": "Falco", "Title": "Vienna Calling", "Track Play Count": 112, "Skip Count": 5},
    {"Artist": "Nena", "Title": "99 Luftballons", "Track Play Count": 10, "Skip Count": 0},
    {"Artist": "Haymaker", "Title": "Sixteen"},
]


def _db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute("CREATE TABLE tracks (path TEXT PRIMARY KEY, status TEXT)")
    for path in [
        "/music/Falco - Hits/06. Falco - Vienna Calling.mp3",
        "/music/Falco - Live/03. Falco - Vienna Calling.flac",
        "/music/Nena - Nena/01. Nena - 99 Luftballons.mp3",
        "/music/Haymaker - Demo/01. Haymaker - Sixteen.mp3",
        "/music/Unknown - X/01. Unknown - Not In Apple.mp3",
        "/music/Falco - Hits/cover.jpg",
    ]:
        conn.execute("INSERT INTO tracks VALUES (?, 'ok')", (path,))
    conn.execute("INSERT INTO tracks VALUES ('/music/a/01. a - pending.mp3', 'pending')")
    conn.commit()
    return conn


def test_score_damps_plays_and_uses_skip_ratio():
    # log damping: 50x the plays is nowhere near 50x the score.
    assert score_of(200, 0) < 5 * score_of(4, 0)
    # A skip ratio lowers the score; absolute skips on a heavy-rotation track
    # must still beat a barely-played one.
    assert score_of(200, 50) > score_of(5, 1)
    assert score_of(10, 10) < score_of(10, 0)
    assert score_of(0, 5) == 0.0


def test_collect_groups_duplicates_and_skips_unscorable():
    conn = _db()
    rows = collect(conn, build_index(APPLE))
    by_path = {r[0]: r for r in rows}

    # Both local copies of Vienna Calling get the summed play count (202+112).
    assert len(by_path) == 3, sorted(by_path)
    for p in ("/music/Falco - Hits/06. Falco - Vienna Calling.mp3",
              "/music/Falco - Live/03. Falco - Vienna Calling.flac"):
        assert by_path[p][2] == 314, by_path[p]
    # ...and share a song_key so playlists can de-duplicate them.
    assert by_path["/music/Falco - Hits/06. Falco - Vienna Calling.mp3"][1] == \
           by_path["/music/Falco - Live/03. Falco - Vienna Calling.flac"][1]

    # No Apple match, no play data, non-audio and non-ok rows are all left out.
    assert "/music/Unknown - X/01. Unknown - Not In Apple.mp3" not in by_path
    assert "/music/Haymaker - Demo/01. Haymaker - Sixteen.mp3" not in by_path
    assert "/music/Falco - Hits/cover.jpg" not in by_path
    assert "/music/a/01. a - pending.mp3" not in by_path


HISTORY_CSV = """Track Description,Date Played,Play Count,Skip Count
Falco - Vienna Calling,20260901,10,0
Falco - Vienna Calling,20180901,100,0
Nena - 99 Luftballons,20260901,10,0
"""


def _history_file():
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8")
    tmp.write(HISTORY_CSV)
    tmp.close()
    return tmp.name


def test_recent_plays_outweigh_old_ones():
    history, old_weight = load_history(_history_file(), half_life_years=2.0)
    recent = history["nena99luftballons"][0]
    # 100 plays from 2018 are ~8 years old: four half-lives, so under 1/16 each.
    old = history["falcoviennacalling"][0]
    assert abs(recent - 10.0) < 0.01, recent
    assert 10 < old < 20, old
    # Anything older than the log itself is discounted hardest of all.
    assert 0 < old_weight < 0.1, old_weight


def test_plays_predating_the_log_are_aged_not_dropped():
    history, old_weight = load_history(_history_file(), half_life_years=2.0)
    # Lifetime counter says 200, the log only accounts for 110 -> 90 are older
    # than the log and must still carry a little weight, not vanish.
    tracks = [{"Artist": "Falco", "Title": "Vienna Calling",
               "Track Play Count": 200, "Skip Count": 0}]
    weighted, _, raw = weigh(tracks, history, old_weight)
    logged = history["falcoviennacalling"][0]
    assert raw == 200
    assert weighted > logged
    assert weighted < logged + 90


def test_untracked_song_keeps_a_residual_score():
    """A song the log never saw still scores - just very low."""
    history, old_weight = load_history(_history_file(), half_life_years=2.0)
    tracks = [{"Artist": "Gone", "Title": "Old Favourite",
               "Track Play Count": 109, "Skip Count": 1}]
    weighted, _, raw = weigh(tracks, history, old_weight)
    assert raw == 109
    assert 0 < weighted < 109 * 0.1
    assert score_of(weighted, 0) > 0


def test_write_is_idempotent():
    conn = _db()
    rows = collect(conn, build_index(APPLE))
    write(conn, rows)
    write(conn, rows)
    assert conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0] == len(rows)


if __name__ == "__main__":
    test_score_damps_plays_and_uses_skip_ratio()
    test_collect_groups_duplicates_and_skips_unscorable()
    test_recent_plays_outweigh_old_ones()
    test_plays_predating_the_log_are_aged_not_dropped()
    test_untracked_song_keeps_a_residual_score()
    test_write_is_idempotent()
    print("All import_preferences tests passed.")
