"""Artist neighbourhood graph built from the Essentia embeddings.

One artist per view, like a MusicBrainz-style artist page: the artist in the
middle, the artists that sound closest around it. The whole library is 33k
tracks and 646 artists - drawing all of it at once is a hairball, so the graph
is served one neighbourhood at a time.

Edges mean "sounds like", not "worked with": the weight is the cosine
similarity between two artists' mean embeddings, which is all the library
knows. There is no collaboration data.
"""

import numpy as np

# An artist's centroid is meaningless if it averages two tracks, and the long
# tail is mostly compilation leftovers filed under one-off folder names.
MIN_TRACKS = 3
# Floor for *entering* a neighbourhood. The median similarity between any two
# artists in this library is 0.37 and the 90th percentile is 0.80, so these
# embeddings are generally positive - anything below this is plainly unrelated.
MIN_SIMILARITY = 0.6

# Edges kept per node. An absolute threshold cannot work here: neighbours are
# picked for being similar to the centre, so they are similar to each other
# too, and every pair clears any cutoff - at 0.9 still 95 of 105 possible
# edges survived, drawing a hairball. Keeping each node's strongest few edges
# shows who sits closest to whom instead.
EDGES_PER_NODE = 3


def build_index(tracks: list) -> dict:
    """Pre-compute per-artist centroids once, at startup.

    Returns {"artists": [...], "matrix": (n, d) L2-normalised centroids}, so a
    neighbourhood query is one matrix-vector product rather than a scan over
    33k embeddings.
    """
    grouped = {}
    for track in tracks:
        artist = track.get("artist")
        if artist:
            grouped.setdefault(artist, []).append(track)
    grouped = {a: ts for a, ts in grouped.items() if len(ts) >= MIN_TRACKS}
    if not grouped:
        return {"artists": [], "matrix": np.zeros((0, 0), dtype=np.float32), "tracks": {}}

    artists = sorted(grouped)
    centroids = np.stack([
        np.mean([t["embedding"] for t in grouped[a]], axis=0) for a in artists
    ]).astype(np.float32)
    # Normalise once so similarity is a plain dot product later.
    centroids /= np.linalg.norm(centroids, axis=1, keepdims=True) + 1e-8
    return {"artists": artists, "matrix": centroids, "tracks": grouped}


def _summary(artist: str, tracks: list) -> dict:
    scored = [t["percentile"] for t in tracks if t.get("percentile") is not None]
    bpms = [t["bpm"] for t in tracks if t.get("bpm") is not None]
    return {
        "id": artist,
        "label": artist.title(),
        "track_count": len(tracks),
        # None when the Apple export never saw this artist, which is most of
        # the library - the UI greys those out rather than scoring them 0.
        "percentile": round(sum(scored) / len(scored)) if scored else None,
        "avg_bpm": round(sum(bpms) / len(bpms)) if bpms else None,
    }


def neighbourhood(index: dict, artist: str, limit: int = 20) -> dict:
    """The artist, its nearest-sounding neighbours, and the edges between them.

    Edges are drawn among the neighbours too, not just from the centre, so
    clusters within the neighbourhood are visible instead of a plain star.
    """
    artists = index["artists"]
    if artist not in index["tracks"]:
        return None

    centre = artists.index(artist)
    scores = index["matrix"] @ index["matrix"][centre]
    scores[centre] = -1.0
    # int() throughout: argsort yields numpy ints, and a numpy bool derived
    # from them is not JSON-serialisable.
    order = [int(i) for i in np.argsort(-scores) if scores[i] >= MIN_SIMILARITY][:limit]

    members = [centre] + list(order)
    nodes = [dict(_summary(artists[i], index["tracks"][artists[i]]),
                  is_center=(i == centre)) for i in members]

    # Each node keeps its strongest few links; the union is symmetric, so an
    # edge survives if either endpoint rates the other among its closest.
    kept = {}
    for i in members:
        ranked = sorted(
            ((float(index["matrix"][i] @ index["matrix"][j]), j) for j in members if j != i),
            reverse=True,
        )
        for weight, j in ranked[:EDGES_PER_NODE]:
            kept[frozenset((i, j))] = weight

    edges = [{"source": artists[min(pair)], "target": artists[max(pair)],
              "weight": round(weight, 3)}
             for pair, weight in sorted(kept.items(), key=lambda kv: -kv[1])]
    return {"center": artist, "nodes": nodes, "edges": edges}


def tracks_for_artists(index: dict, artists: list) -> list:
    """Every analysed track by the named artists, best-liked first.

    Ordering is by taste so that capping per artist keeps each one's
    strongest tracks rather than whichever the database returned first.
    Unscored tracks sort last but are kept - most of the library has no
    Apple score, and dropping them would empty whole neighbourhoods.
    """
    wanted = [a for a in artists if a in index["tracks"]]
    collected = [t for a in wanted for t in index["tracks"][a]]
    # percentile, not score: this module reports and colours by percentile
    # everywhere else, and mixing the two notions here would be a trap.
    collected.sort(
        key=lambda t: (t.get("percentile") is not None, t.get("percentile") or 0),
        reverse=True,
    )
    return collected


def list_artists(index: dict) -> list:
    return [_summary(a, index["tracks"][a]) for a in index["artists"]]
