import json
import os

import httpx

OMLX_BASE_URL = os.environ.get("OMLX_BASE_URL", "http://192.168.0.3:8001")
OMLX_MODEL = os.environ.get("OMLX_MODEL", "gemma-4-E4B-it-MLX-8bit")

from presets import FILTER_COLUMNS

ALLOWED_CRITERIA_KEYS = {f"{bound}_{col}" for col in FILTER_COLUMNS for bound in ("min", "max")}

_SYSTEM_PROMPT = (
    "Convert the user's playlist mood/activity description into a JSON object "
    "of numeric thresholds. Allowed keys: " + ", ".join(sorted(ALLOWED_CRITERIA_KEYS)) + ". "
    "bpm is beats per minute (typically 60-180). "
    "percentile is how much the listener likes a track, 0-100: min_percentile 90 "
    "keeps only their top 10%, 50 keeps the better-liked half. Use it when the "
    "description asks for favourites or well-liked music. "
    "All other values range 0.0-1.0. "
    "Only include keys clearly implied by the description. "
    "Respond with ONLY the JSON object, no explanation, no markdown."
)


class OmlxError(Exception):
    pass


def parse_prompt_to_criteria(prompt: str) -> dict:
    body = {
        "model": OMLX_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 200,
        "temperature": 0.0,
    }
    try:
        response = httpx.post(f"{OMLX_BASE_URL}/v1/chat/completions", json=body, timeout=30.0)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPError as e:
        raise OmlxError(f"oMLX unreachable at {OMLX_BASE_URL}: {e}") from e
    except (KeyError, IndexError, TypeError) as e:
        raise OmlxError(f"unexpected response shape from oMLX: {e}") from e

    # ponytail: local models like wrapping JSON in ```json fences despite instructions; strip them.
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    try:
        criteria = json.loads(content)
    except json.JSONDecodeError as e:
        raise OmlxError(f"oMLX did not return valid JSON: {content!r}") from e

    if not isinstance(criteria, dict):
        raise OmlxError(f"oMLX did not return a JSON object: {content!r}")
    return {k: v for k, v in criteria.items() if k in ALLOWED_CRITERIA_KEYS and isinstance(v, (int, float))}
