import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import graph


def _track(artist, vec, percentile=None, bpm=120.0):
    return {
        "path": f"/music/{artist} - Album/01. {artist} - x.mp3",
        "artist": artist,
        "embedding": np.array(vec, dtype=np.float32),
        "percentile": percentile,
        "bpm": bpm,
    }


def _library():
    # Two sonic camps plus one artist too small to earn a centroid.
    punk = [_track("broilers", [1.0, 0.0, 0.0], 90) for _ in range(4)]
    punk += [_track("feine sahne", [0.98, 0.05, 0.0], 95) for _ in range(5)]
    schlager = [_track("helene fischer", [0.0, 1.0, 0.0]) for _ in range(6)]
    tiny = [_track("one hit wonder", [1.0, 0.0, 0.0]) for _ in range(2)]
    return punk + schlager + tiny


def test_small_artists_are_left_out():
    index = graph.build_index(_library())
    assert "one hit wonder" not in index["artists"]
    assert set(index["artists"]) == {"broilers", "feine sahne", "helene fischer"}


def test_neighbourhood_centres_on_the_artist_and_ranks_by_sound():
    result = graph.neighbourhood(graph.build_index(_library()), "broilers")

    assert result["center"] == "broilers"
    centre = [n for n in result["nodes"] if n["is_center"]]
    assert [n["id"] for n in centre] == ["broilers"]
    # The sonically close artist is included; the distant one falls below the
    # similarity floor and never enters the neighbourhood.
    ids = {n["id"] for n in result["nodes"]}
    assert "feine sahne" in ids
    assert "helene fischer" not in ids


def test_edges_connect_neighbours_to_each_other_not_just_the_centre():
    library = _library()
    library += [_track("sondaschule", [0.97, 0.08, 0.0], 80) for _ in range(4)]
    result = graph.neighbourhood(graph.build_index(library), "broilers")

    pairs = {frozenset((e["source"], e["target"])) for e in result["edges"]}
    assert frozenset(("feine sahne", "sondaschule")) in pairs, pairs


def test_unscored_artists_report_no_percentile():
    nodes = {n["id"]: n for n in
             graph.neighbourhood(graph.build_index(_library()), "helene fischer")["nodes"]}
    # Never played in Apple Music -> None, not 0, so the UI can grey it out.
    assert nodes["helene fischer"]["percentile"] is None
    assert nodes["helene fischer"]["track_count"] == 6


def test_unknown_artist_returns_none():
    assert graph.neighbourhood(graph.build_index(_library()), "nobody") is None


def test_empty_library_does_not_crash():
    index = graph.build_index([])
    assert index["artists"] == []
    assert graph.list_artists(index) == []


if __name__ == "__main__":
    test_small_artists_are_left_out()
    test_neighbourhood_centres_on_the_artist_and_ranks_by_sound()
    test_edges_connect_neighbours_to_each_other_not_just_the_centre()
    test_unscored_artists_report_no_percentile()
    test_unknown_artist_returns_none()
    test_empty_library_does_not_crash()
    print("All graph tests passed.")
