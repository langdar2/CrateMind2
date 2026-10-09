import collections
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


def test_cap_per_artist_keeps_the_first_five():
    tracks = [{"path": f"/x/{i}", "artist": "broilers"} for i in range(9)]
    tracks += [{"path": "/y/1", "artist": "falco"}]
    result = presets.cap_per_artist(tracks)
    assert [t["path"] for t in result] == [f"/x/{i}" for i in range(5)] + ["/y/1"]


def test_cap_per_artist_keeps_tracks_with_no_artist():
    tracks = [{"path": f"/x/{i}", "artist": ""} for i in range(9)]
    assert len(presets.cap_per_artist(tracks)) == 9


def test_filter_caps_artists_before_taking_the_limit():
    """Twenty Broilers tracks must not fill a twenty-track playlist."""
    pool = [dict(_track(bpm=120, danceability=0.9, mood_party=0.9, mood_relaxed=0.1),
                 path=f"/b/{i}.mp3", artist="broilers") for i in range(20)]
    pool += [dict(_track(bpm=121, danceability=0.9, mood_party=0.9, mood_relaxed=0.1),
                  path=f"/f/{i}.mp3", artist="falco") for i in range(20)]
    result = presets.filter_by_criteria(pool, {"min_bpm": 100}, limit=20)
    counts = collections.Counter(t["artist"] for t in result)
    assert counts["broilers"] == 5, counts
    assert counts["falco"] == 5, counts


def _mixed_pool():
    """40 well-liked tracks plus 40 the Apple export never scored."""
    liked = [_scored(120 + i, score=5.0 - i * 0.01, percentile=99) for i in range(40)]
    unknown = [_scored(120 + i, score=None, percentile=None) for i in range(40, 80)]
    for i, t in enumerate(liked + unknown):
        t["path"] = f"/x/{i}.mp3"
    return liked + unknown


def test_discovery_reserves_slots_for_unscored_tracks():
    result = presets.filter_by_criteria(_mixed_pool(), {"min_percentile": 50},
                                        limit=20, discovery=0.25)
    unscored = [t for t in result if t["percentile"] is None]
    assert len(result) == 20
    assert len(unscored) == 5, len(unscored)


def test_discovery_picks_differ_between_calls():
    pool = _mixed_pool()
    runs = set()
    for _ in range(6):
        result = presets.filter_by_criteria(pool, {"min_percentile": 50}, limit=20, discovery=0.25)
        runs.add(tuple(t["path"] for t in result if t["percentile"] is None))
    assert len(runs) > 1, "discovery slots should vary between previews"


def test_discovery_respects_the_other_criteria():
    """Unheard tracks still have to fit the brief, only taste is waived."""
    pool = _mixed_pool()
    result = presets.filter_by_criteria(pool, {"min_percentile": 50, "min_bpm": 150},
                                        limit=20, discovery=0.5)
    assert all(t["bpm"] >= 150 for t in result), [t["bpm"] for t in result]


def test_discovery_does_nothing_without_a_taste_filter():
    """Without a taste threshold the list is already full of unheard music."""
    pool = _mixed_pool()
    a = presets.filter_by_criteria(pool, {"min_bpm": 100}, limit=20, discovery=0.5)
    b = presets.filter_by_criteria(pool, {"min_bpm": 100}, limit=20, discovery=0.5)
    assert [t["path"] for t in a] == [t["path"] for t in b]


def test_unknown_criteria_keys_are_ignored():
    tracks = [_track(bpm=140, danceability=0.9, mood_party=0.9, mood_relaxed=0.1)]
    result = presets.filter_by_criteria(tracks, {"vibe": "great"})
    assert len(result) == 1


NOW = 1_800_000_000.0
DAY = 86400.0


def _dated(name, days_ago, artist="a", **extra):
    # "artist" is what cap_per_artist groups on; load_ok_tracks always sets it.
    t = {"path": f"/music/{artist} - Album/{name}.mp3", "artist": artist,
         "first_seen": NOW - days_ago * DAY, "song_key": name}
    t.update(extra)
    return t


def test_fresh_quota_pulls_in_new_music_the_mode_buried():
    old = [_dated(f"old{i}", 400, artist=f"a{i}") for i in range(10)]
    new = [_dated(f"new{i}", 3, artist=f"b{i}") for i in range(5)]

    out = presets.weave_in_fresh(old, old + new, limit=10, share=0.2,
                                 max_age_days=60, now=NOW)

    assert len(out) == 10
    fresh = [t for t in out if t in new]
    assert len(fresh) == 2                      # 20% of 10
    assert out[0] in old                        # woven in, not prepended
    assert len({t["path"] for t in out}) == 10  # no duplicates


def test_fresh_quota_counts_new_music_the_mode_already_picked():
    """The quota is a floor on new music, not an extra helping of it."""
    new = [_dated(f"new{i}", 5, artist=f"b{i}") for i in range(10)]
    out = presets.weave_in_fresh(new, new, limit=10, share=0.2,
                                 max_age_days=60, now=NOW)
    assert out == new[:10]  # already all fresh, nothing to add


def test_fresh_quota_prefers_the_newest_and_skips_banned():
    old = [_dated(f"old{i}", 400, artist=f"a{i}") for i in range(10)]
    newest = _dated("newest", 1, artist="b")
    older_new = _dated("older_new", 50, artist="c")
    banned = _dated("banned", 2, artist="d", rating=-1)

    out = presets.weave_in_fresh(old, old + [older_new, banned, newest],
                                 limit=10, share=0.1, max_age_days=60, now=NOW)

    assert newest in out
    assert older_new not in out   # only one slot, newest wins
    assert banned not in out


def test_fresh_quota_ignores_tracks_outside_the_window_and_undated_ones():
    old = [_dated(f"old{i}", 400, artist=f"a{i}") for i in range(10)]
    stale = _dated("stale", 90, artist="b")
    undated = {"path": "/music/c - Album/undated.mp3", "first_seen": None}

    out = presets.weave_in_fresh(old, old + [stale, undated], limit=10,
                                 share=0.2, max_age_days=60, now=NOW)

    assert out == old[:10]  # nothing qualifies as fresh


def test_fresh_share_zero_leaves_the_list_alone():
    old = [_dated(f"old{i}", 400, artist=f"a{i}") for i in range(10)]
    new = [_dated("new", 1, artist="b")]
    assert presets.weave_in_fresh(old, old + new, limit=5, share=0.0,
                                  max_age_days=60, now=NOW) == old[:5]


def test_fresh_quota_still_returns_a_full_list_when_the_artist_cap_bites():
    """A big new import is all one artist, so the cap drops most of it; the
    list must be topped back up rather than handed back short."""
    old = [_dated(f"old{i}", 400, artist=f"a{i}") for i in range(20)]
    new = [_dated(f"new{i}", 2, artist="newband") for i in range(10)]

    out = presets.weave_in_fresh(old, old + new, limit=20, share=0.5,
                                 max_age_days=60, now=NOW)

    assert len(out) == 20
    assert len({t["path"] for t in out}) == 20
    newband = [t for t in out if t["artist"] == "newband"]
    assert len(newband) == presets.MAX_PER_ARTIST


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
    test_cap_per_artist_keeps_the_first_five()
    test_cap_per_artist_keeps_tracks_with_no_artist()
    test_filter_caps_artists_before_taking_the_limit()
    test_discovery_reserves_slots_for_unscored_tracks()
    test_discovery_picks_differ_between_calls()
    test_discovery_respects_the_other_criteria()
    test_discovery_does_nothing_without_a_taste_filter()
    test_unknown_criteria_keys_are_ignored()
    print("All presets tests passed.")
