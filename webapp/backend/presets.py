_COLUMNS = ["bpm", "danceability", "mood_happy", "mood_aggressive", "mood_relaxed", "mood_party"]

_THRESHOLD_CHECKS = {}
for _col in _COLUMNS:
    _THRESHOLD_CHECKS[f"min_{_col}"] = (lambda c: lambda track, value: track[c] is not None and track[c] >= value)(_col)
    _THRESHOLD_CHECKS[f"max_{_col}"] = (lambda c: lambda track, value: track[c] is not None and track[c] <= value)(_col)


def filter_by_criteria(tracks: list, criteria: dict, limit: int = 30) -> list:
    checks = [(_THRESHOLD_CHECKS[key], value) for key, value in criteria.items() if key in _THRESHOLD_CHECKS]
    matches = [track for track in tracks if all(check(track, value) for check, value in checks)]
    return matches[:limit]
