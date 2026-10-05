import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_preferences
from import_preferences import collect, host_path, score_of, write
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


def test_host_path_maps_container_paths_onto_this_machine():
    assert host_path("/music/A/b.mp3", "/Volumes/Platte/Musik") == "/Volumes/Platte/Musik/A/b.mp3"
    # No root configured, or a path from somewhere else: leave it alone.
    assert host_path("/music/A/b.mp3", "") == "/music/A/b.mp3"
    assert host_path("/other/b.mp3", "/Volumes/Platte/Musik") == "/other/b.mp3"


def test_tags_match_files_whose_path_does_not(monkeypatched_tags=None):
    """A path with no usable title still matches when the tags carry one."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE tracks (path TEXT PRIMARY KEY, status TEXT)")
    conn.execute("INSERT INTO tracks VALUES ('/music/ripped/track03.mp3', 'ok')")
    conn.commit()
    apple = [{"Artist": "Nena", "Title": "99 Luftballons", "Track Play Count": 10, "Skip Count": 0}]

    # Path alone carries nothing identifiable.
    assert collect(conn, build_index(apple)) == []

    original = import_preferences.read_tags
    import_preferences.read_tags = lambda p: ("Nena", "99 Luftballons")
    try:
        rows = collect(conn, build_index(apple), music_root="/Volumes/Platte/Musik")
    finally:
        import_preferences.read_tags = original
    assert [r[0] for r in rows] == ["/music/ripped/track03.mp3"]
    assert rows[0][2] == 10


def test_write_is_idempotent():
    conn = _db()
    rows = collect(conn, build_index(APPLE))
    write(conn, rows)
    write(conn, rows)
    assert conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0] == len(rows)


if __name__ == "__main__":
    test_score_damps_plays_and_uses_skip_ratio()
    test_collect_groups_duplicates_and_skips_unscorable()
    test_host_path_maps_container_paths_onto_this_machine()
    test_tags_match_files_whose_path_does_not()
    test_write_is_idempotent()
    print("All import_preferences tests passed.")
