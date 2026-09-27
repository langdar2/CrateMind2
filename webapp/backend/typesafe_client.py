import os

import httpx

TYPESAFE_BASE_URL = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1/systemone")
TYPESAFE_API_KEY = os.environ.get("TYPESAFE_API_KEY")
TYPESAFE_MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")

VIBE_CRITERIA = [
    {"what": "Does not fit the described vibe at all"},
    {"what": "Fits weakly"},
    {"what": "Fits reasonably well"},
    {"what": "Fits well"},
    {"what": "Fits the vibe perfectly"},
]


class TypesafeError(Exception):
    pass


def score_vibe_fit(mood_prompt: str, track: dict) -> float:
    if not TYPESAFE_API_KEY:
        raise TypesafeError("TYPESAFE_API_KEY not configured")

    body = {
        "model": TYPESAFE_MODEL,
        "state": {
            "mood_prompt": mood_prompt,
            "track": {
                "filename": track["path"].rsplit("/", 1)[-1],
                "bpm": track["bpm"],
                "key": track["key"],
                "mood_happy": track["mood_happy"],
                "mood_aggressive": track["mood_aggressive"],
                "mood_relaxed": track["mood_relaxed"],
                "mood_party": track["mood_party"],
                "danceability": track["danceability"],
            },
        },
        "questions": {
            "vibe_fit": {
                "type": "score",
                "instructions": "How well does this track fit the described mood/vibe?",
                "criteria": VIBE_CRITERIA,
            }
        },
    }
    headers = {"Authorization": f"Bearer {TYPESAFE_API_KEY}", "Content-Type": "application/json"}

    try:
        response = httpx.post(TYPESAFE_BASE_URL, json=body, headers=headers, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as e:
        raise TypesafeError(f"TypeSafe unreachable at {TYPESAFE_BASE_URL}: {e}") from e

    try:
        return payload["answers"]["vibe_fit"]["score"]
    except (KeyError, TypeError) as e:
        raise TypesafeError(f"unexpected response shape from TypeSafe: {e}") from e


def rank_by_vibe(mood_prompt: str, tracks: list, limit: int) -> list:
    # ponytail: one Jev call per candidate track; candidate pool is capped
    # upstream (app.py) to keep this bounded, batch if that cap ever grows.
    scored = [(score_vibe_fit(mood_prompt, t), t) for t in tracks]
    scored.sort(key=lambda scored_track: -scored_track[0])
    return [t for _, t in scored[:limit]]
