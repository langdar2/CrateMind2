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


def test_respects_limit():
    seed = _track("/seed.mp3", [1.0, 0.0])
    others = [_track(f"/t{i}.mp3", [1.0, 0.0]) for i in range(5)]

    result = similarity.top_similar(seed, others, limit=2)

    assert len(result) == 2


if __name__ == "__main__":
    test_ranks_by_cosine_similarity_descending()
    test_excludes_seed_even_if_present_in_input()
    test_respects_limit()
    print("All similarity tests passed.")
