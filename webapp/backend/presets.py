import random

# Criteria that only a track with Apple play data can ever satisfy.
TASTE_KEYS = ("min_percentile", "max_percentile")

# The one place that defines what a playlist can be filtered on. omlx_client
# builds the prompt vocabulary from this, so a column added here is immediately
# available to free-text prompts too.
FILTER_COLUMNS = ["bpm", "danceability", "mood_happy", "mood_aggressive", "mood_relaxed", "mood_party", "percentile"]

_THRESHOLD_CHECKS = {}
for _col in FILTER_COLUMNS:
    _THRESHOLD_CHECKS[f"min_{_col}"] = (lambda c: lambda track, value: track.get(c) is not None and track[c] >= value)(_col)
    _THRESHOLD_CHECKS[f"max_{_col}"] = (lambda c: lambda track, value: track.get(c) is not None and track[c] <= value)(_col)


def dedupe_by_song(tracks: list) -> list:
    """Drop repeat copies of the same recording, keeping the first.

    The library holds ~2.2 files per song (different albums, rips and formats),
    which otherwise fill a playlist with the same track over and over. Tracks
    the Apple import could not identify have no song_key and are all kept.
    """
    seen = set()
    out = []
    for track in tracks:
        key = track.get("song_key")
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        out.append(track)
    return out


MAX_PER_ARTIST = 5


def cap_per_artist(tracks: list, limit: int = MAX_PER_ARTIST) -> list:
    """Keep at most `limit` tracks per artist, in the order given.

    A BPM-and-mood filter happily returns twenty Broilers songs in a row,
    because an artist's catalogue is consistent in exactly the properties
    being filtered on.
    """
    seen = {}
    out = []
    for track in tracks:
        artist = track.get("artist")
        if artist:
            if seen.get(artist, 0) >= limit:
                continue
            seen[artist] = seen.get(artist, 0) + 1
        out.append(track)
    return out


def _checks(criteria: dict, skip=()) -> list:
    return [(_THRESHOLD_CHECKS[key], value) for key, value in criteria.items()
            if key in _THRESHOLD_CHECKS and key not in skip]


def _weave(keep: list, extras: list) -> list:
    """Spread extras through keep instead of appending them in a clump."""
    out = list(keep)
    if not extras:
        return out
    step = max(1, len(out) // len(extras))
    for i, extra in enumerate(extras):
        out.insert(min(len(out), step * (i + 1) + i), extra)
    return out


def is_fresh(track: dict, now: float, max_age_days: float) -> bool:
    first_seen = track.get("first_seen")
    return first_seen is not None and (now - first_seen) <= max_age_days * 86400


def weave_in_fresh(matches: list, candidates: list, limit: int, share: float,
                   max_age_days: float, now: float) -> list:
    """Reserve part of the list for recently imported music.

    New arrivals have no play history, so taste ranking buries them exactly
    when they are most interesting. A quota, rather than a score bonus, is
    what guarantees they actually appear. They still have to pass the same
    brief: `candidates` is the pool the mode already considered suitable.
    """
    wanted = round(limit * share) if share > 0 else 0
    if wanted <= 0:
        return matches[:limit]

    chosen = matches[:limit]
    already = sum(1 for t in chosen if is_fresh(t, now, max_age_days))
    wanted -= already
    if wanted <= 0:
        return chosen  # the mode picked enough new music on its own

    taken = {t["path"] for t in chosen}
    pool = [t for t in candidates
            if t["path"] not in taken and is_fresh(t, now, max_age_days)
            and t.get("rating", 0) >= 0]
    # Newest first, so a quota that cannot be filled still favours the freshest.
    pool.sort(key=lambda t: t["first_seen"], reverse=True)
    picks = dedupe_by_song(pool)[:wanted]
    woven = cap_per_artist(_weave(chosen[:limit - len(picks)], picks))
    # The cap can drop tracks - a big fresh import is all one artist - which
    # would otherwise hand back a short list. Top it back up from the matches
    # the quota displaced, which are the next best the mode had.
    if len(woven) < limit:
        have = {t["path"] for t in woven}
        woven += [t for t in matches if t["path"] not in have][:limit - len(woven)]
    return woven[:limit]


def filter_by_criteria(tracks: list, criteria: dict, limit: int = 30,
                       discovery: float = 0.0) -> list:
    matches = [t for t in tracks if all(c(t, v) for c, v in _checks(criteria))]
    # Only order by taste once the caller asks for it; otherwise scored tracks
    # would always crowd out everything the Apple export never saw. Ordering
    # uses the raw score, which has none of the percentile's rounding ties.
    if criteria.get("min_percentile"):
        matches.sort(key=lambda t: t["score"], reverse=True)
    matches = cap_per_artist(dedupe_by_song(matches))

    # A percentile threshold can never admit a track that has no percentile,
    # so asking for favourites silently rules out the ~79% of the library the
    # Apple export never saw. Hand part of the list back to those, picked from
    # the tracks that pass every *other* criterion, so they fit the same brief.
    wanted = round(limit * discovery) if discovery > 0 else 0
    if not wanted or not any(k in criteria for k in TASTE_KEYS):
        return matches[:limit]

    taken = {t["path"] for t in matches[:limit - wanted]}
    pool = [t for t in tracks
            if t.get("percentile") is None and t["path"] not in taken
            and all(c(t, v) for c, v in _checks(criteria, skip=TASTE_KEYS))]
    # Random, so repeated previews keep surfacing different unheard tracks.
    picks = random.sample(pool, min(wanted, len(pool)))
    woven = _weave(matches[:limit - len(picks)], dedupe_by_song(picks))
    # Cap again: a discovery pick can share an artist with the scored portion.
    return cap_per_artist(woven)[:limit]
