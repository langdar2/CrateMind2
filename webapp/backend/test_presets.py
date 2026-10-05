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


def _scored(bpm, score, percentile):
    return dict(_track(bpm=bpm, danceability=0.5, mood_party=0.5, mood_relaxed=0.5),
                score=score, percentile=percentile)


def test_min_percentile_excludes_unscored_tracks():
    liked = _scored(120, score=4.0, percentile=90)
    unscored = _scored(121, score=None, percentile=None)
    result = presets.filter_by_criteria([unscored, liked], {"min_percentile": 50})
    assert [t["bpm"] for t in result] == [120]


def test_min_percentile_sorts_favourites_first():
    low = _scored(100, score=1.0, percentile=20)
    high = _scored(101, score=5.0, percentile=99)
    result = presets.filter_by_criteria([low, high], {"min_percentile": 10})
    assert [t["percentile"] for t in result] == [99, 20]


def test_ordering_uses_score_not_the_rounded_percentile():
    # Both land in the same percentile bucket; the finer score decides.
    a = _scored(100, score=4.1, percentile=90)
    b = _scored(101, score=4.9, percentile=90)
    result = presets.filter_by_criteria([a, b], {"min_percentile": 50})
    assert [t["score"] for t in result] == [4.9, 4.1]


def test_without_min_percentile_order_is_untouched():
    low = _scored(100, score=1.0, percentile=20)
    high = _scored(101, score=5.0, percentile=99)
    result = presets.filter_by_criteria([low, high], {"min_bpm": 50})
    assert [t["percentile"] for t in result] == [20, 99]


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
    test_min_percentile_excludes_unscored_tracks()
    test_min_percentile_sorts_favourites_first()
    test_ordering_uses_score_not_the_rounded_percentile()
    test_without_min_percentile_order_is_untouched()
    test_dedupe_keeps_first_copy_and_all_unidentified()
    test_dedupe_applies_before_the_limit()
    test_unknown_criteria_keys_are_ignored()
    print("All presets tests passed.")
