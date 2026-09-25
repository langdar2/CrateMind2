PRESETS = {
    "workout": {"min_bpm": 120, "min_danceability": 0.6},
    "chill": {"max_bpm": 100, "min_mood_relaxed": 0.5},
    "party": {"min_danceability": 0.6, "min_mood_party": 0.5},
}

_THRESHOLD_CHECKS = {
    "min_bpm": lambda track, value: track["bpm"] is not None and track["bpm"] >= value,
    "max_bpm": lambda track, value: track["bpm"] is not None and track["bpm"] <= value,
    "min_danceability": lambda track, value: track["danceability"] is not None and track["danceability"] >= value,
    "min_mood_party": lambda track, value: track["mood_party"] is not None and track["mood_party"] >= value,
    "min_mood_relaxed": lambda track, value: track["mood_relaxed"] is not None and track["mood_relaxed"] >= value,
}


def filter_tracks(tracks: list, preset_name: str, limit: int = 30) -> list:
    preset = PRESETS[preset_name]
    matches = [
        track for track in tracks
        if all(_THRESHOLD_CHECKS[key](track, value) for key, value in preset.items())
    ]
    return matches[:limit]
