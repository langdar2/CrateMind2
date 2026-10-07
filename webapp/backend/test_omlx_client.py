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
    test_parse_prompt_to_criteria_raises_on_invalid_json()
    print("All omlx_client tests passed.")
