import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import typesafe_client


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


TRACK = {
    "path": "/music/a.mp3",
    "bpm": 120,
    "key": "C major",
    "mood_happy": 0.5,
    "mood_aggressive": 0.1,
    "mood_relaxed": 0.7,
    "mood_party": 0.3,
    "danceability": 0.6,
}


def test_score_vibe_fit_parses_score():
    payload = {"model": "jev-1.0", "answers": {"vibe_fit": {"type": "score", "score": 3.5}}}
    with patch.object(typesafe_client, "TYPESAFE_API_KEY", "test-key"), \
         patch("typesafe_client.httpx.post", return_value=FakeResponse(payload)):
        score = typesafe_client.score_vibe_fit("chill sunday", TRACK)
    assert score == 3.5


def test_score_vibe_fit_raises_without_api_key():
    with patch.object(typesafe_client, "TYPESAFE_API_KEY", None):
        try:
            typesafe_client.score_vibe_fit("chill sunday", TRACK)
            assert False, "expected TypesafeError"
        except typesafe_client.TypesafeError:
            pass


def test_score_vibe_fit_raises_on_malformed_response():
    with patch.object(typesafe_client, "TYPESAFE_API_KEY", "test-key"), \
         patch("typesafe_client.httpx.post", return_value=FakeResponse({})):
        try:
            typesafe_client.score_vibe_fit("chill sunday", TRACK)
            assert False, "expected TypesafeError"
        except typesafe_client.TypesafeError:
            pass


def test_rank_by_vibe_sorts_descending():
    scores = iter([1.0, 4.0, 2.0])
    tracks = [dict(TRACK, path=f"/music/{i}.mp3") for i in range(3)]
    with patch.object(typesafe_client, "score_vibe_fit", side_effect=lambda prompt, t: next(scores)):
        ranked = typesafe_client.rank_by_vibe("chill sunday", tracks, limit=2)
    assert [t["path"] for t in ranked] == ["/music/1.mp3", "/music/2.mp3"]


if __name__ == "__main__":
    test_score_vibe_fit_parses_score()
    test_score_vibe_fit_raises_without_api_key()
    test_score_vibe_fit_raises_on_malformed_response()
    test_rank_by_vibe_sorts_descending()
    print("All typesafe_client tests passed.")
