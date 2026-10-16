"""Turn a hand-written list of wished-for songs into a playlist.

Each line is matched against the library. Matches go in first, in the order
given; songs the library does not have are reported back rather than
silently dropped; the rest of the list is filled with tracks that sound like
the wished-for ones.
"""

import re

import numpy as np

import db
import presets


# Words marking a version other than the one someone means when they name a
# song. A remaster is the same recording, so it is deliberately not here.
_ALTERNATE = re.compile(
    r"\b(live|remix|mix|edit|dub|instrumental|acoustic|unplugged|demo|"
    r"version|session|rehearsal|karaoke|sped up|slowed|cover)\b", re.I)


def _pick_version(tracks: list) -> dict:
    """Of several files of one song, the one to play when it is asked for by name.

    Taste ties across versions - the play counts are pooled per song, so all
    52 copies of "Nothing Else Matters" share one percentile - and a bare
    "shortest title" then preferred "(Live)" over "(Remastered 2021)". So:
    the album cut first, then the best-liked, then the plainest title.
    """
    def rank(t):
        title = t["display"]["title"]
        return (not _ALTERNATE.search(title), t.get("percentile") or -1, -len(title))
    return max(tracks, key=rank)


def match(wishes: list, tracks: list) -> tuple:
    """Split parsed wishes into (found tracks, missing wishes).

    An exact artist+title key match is tried first. A wish without an artist
    (a bare title) matches on the title alone, but only when exactly one
    artist in the library has a song by that name - "Wonderwall" is fine,
    "Intro" is not.
    """
    by_key, by_title = {}, {}
    for t in tracks:
        by_key.setdefault(t["song_key"], []).append(t)
        title_key = t["song_key"].split("|", 1)[1]
        by_title.setdefault(title_key, []).append(t)

    found, missing, seen = [], [], set()
    for wish in wishes:
        key = db.song_key_for(wish["artist"], wish["title"])
        candidates = by_key.get(key) if wish["artist"] else None
        if not candidates and not wish["artist"]:
            same_title = by_title.get(key.split("|", 1)[1], [])
            if len({t["song_key"] for t in same_title}) == 1:
                candidates = same_title
        if not candidates:
            missing.append(wish)
            continue
        chosen = _pick_version(candidates)
        if chosen["song_key"] in seen:  # listed twice
            continue
        seen.add(chosen["song_key"])
        found.append(chosen)
    return found, missing


def fill(found: list, tracks: list, limit: int) -> list:
    """Top the found songs up to `limit` with tracks that sound like them.

    Similarity is measured against the centroid of the wished-for songs, so
    the filler suits the list as a whole rather than echoing one track. The
    usual per-artist cap and de-duplication apply to the filler, but never
    evict a wished-for song - those were asked for by name.
    """
    if len(found) >= limit or not found:
        return found[:limit]

    centre = np.mean([t["embedding"] for t in found], axis=0).astype(np.float32)
    centre /= np.linalg.norm(centre) + 1e-8
    taken = {t["song_key"] for t in found}
    pool = [t for t in tracks if t["song_key"] not in taken and t.get("rating", 0) >= 0]
    if not pool:
        return found

    matrix = np.stack([t["embedding"] for t in pool]).astype(np.float32)
    scores = (matrix @ centre) / (np.linalg.norm(matrix, axis=1) + 1e-8)
    ranked = [pool[i] for i in np.argsort(-scores)[:limit * 6]]

    # Wished-for artists already occupy slots, so the cap counts them too.
    counts = {}
    for t in found:
        counts[t["artist"]] = counts.get(t["artist"], 0) + 1
    filler = []
    for t in presets.dedupe_by_song(ranked):
        if len(found) + len(filler) >= limit:
            break
        if counts.get(t["artist"], 0) >= presets.MAX_PER_ARTIST:
            continue
        counts[t["artist"]] = counts.get(t["artist"], 0) + 1
        filler.append(t)
    return found + filler


def build(lines: list, tracks: list, limit: int = 50) -> dict:
    wishes = [w for w in (db.parse_wish(line) for line in lines) if w]
    found, missing = match(wishes, tracks)
    return {"tracks": fill(found, tracks, limit), "found": len(found),
            "missing": [w["line"] for w in missing], "wished": len(wishes)}


def _selfcheck():
    def track(artist, title, vec, pct=None, album="Alb"):
        path = f"/music/{artist} - {album}/01. {artist} - {title}.flac"
        return {"path": path, "artist": db.artist_of(path), "display": db.display_of(path),
                "song_key": db.song_key_of(path), "percentile": pct, "rating": 0,
                "embedding": np.array(vec, dtype=np.float32)}

    lib = [track("Falco", "Vienna Calling", [1, 0], 90),
           track("Falco", "Vienna Calling (Live)", [1, 0], 20, album="Live"),
           track("Metallica", "One (Live)", [1, 0], 50, album="S&M"),
           track("Metallica", "One (Remastered 2021)", [1, 0], 50, album="Black"),
           track("Nena", "99 Luftballons", [0.9, 0.1]),
           track("Oasis", "Wonderwall", [0, 1]),
           track("Band A", "Intro", [0.5, 0.5]), track("Band B", "Intro", [0.5, 0.5])]
    out = build(["Falco - Vienna Calling", "Wonderwall", "Intro",
                 "Unbekannt - Gibt es nicht", "", "falco - vienna calling"], lib, limit=4)
    paths = [t["path"] for t in out["tracks"]]
    # Album cut chosen over the live take, listed once despite two lines.
    assert paths[0].endswith("01. Falco - Vienna Calling.flac"), paths
    assert sum("Vienna" in p for p in paths) == 1
    # A unique bare title matches; an ambiguous one is reported missing.
    assert any("Wonderwall" in p for p in paths)
    assert out["missing"] == ["Intro", "Unbekannt - Gibt es nicht"], out["missing"]
    # Filled up to the limit with the closest-sounding remainder.
    assert len(out["tracks"]) == 4 and out["found"] == 2 and out["wished"] == 5
    # On a taste tie the remaster (album cut) beats the live take.
    one = build(["Metallica - One"], lib, limit=1)["tracks"][0]
    assert "Remastered" in one["path"], one["path"]
    print("ok")


if __name__ == "__main__":
    _selfcheck()
