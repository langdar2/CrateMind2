import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import presets


def _track(bpm, danceability, mood_party, mood_relaxed):
    return {
        "path": f"/x/{bpm}-{danceability}.mp3",
        "bpm": bpm,
        "danceability": danceability,
        "mood_party": mood_party,
        "mood_relaxed": mood_relaxed,
    }


def test_filters_by_bpm_and_danceability():
    tracks = [
        _track(bpm=140, danceability=0.8, mood_party=0.5, mood_relaxed=0.1),
        _track(bpm=80, danceability=0.2, mood_party=0.1, mood_relaxed=0.7),
    ]
    result = presets.filter_by_criteria(tracks, {"min_bpm": 120, "min_danceability": 0.6})
    assert len(result) == 1
    assert result[0]["bpm"] == 140


def test_filters_by_relaxed_mood():
    tracks = [
        _track(bpm=140, danceability=0.8, mood_party=0.5, mood_relaxed=0.1),
        _track(bpm=80, danceability=0.2, mood_party=0.1, mood_relaxed=0.7),
    ]
    result = presets.filter_by_criteria(tracks, {"max_bpm": 100, "min_mood_relaxed": 0.5})
    assert len(result) == 1
    assert result[0]["mood_relaxed"] == 0.7


def test_respects_limit():
    tracks = [_track(bpm=140, danceability=0.9, mood_party=0.9, mood_relaxed=0.1) for _ in range(5)]
    result = presets.filter_by_criteria(tracks, {"min_danceability": 0.5}, limit=2)
    assert len(result) == 2


def test_unknown_criteria_keys_are_ignored():
    tracks = [_track(bpm=140, danceability=0.9, mood_party=0.9, mood_relaxed=0.1)]
    result = presets.filter_by_criteria(tracks, {"vibe": "great"})
    assert len(result) == 1


if __name__ == "__main__":
    test_filters_by_bpm_and_danceability()
    test_filters_by_relaxed_mood()
    test_respects_limit()
    test_unknown_criteria_keys_are_ignored()
    print("All presets tests passed.")
