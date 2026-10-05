"""Probe how many local library tracks can be matched to the Apple Music export.

Gate for the taste-score feature: if the match rate is too low, scoring by play
count is pointless and we need to read tags from the files instead of parsing paths.

  python3 scripts/match_probe.py --library-json "Apple Music Library Tracks.json" --db data/library.db
  python3 scripts/match_probe.py --library-json "Apple Music Library Tracks.json" --selftest

ponytail: normalized exact title match + artist-in-haystack check. No fuzzy
matching, no Levenshtein; if the exact-match rate is decent that complexity
never needs to exist.
"""

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

# "(Live)", "[Remastered 2011]", "(feat. X)" - noise that differs between
# Apple's metadata and the filename for the same recording.
BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
# "01 ", "01 - ", "1-05_" at the start of a filename.
TRACK_NUMBER = re.compile(r"^\d{1,3}\s*[-_. ]\s*|^\d{1,3}(?=\D)")
NON_ALNUM = re.compile(r"[^a-z0-9]+")
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav", ".aiff", ".alac"}


def norm(text: str) -> str:
    """Fold to a comparison key: lowercase, de-accented, alphanumerics only."""
    if not text:
        return ""
    text = text.lower().replace("ß", "ss").replace("&", "and")
    text = BRACKETS.sub(" ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return NON_ALNUM.sub("", text)


def stem_of(path: str) -> str:
    """Normalized filename without extension and leading track number."""
    name = Path(path).stem
    return norm(TRACK_NUMBER.sub("", name))


def build_index(apple_tracks: list) -> dict:
    """title_key -> [(artist_key, [tracks])].

    Rows are grouped by artist+title because the library duplicates songs
    heavily (same track from a purchase, an Apple Music copy and several
    albums). Each copy carries its own play count, so a caller that wants a
    play total has to sum the whole group - picking one row understates
    favourites badly.
    """
    groups = defaultdict(list)
    for track in apple_tracks:
        title_key = norm(track.get("Title") or "")
        if not title_key:
            continue
        groups[(title_key, norm(track.get("Artist") or ""))].append(track)

    index = defaultdict(list)
    for (title_key, artist_key), tracks in groups.items():
        index[title_key].append((artist_key, tracks))
    return index


def match(haystack: str, stem: str, index: dict):
    """Resolve one messy string to every library row for that song.

    haystack: the whole normalized string (path or description) - should contain
    the artist somewhere. stem: the part expected to be just the title.

    Returns (tracks, status) where status is "matched", "artist_mismatch" or
    "no_title", and tracks is the full duplicate group.
    """
    candidates = index.get(stem)
    if not candidates:
        return None, "no_title"
    for artist_key, tracks in candidates:
        if artist_key and artist_key in haystack:
            return tracks, "matched"
    # Title is unique in the library, so accept it even without artist confirmation.
    if len(candidates) == 1:
        return candidates[0][1], "matched"
    return None, "artist_mismatch"


def report(results: dict, total: int, label: str, samples: list) -> None:
    print(f"\n=== {label} ===")
    print(f"candidates:       {total}")
    matched = results["matched"]
    rate = (matched / total * 100) if total else 0.0
    print(f"matched:          {matched}  ({rate:.1f}%)")
    print(f"title not found:  {results['no_title']}")
    print(f"artist mismatch:  {results['artist_mismatch']}")
    if samples:
        print("\nunmatched samples:")
        for s in samples[:15]:
            print(f"  {s[:100]}")


def probe_db(db_path: str, index: dict) -> None:
    conn = sqlite3.connect(db_path)
    paths = [r[0] for r in conn.execute("SELECT path FROM tracks").fetchall()]
    conn.close()
    paths = [p for p in paths if Path(p).suffix.lower() in AUDIO_EXT]

    results = defaultdict(int)
    unmatched = []
    for path in paths:
        _, status = match(norm(path), stem_of(path), index)
        results[status] += 1
        if status != "matched":
            unmatched.append(path)
    report(results, len(paths), f"LOCAL LIBRARY vs APPLE EXPORT ({db_path})", unmatched)

    rate = results["matched"] / len(paths) * 100 if paths else 0
    print()
    if rate >= 40:
        print(f"-> {rate:.1f}% is workable. Proceed to the preferences table (step 2).")
    else:
        print(f"-> {rate:.1f}% is too low. Plan B: read artist/title tags from the")
        print("   audio files instead of parsing paths.")


def selftest(apple_tracks: list, index: dict, history_csv: str) -> None:
    """Validate the matcher against Play History 'Artist - Title' descriptions.

    Same shape of problem as a file path: one messy string that should contain
    both artist and title. Runs without the server or the music volume.
    """
    assert norm("Böhse Onkelz") == "bohseonkelz"
    assert norm("Die Ärzte") == "diearzte"
    assert norm("Nothing Else Matters (Remastered 2021)") == "nothingelsematters"
    assert norm("Straße & Co.") == "strasseandco"
    assert stem_of("/music/Onkelz/04 - Auf gute Freunde.mp3") == "aufgutefreunde"
    assert stem_of("/music/x/01 Intro.flac") == "intro"

    # Duplicate rows for one song must come back as a group, not a single row.
    dup_index = build_index([
        {"Artist": "Falco", "Title": "Vienna Calling", "Track Play Count": 202},
        {"Artist": "Falco", "Title": "Vienna Calling (Live)", "Track Play Count": 27},
        {"Artist": "Nena", "Title": "99 Luftballons", "Track Play Count": 5},
    ])
    hits, status = match(norm("/music/Falco/03 Vienna Calling.mp3"),
                         stem_of("/music/Falco/03 Vienna Calling.mp3"), dup_index)
    assert status == "matched", status
    assert sum(t["Track Play Count"] for t in hits) == 229, hits
    print("norm/stem/grouping asserts passed.")

    import csv

    descriptions = set()
    with open(history_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = (row.get("Track Description") or "").strip()
            if " - " in d:
                descriptions.add(d)

    results = defaultdict(int)
    unmatched = []
    for desc in descriptions:
        title_part = desc.split(" - ", 1)[1]
        _, status = match(norm(desc), norm(title_part), index)
        results[status] += 1
        if status != "matched":
            unmatched.append(desc)
    report(results, len(descriptions), "SELFTEST: play history vs library index", unmatched)
    print("\n-> Validates the matcher on real string variance, not the path layout.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library-json", required=True, help="Apple Music Library Tracks.json")
    ap.add_argument("--db", help="local library.db to probe")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--history-csv", help="Apple Music - Play History Daily Tracks.csv")
    args = ap.parse_args()

    apple_tracks = json.load(open(args.library_json, encoding="utf-8"))
    index = build_index(apple_tracks)
    print(f"Apple library: {len(apple_tracks)} tracks, {len(index)} distinct title keys")

    if args.selftest:
        if not args.history_csv:
            sys.exit("--selftest needs --history-csv")
        selftest(apple_tracks, index, args.history_csv)
    if args.db:
        probe_db(args.db, index)
    if not args.selftest and not args.db:
        sys.exit("nothing to do: pass --db and/or --selftest")


if __name__ == "__main__":
    main()
