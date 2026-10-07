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


def filter_by_criteria(tracks: list, criteria: dict, limit: int = 30) -> list:
    checks = [(_THRESHOLD_CHECKS[key], value) for key, value in criteria.items() if key in _THRESHOLD_CHECKS]
    matches = [track for track in tracks if all(check(track, value) for check, value in checks)]
    # Only order by taste once the caller asks for it; otherwise scored tracks
    # would always crowd out everything the Apple export never saw. Ordering
    # uses the raw score, which has none of the percentile's rounding ties.
    if criteria.get("min_percentile"):
        matches.sort(key=lambda t: t["score"], reverse=True)
    return dedupe_by_song(matches)[:limit]
