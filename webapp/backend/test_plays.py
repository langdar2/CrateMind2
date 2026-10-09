import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plays


def test_media_id_is_pulled_from_a_stream_url():
    assert plays.media_id_from_url("http://192.168.0.3:8080/media/34910.m4a") == 34910
    assert plays.media_id_from_url("http://h/media/7/cover") == 7
    # Radio, another server, nothing playing: no id, no counting.
    assert plays.media_id_from_url("http://radio.example/stream.mp3") is None
    assert plays.media_id_from_url(None) is None


def test_paused_and_stopped_renderers_are_ignored():
    """VUIO keeps reporting the last URL after the music stops."""
    playing = {"renderers": [{"state": "playing", "current_url": "http://h/media/5.m4a"}]}
    paused = {"renderers": [{"state": "paused", "current_url": "http://h/media/5.m4a"}]}
    stopped = {"renderers": [{"state": "stopped", "current_url": "http://h/media/5.m4a"}]}

    assert plays.current_media_id(playing) == 5
    assert plays.current_media_id(paused) is None
    assert plays.current_media_id(stopped) is None
    assert plays.current_media_id({"renderers": []}) is None
    assert plays.current_media_id(None) is None


def test_a_track_held_long_enough_counts_as_played():
    t = plays.PlayTracker(min_play_seconds=30)
    assert t.observe(5, now=0) is None
    assert t.observe(5, now=20) is None
    assert t.observe(5, now=45) is None
    # Moving to the next track closes the previous one out.
    event = t.observe(6, now=50)
    assert event == (5, 45, True)


def test_a_track_dropped_early_is_recorded_as_a_skip():
    t = plays.PlayTracker(min_play_seconds=30)
    t.observe(5, now=0)
    t.observe(5, now=8)
    media_id, seconds, completed = t.observe(6, now=10)
    assert (media_id, completed) == (5, False)
    assert seconds == 8


def test_silence_closes_out_the_current_track():
    t = plays.PlayTracker(min_play_seconds=30)
    t.observe(5, now=0)
    t.observe(5, now=60)
    assert t.observe(None, now=63) == (5, 60, True)
    # ...and nothing is emitted twice.
    assert t.observe(None, now=70) is None


def test_replaying_the_same_track_counts_twice():
    t = plays.PlayTracker(min_play_seconds=30)
    t.observe(5, now=0)
    t.observe(5, now=40)
    assert t.observe(None, now=45)[0] == 5
    t.observe(5, now=50)
    t.observe(5, now=95)
    assert t.flush() == (5, 45, True)


if __name__ == "__main__":
    test_media_id_is_pulled_from_a_stream_url()
    test_paused_and_stopped_renderers_are_ignored()
    test_a_track_held_long_enough_counts_as_played()
    test_a_track_dropped_early_is_recorded_as_a_skip()
    test_silence_closes_out_the_current_track()
    test_replaying_the_same_track_counts_twice()
    print("All plays tests passed.")
