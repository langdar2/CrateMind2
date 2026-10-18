import json
import os

import httpx

# Live configuration: starts from the environment, and the LLM page replaces it
# at runtime (see app.py), so a change needs no restart.
_config = {
    "base_url": os.environ.get("OMLX_BASE_URL", "http://192.168.0.3:8001"),
    "model": os.environ.get("OMLX_MODEL", "gemma-4-E4B-it-MLX-8bit"),
    "api_key": os.environ.get("OMLX_API_KEY", ""),
}


def set_config(base_url=None, model=None, api_key=None) -> None:
    """Replace the given settings; None leaves a setting as it is."""
    for key, value in (("base_url", base_url), ("model", model), ("api_key", api_key)):
        if value is not None:
            _config[key] = value.strip().rstrip("/") if key == "base_url" else value.strip()


def get_config() -> dict:
    return dict(_config)


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _post(body: dict, timeout: float):
    body = {**body, "model": _config["model"]}
    return httpx.post(f"{_config['base_url']}/v1/chat/completions", json=body,
                      headers=_headers(_config["api_key"]), timeout=timeout)


def list_models(base_url: str, api_key: str) -> list:
    """Model ids the server offers; raises OmlxError with a readable reason."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/v1/models",
                             headers=_headers(api_key), timeout=10.0)
    except httpx.HTTPError as e:
        raise OmlxError(f"Server nicht erreichbar: {e}") from e
    if response.status_code in (401, 403):
        raise OmlxError("API-Key fehlt oder ist falsch (HTTP %d)" % response.status_code)
    if response.status_code != 200:
        raise OmlxError(f"Server antwortete mit HTTP {response.status_code}")
    try:
        return [m["id"] for m in response.json()["data"]]
    except (KeyError, TypeError, ValueError) as e:
        raise OmlxError("Unerwartete Antwort der Modellliste") from e


def test_completion(base_url: str, api_key: str, model: str) -> str:
    """One tiny completion with the given settings; returns the answer text."""
    body = {"model": model, "max_tokens": 8, "temperature": 0.0,
            "messages": [{"role": "user", "content": "Antworte nur mit: ok"}]}
    try:
        response = httpx.post(f"{base_url.rstrip('/')}/v1/chat/completions", json=body,
                              headers=_headers(api_key), timeout=60.0)
    except httpx.HTTPError as e:
        raise OmlxError(f"Server nicht erreichbar: {e}") from e
    if response.status_code != 200:
        try:
            detail = response.json()
            detail = detail.get("error", detail)
            detail = detail.get("message", detail) if isinstance(detail, dict) else detail
        except ValueError:
            detail = response.text[:200]
        raise OmlxError(f"HTTP {response.status_code}: {detail}")
    try:
        return response.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise OmlxError("Unerwartete Antwort des Modells") from e

from presets import FILTER_COLUMNS

ALLOWED_CRITERIA_KEYS = {f"{bound}_{col}" for col in FILTER_COLUMNS for bound in ("min", "max")}

_SYSTEM_PROMPT = (
    "Convert the user's playlist mood/activity description into a JSON object "
    "of numeric thresholds. Allowed keys: " + ", ".join(sorted(ALLOWED_CRITERIA_KEYS)) + ". "
    "bpm is beats per minute (typically 60-180). "
    "Pick the direction of each limit deliberately: a 'min_' key says the "
    "value must be AT LEAST that high, a 'max_' key AT MOST. "
    "Slow, calm, relaxed, background or sleepy moods need a max_bpm "
    "(about 100-110); fast, workout, running or energetic moods need a "
    "min_bpm (about 125-135). Never give a calm description a min_bpm or an "
    "energetic one a max_bpm. "
    "Calm or gentle also means a LOW mood_aggressive (a max_, about 0.2-0.3, "
    "never 0.0) and a HIGH mood_relaxed (a min_, about 0.5-0.6). "
    "Energetic, party or workout means a HIGH mood_party or danceability "
    "(a min_, about 0.5-0.6) and never a max_ on them. "
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
        "messages": [
            {"role": "system", "content": _DESCRIPTION_PROMPT},
            {"role": "user", "content": _describe_tracks_fully(tracks)},
        ],
        "max_tokens": 150,
        "temperature": 0.7,
    }
    try:
        response = _post(body, 30.0)
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError):
        return None

    text = " ".join(text.strip().strip('"\'`*').split())
    return text[:MAX_DESCRIPTION_LENGTH] if text else None


MAX_RATE_TRACKS = 80


def rate_fit(theme: str, tracks: list) -> dict:
    """How well each track fits a theme, 0-10, from its artist and title.

    The mood sliders only know five audio values, so "romantic dinner with
    love songs" cannot be expressed in them - a children's lullaby is as
    gentle and untroubled as a ballad. Titles carry what audio cannot, and a
    local model reads them for free.

    Returns {index: score}, empty when the model is unavailable or answers
    with something unusable; callers then keep the order they already had.
    Tracks beyond MAX_RATE_TRACKS are not rated, to keep the answer short.
    """
    tracks = tracks[:MAX_RATE_TRACKS]
    if not tracks:
        return {}
    lines = "\n".join(
        f"{i}. {t['display']['artist']} - {t['display']['title']}"
        for i, t in enumerate(tracks)
    )
    body = {
        "messages": [{"role": "user", "content": (
            f"Du bewertest Songs für eine Playlist. Thema: \"{theme}\".\n"
            "Gib für JEDEN Song eine ganze Zahl von 0 bis 10 an: wie gut er zum "
            "Thema passt (10 = perfekt, 0 = passt nicht, z.B. Kinderlieder oder "
            "hektische Musik bei einem ruhigen Thema).\n"
            'Antworte NUR mit JSON, Schlüssel ist die Nummer: {"0": 7, "1": 2}\n\n'
            + lines)}],
        # Roughly 6 tokens per entry, with headroom.
        "max_tokens": 120 + 8 * len(tracks),
        "temperature": 0.0,
    }
    try:
        response = _post(body, 90.0)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError):
        return {}

    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}

    scores = {}
    for key, value in raw.items():
        if (str(key).isdigit() and int(key) < len(tracks)
                and isinstance(value, (int, float)) and not isinstance(value, bool)):
            scores[int(key)] = max(0, min(10, value))
    return scores


def suggest_playlist_name(tracks: list) -> str:
    """A name for this set of tracks, or None if the model is unavailable.

    Deliberately returns None instead of raising: the playlist is already
    built by the time anyone wants a name for it, so a local model being
    down must not break creating one.
    """
    if not tracks:
        return None
    body = {
        "messages": [
            {"role": "system", "content": _NAME_PROMPT},
            {"role": "user", "content": _describe_tracks(tracks)},
        ],
        "max_tokens": 30,
        # Unlike criteria parsing, this wants variety rather than determinism.
        "temperature": 0.8,
    }
    try:
        response = _post(body, 20.0)
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
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 200,
        "temperature": 0.0,
    }
    try:
        response = _post(body, 30.0)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPError as e:
        raise OmlxError(f"oMLX unreachable at {_config['base_url']}: {e}") from e
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
