import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import similarity


def _track(path, embedding):
    return {"path": path, "embedding": np.array(embedding, dtype=np.float32)}


def test_ranks_by_cosine_similarity_descending():
    seed = _track("/seed.mp3", [1.0, 0.0, 0.0])
    close = _track("/close.mp3", [0.99, 0.01, 0.0])
    far = _track("/far.mp3", [0.0, 1.0, 0.0])
    tracks = [seed, far, close]

    result = similarity.top_similar(seed, tracks, limit=10)

    assert [t["path"] for t in result] == ["/close.mp3", "/far.mp3"]


def test_excludes_seed_even_if_present_in_input():
    seed = _track("/seed.mp3", [1.0, 0.0, 0.0])
    other = _track("/other.mp3", [1.0, 0.0, 0.0])
    tracks = [seed, other]

    result = similarity.top_similar(seed, tracks)

    assert all(t["path"] != "/seed.mp3" for t in result)


def _scored(path, embedding, percentile):
    return dict(_track(path, embedding), percentile=percentile)


def test_taste_weight_zero_keeps_pure_sound_ranking():
    seed = _scored("/seed.mp3", [1.0, 0.0], None)
    close_disliked = _scored("/close.mp3", [1.0, 0.02], 5)
    far_loved = _scored("/far.mp3", [0.0, 1.0], 99)

    result = similarity.top_similar(seed, [close_disliked, far_loved], taste_weight=0.0)

    assert [t["path"] for t in result] == ["/close.mp3", "/far.mp3"]


def test_full_taste_weight_puts_favourites_first():
    seed = _scored("/seed.mp3", [1.0, 0.0], None)
    close_disliked = _scored("/close.mp3", [1.0, 0.02], 5)
    far_loved = _scored("/far.mp3", [0.0, 1.0], 99)

    result = similarity.top_similar(seed, [close_disliked, far_loved], taste_weight=1.0)

    assert [t["path"] for t in result] == ["/far.mp3", "/close.mp3"]


def test_unscored_tracks_rank_as_average_not_as_worst():
    """Most of the library has no Apple score; it must not be buried."""
    seed = _scored("/seed.mp3", [1.0, 0.0], None)
    unscored = _scored("/unknown.mp3", [1.0, 0.0], None)
    disliked = _scored("/disliked.mp3", [1.0, 0.0], 1)
    loved = _scored("/loved.mp3", [1.0, 0.0], 99)

    result = similarity.top_similar(seed, [disliked, unscored, loved], taste_weight=1.0)

    assert [t["path"] for t in result] == ["/loved.mp3", "/unknown.mp3", "/disliked.mp3"]


def test_taste_cannot_reach_past_the_similarity_shortlist():
    """Seed mode must stay about sound: a favourite that sounds nothing like
    the seed stays out, however high the taste weight."""
    seed = _scored("/seed.mp3", [1.0, 0.0], None)
    # 25 near-identical tracks, then one much further away that is adored.
    near = [_scored(f"/near{i}.mp3", [1.0, 0.001 * i], 40) for i in range(25)]
    far_loved = _scored("/far_loved.mp3", [0.0, 1.0], 100)

    result = similarity.top_similar(seed, near + [far_loved], limit=2, taste_weight=1.0)

    assert all(t["path"] != "/far_loved.mp3" for t in result), [t["path"] for t in result]


def test_weighting_survives_tracks_without_a_percentile_key():
    """Callers that never ran the Apple import still pass plain track dicts."""
    seed = _track("/seed.mp3", [1.0, 0.0])
    other = _track("/other.mp3", [0.9, 0.1])

    result = similarity.top_similar(seed, [other], taste_weight=0.5)

    assert [t["path"] for t in result] == ["/other.mp3"]


def test_respects_limit():
    seed = _track("/seed.mp3", [1.0, 0.0])
    others = [_track(f"/t{i}.mp3", [1.0, 0.0]) for i in range(5)]

    result = similarity.top_similar(seed, others, limit=2)

    assert len(result) == 2


if __name__ == "__main__":
    test_ranks_by_cosine_similarity_descending()
    test_excludes_seed_even_if_present_in_input()
    test_taste_weight_zero_keeps_pure_sound_ranking()
    test_full_taste_weight_puts_favourites_first()
    test_unscored_tracks_rank_as_average_not_as_worst()
    test_taste_cannot_reach_past_the_similarity_shortlist()
    test_weighting_survives_tracks_without_a_percentile_key()
    test_respects_limit()
    print("All similarity tests passed.")
