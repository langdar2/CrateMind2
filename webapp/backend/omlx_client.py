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


_NAME_PROMPT = (
    "Du erfindest Namen für Musik-Playlists. Antworte mit NUR dem Namen: "
    "höchstens vier Wörter, keine Anführungszeichen, keine Erklärung, "
    "kein Punkt am Ende. Deutsch, außer die Musik ist klar englischsprachig."
)

# A name is a nicety, not a feature: anything longer is a model that ignored
# the instruction and started explaining itself.
MAX_NAME_LENGTH = 60


class OmlxError(Exception):
    pass


def _mood_words(tracks: list) -> list:
    """The moods that actually characterise this selection.

    Without these the model names a playlist from its BPM range alone, which
    produced "Pop Hits Goldene Ära" for a set averaging 0.90 on relaxed.
    Only clear tendencies are reported - a mood sitting near the middle says
    nothing and would just add noise.
    """
    labels = {"mood_relaxed": ("entspannt", "treibend"),
              "mood_happy": ("fröhlich", "düster"),
              "mood_aggressive": ("aggressiv", "sanft"),
              "mood_party": ("Party", "zurückhaltend"),
              "danceability": ("tanzbar", "unrhythmisch")}
    words = []
    for key, (high, low) in labels.items():
        values = [t[key] for t in tracks if t.get(key) is not None]
        if not values:
            continue
        average = sum(values) / len(values)
        if average >= 0.65:
            words.append(high)
        elif average <= 0.2:
            words.append(low)
    return words


def _describe_tracks(tracks: list) -> str:
    """Condense a preview into the few facts worth naming it after."""
    artists = []
    for track in tracks:
        artist = track.get("artist")
        if artist and artist not in artists:
            artists.append(artist)
    bpms = [t["bpm"] for t in tracks if t.get("bpm")]

    parts = [f"Künstler: {', '.join(a.title() for a in artists[:6])}"] if artists else []
    if bpms:
        parts.append(f"{round(min(bpms))}-{round(max(bpms))} BPM")
    moods = _mood_words(tracks)
    if moods:
        parts.append("Stimmung: " + ", ".join(moods))
    parts.append(f"{len(tracks)} Tracks")
    return ". ".join(parts)


_DESCRIPTION_PROMPT = (
    "Du schreibst kurze Beschreibungen für Musik-Playlists. "
    "Ein bis zwei Sätze, höchstens 200 Zeichen. Beschreibe die Stimmung und "
    "was den Hörer erwartet. Keine Aufzählung aller Künstler, keine "
    "Anführungszeichen, keine Überschrift. Deutsch."
)

MAX_DESCRIPTION_LENGTH = 300


def _describe_tracks_fully(tracks: list) -> str:
    """Like _describe_tracks, plus a few titles.

    Titles carry information the aggregates lose - a set can be 120 BPM and
    "fröhlich" and still be Christmas music, which only the titles reveal.
    """
    base = _describe_tracks(tracks)
    titles = []
    for track in tracks[:8]:
        name = track.get("path", "").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if name:
            titles.append(name)
    return f"{base}. Beispieltitel: {'; '.join(titles)}" if titles else base


def suggest_playlist_description(tracks: list) -> str:
    """A one-or-two sentence description, or None if the model is unavailable."""
    if not tracks:
        return None
    body = {
        "model": OMLX_MODEL,
        "messages": [
            {"role": "system", "content": _DESCRIPTION_PROMPT},
            {"role": "user", "content": _describe_tracks_fully(tracks)},
        ],
        "max_tokens": 150,
        "temperature": 0.7,
    }
    try:
        response = httpx.post(f"{OMLX_BASE_URL}/v1/chat/completions", json=body, timeout=30.0)
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError):
        return None

    text = " ".join(text.strip().strip('"\'`*').split())
    return text[:MAX_DESCRIPTION_LENGTH] if text else None


def suggest_playlist_name(tracks: list) -> str:
    """A name for this set of tracks, or None if the model is unavailable.

    Deliberately returns None instead of raising: the playlist is already
    built by the time anyone wants a name for it, so a local model being
    down must not break creating one.
    """
    if not tracks:
        return None
    body = {
        "model": OMLX_MODEL,
        "messages": [
            {"role": "system", "content": _NAME_PROMPT},
            {"role": "user", "content": _describe_tracks(tracks)},
        ],
        "max_tokens": 30,
        # Unlike criteria parsing, this wants variety rather than determinism.
        "temperature": 0.8,
    }
    try:
        response = httpx.post(f"{OMLX_BASE_URL}/v1/chat/completions", json=body, timeout=20.0)
        response.raise_for_status()
        name = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError):
        return None

    # Models wrap names in quotes and add trailing punctuation despite being told not to.
    name = name.strip().strip('"\'`*').rstrip(".").strip()
    name = " ".join(name.split())
    return name[:MAX_NAME_LENGTH] if name else None


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
