import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import omlx_client


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._payload


def _chat_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def test_parse_prompt_to_criteria_parses_plain_json():
    payload = _chat_payload('{"min_bpm": 120, "min_danceability": 0.6}')
    with patch("omlx_client.httpx.post", return_value=FakeResponse(payload)):
        criteria = omlx_client.parse_prompt_to_criteria("energetic workout")
    assert criteria == {"min_bpm": 120, "min_danceability": 0.6}


def test_parse_prompt_to_criteria_strips_markdown_fence():
    payload = _chat_payload('```json\n{"max_bpm": 100}\n```')
    with patch("omlx_client.httpx.post", return_value=FakeResponse(payload)):
        criteria = omlx_client.parse_prompt_to_criteria("chill sunday")
    assert criteria == {"max_bpm": 100}


def test_parse_prompt_to_criteria_drops_unknown_keys():
    payload = _chat_payload('{"min_bpm": 120, "vibe": "great"}')
    with patch("omlx_client.httpx.post", return_value=FakeResponse(payload)):
        criteria = omlx_client.parse_prompt_to_criteria("something")
    assert criteria == {"min_bpm": 120}


def test_taste_threshold_survives_parsing():
    payload = _chat_payload('{"min_percentile": 90, "min_bpm": 120}')
    with patch("omlx_client.httpx.post", return_value=FakeResponse(payload)):
        criteria = omlx_client.parse_prompt_to_criteria("energiegeladen, nur was ich mag")
    assert criteria == {"min_percentile": 90, "min_bpm": 120}


def test_prompt_vocabulary_matches_what_the_filter_accepts():
    """The two drifted apart once and silently dropped taste from prompt mode."""
    import presets
    assert omlx_client.ALLOWED_CRITERIA_KEYS == set(presets._THRESHOLD_CHECKS)


def _tracks(n=3):
    return [{"artist": "broilers", "bpm": 120.0 + i, "path": f"/m/{i}"} for i in range(n)]


def test_name_suggestion_is_cleaned_up():
    """Models add quotes and trailing punctuation however they are told not to."""
    payload = _chat_payload('  "Punk am Montag."  ')
    with patch("omlx_client.httpx.post", return_value=FakeResponse(payload)):
        assert omlx_client.suggest_playlist_name(_tracks()) == "Punk am Montag"


def test_name_suggestion_returns_none_when_the_model_is_down():
    """A missing name must never block creating the playlist."""
    import httpx
    with patch("omlx_client.httpx.post", side_effect=httpx.ConnectError("refused")):
        assert omlx_client.suggest_playlist_name(_tracks()) is None


def test_name_suggestion_handles_an_empty_answer():
    with patch("omlx_client.httpx.post", return_value=FakeResponse(_chat_payload('""'))):
        assert omlx_client.suggest_playlist_name(_tracks()) is None


def test_name_suggestion_is_truncated_if_the_model_rambles():
    payload = _chat_payload("Hier ist ein Name " + "sehr " * 40 + "lang")
    with patch("omlx_client.httpx.post", return_value=FakeResponse(payload)):
        name = omlx_client.suggest_playlist_name(_tracks())
    assert len(name) <= omlx_client.MAX_NAME_LENGTH


def test_description_lists_distinct_artists_and_the_bpm_range():
    tracks = [{"artist": "broilers", "bpm": 100.0}, {"artist": "broilers", "bpm": 180.0},
              {"artist": "donots", "bpm": 140.0}]
    described = omlx_client._describe_tracks(tracks)
    assert "Broilers, Donots" in described
    assert "100-180 BPM" in described
    assert "3 Tracks" in described


def test_mood_words_only_report_clear_tendencies():
    """A mood near the middle says nothing and would only add noise."""
    calm = [{"mood_relaxed": 0.9, "mood_aggressive": 0.01, "mood_happy": 0.5}] * 3
    words = omlx_client._mood_words(calm)
    assert "entspannt" in words
    assert "sanft" in words
    # mood_happy sits at 0.5: neither label applies.
    assert "fröhlich" not in words and "düster" not in words


def test_description_mentions_the_mood():
    """Without this the model named a relaxed set from its BPM range alone."""
    tracks = [{"artist": "x", "bpm": 80.0, "mood_relaxed": 0.9, "mood_aggressive": 0.0}] * 3
    assert "Stimmung: entspannt" in omlx_client._describe_tracks(tracks)


def test_no_tracks_means_no_name():
    assert omlx_client.suggest_playlist_name([]) is None


def test_parse_prompt_to_criteria_raises_on_invalid_json():
    payload = _chat_payload("not json at all")
    with patch("omlx_client.httpx.post", return_value=FakeResponse(payload)):
        try:
            omlx_client.parse_prompt_to_criteria("something")
            assert False, "expected OmlxError"
        except omlx_client.OmlxError:
            pass


if __name__ == "__main__":
    test_parse_prompt_to_criteria_parses_plain_json()
    test_parse_prompt_to_criteria_strips_markdown_fence()
    test_parse_prompt_to_criteria_drops_unknown_keys()
    test_taste_threshold_survives_parsing()
    test_prompt_vocabulary_matches_what_the_filter_accepts()
    test_name_suggestion_is_cleaned_up()
    test_name_suggestion_returns_none_when_the_model_is_down()
    test_name_suggestion_handles_an_empty_answer()
    test_name_suggestion_is_truncated_if_the_model_rambles()
    test_description_lists_distinct_artists_and_the_bpm_range()
    test_mood_words_only_report_clear_tendencies()
    test_description_mentions_the_mood()
    test_no_tracks_means_no_name()
    test_parse_prompt_to_criteria_raises_on_invalid_json()
    print("All omlx_client tests passed.")
