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


def test_min_score_excludes_unscored_tracks():
    liked = dict(_track(bpm=120, danceability=0.5, mood_party=0.5, mood_relaxed=0.5), score=4.0)
    unscored = dict(_track(bpm=121, danceability=0.5, mood_party=0.5, mood_relaxed=0.5), score=None)
    result = presets.filter_by_criteria([unscored, liked], {"min_score": 1.0})
    assert [t["bpm"] for t in result] == [120]


def test_min_score_sorts_favourites_first():
    low = dict(_track(bpm=100, danceability=0.5, mood_party=0.5, mood_relaxed=0.5), score=1.0)
    high = dict(_track(bpm=101, danceability=0.5, mood_party=0.5, mood_relaxed=0.5), score=5.0)
    result = presets.filter_by_criteria([low, high], {"min_score": 0.5})
    assert [t["score"] for t in result] == [5.0, 1.0]


def test_without_min_score_order_is_untouched():
    low = dict(_track(bpm=100, danceability=0.5, mood_party=0.5, mood_relaxed=0.5), score=1.0)
    high = dict(_track(bpm=101, danceability=0.5, mood_party=0.5, mood_relaxed=0.5), score=5.0)
    result = presets.filter_by_criteria([low, high], {"min_bpm": 50})
    assert [t["score"] for t in result] == [1.0, 5.0]


def test_dedupe_keeps_first_copy_and_all_unidentified():
    a1 = {"path": "/a1", "song_key": "falco|vienna"}
    a2 = {"path": "/a2", "song_key": "falco|vienna"}
    b = {"path": "/b", "song_key": "nena|99"}
    unknown1 = {"path": "/u1", "song_key": None}
    unknown2 = {"path": "/u2", "song_key": None}
    result = presets.dedupe_by_song([a1, a2, b, unknown1, unknown2])
    assert [t["path"] for t in result] == ["/a1", "/b", "/u1", "/u2"]


def test_dedupe_applies_before_the_limit():
    dupes = [dict(_track(bpm=120, danceability=0.9, mood_party=0.9, mood_relaxed=0.1),
                  song_key="same") for _ in range(5)]
    other = dict(_track(bpm=121, danceability=0.9, mood_party=0.9, mood_relaxed=0.1), song_key="other")
    result = presets.filter_by_criteria(dupes + [other], {"min_danceability": 0.5}, limit=2)
    assert [t["song_key"] for t in result] == ["same", "other"]


def test_unknown_criteria_keys_are_ignored():
    tracks = [_track(bpm=140, danceability=0.9, mood_party=0.9, mood_relaxed=0.1)]
    result = presets.filter_by_criteria(tracks, {"vibe": "great"})
    assert len(result) == 1


if __name__ == "__main__":
    test_filters_by_bpm_and_danceability()
    test_filters_by_relaxed_mood()
    test_respects_limit()
    test_min_score_excludes_unscored_tracks()
    test_min_score_sorts_favourites_first()
    test_without_min_score_order_is_untouched()
    test_dedupe_keeps_first_copy_and_all_unidentified()
    test_dedupe_applies_before_the_limit()
    test_unknown_criteria_keys_are_ignored()
    print("All presets tests passed.")
