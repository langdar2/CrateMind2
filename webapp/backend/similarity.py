import numpy as np

# What a track with no Apple play data counts as when taste is mixed in.
# The median of everything that does have a score, so an unknown track is
# neither rewarded nor punished - most of the library is unscored.
NEUTRAL_PERCENTILE = 50.0

# How many of the closest tracks taste is allowed to reorder, as a multiple of
# the requested limit. Blending across the whole library does not work: the
# 30 closest of 33000 tracks sit within a hair of each other, so dropping a
# thousand places costs almost no similarity and any weight above a few
# percent would silently turn the mode into "my favourites". Narrowing to a
# genuinely similar shortlist first makes the weight mean what it says.
SHORTLIST_FACTOR = 10


def top_similar(seed: dict, tracks: list, limit: int = 30, taste_weight: float = 0.0) -> list:
    """Closest tracks to the seed, optionally reordered towards well-liked music.

    taste_weight 0 is pure sound, 1 picks the best-liked of the shortlist.
    Both inputs are turned into ranks within that shortlist before mixing, so
    the weight splits the decision evenly rather than being swamped by
    whichever of the two happens to have the wider spread.
    """
    others = [t for t in tracks if t["path"] != seed["path"]]
    if not others:
        return []

    embeddings = np.stack([t["embedding"] for t in others]).astype(np.float32)
    seed_vec = seed["embedding"].astype(np.float32)

    norms = np.linalg.norm(embeddings, axis=1)
    seed_norm = np.linalg.norm(seed_vec)
    scores = (embeddings @ seed_vec) / (norms * seed_norm + 1e-8)

    order = np.argsort(-scores)
    if taste_weight <= 0:
        return [others[i] for i in order[:limit]]

    shortlist = [others[i] for i in order[:limit * SHORTLIST_FACTOR]]
    n = len(shortlist)
    if n == 1:
        return shortlist[:limit]

    # shortlist is already sorted by similarity, so position is the rank.
    sound_rank = np.linspace(1.0, 0.0, n, dtype=np.float32)
    taste = np.array(
        [(t.get("percentile") if t.get("percentile") is not None else NEUTRAL_PERCENTILE) / 100.0
         for t in shortlist],
        dtype=np.float32,
    )
    blended = sound_rank * (1.0 - taste_weight) + taste * taste_weight
    return [shortlist[i] for i in np.argsort(-blended)[:limit]]
