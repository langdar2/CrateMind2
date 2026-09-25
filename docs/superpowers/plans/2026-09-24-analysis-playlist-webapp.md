# Analyse- & Playlist-Web-App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein FastAPI-Backend + React-Frontend, das die vorhandene
`library.db` (Essentia-Analyse) für ein Dashboard und Playlist-Generierung
nutzt und generierte Playlists direkt in VuIO anlegt und castet.

**Architecture:** Backend liest read-only aus `library.db`, hält alle
`status='ok'`-Tracks samt Embeddings im Speicher (geladen beim Start),
bietet REST-Endpunkte für Stats/Presets/Track-Suche/Playlist-Vorschau, und
spricht für Playlist-Anlage/Casting mit VuIOs MCP-HTTP-Endpunkt
(`POST /mcp`, JSON-RPC `tools/call`). Frontend ist eine React-SPA
(Top-Nav-Layout: Dashboard / Playlists / Renderer), gebaut mit Vite,
gegen das Backend als statische Dateien ausgeliefert. Siehe
[Design-Spec](../specs/2026-09-24-analysis-playlist-webapp-design.md).

**Wichtiger Implementierungsfund (nicht im Spec-Dokument, hier
festgehalten):** VuIO hat keine REST-Endpunkte für Playlist-CRUD. Playlists
werden ausschließlich über VuIOs eingebauten MCP-Server verwaltet
(`POST /mcp`, siehe `docs/mcp.md` im VuIO-Repo:
https://github.com/vuiodev/vuio/blob/main/docs/mcp.md). Das genaue
Protokoll (Request-/Response-Format, Tool-Namen `create_playlist`,
`add_to_playlist`, `list_renderers`, `cast_playlist_to_renderer`,
`get_playback_status`, `search_media`) wurde gegen den echten Server auf
`minime-3.local` (`192.168.0.54:8080`) verifiziert (siehe Task 4).

**Tech Stack:** Python 3.11, FastAPI, `httpx`, `numpy`, SQLite (stdlib
`sqlite3`); React 18, Vite, `react-router-dom`, `recharts`; Docker,
Docker Compose.

---

## File Structure

```
webapp/
  backend/
    requirements.txt
    app.py            # FastAPI-App, alle Endpunkte
    db.py             # Read-only Zugriff auf library.db
    presets.py        # Preset-Definitionen + Filterlogik
    similarity.py      # Cosine-Similarity-Ranking
    vuio_client.py     # VuIO-MCP-HTTP-Client
    test_db.py
    test_presets.py
    test_similarity.py
    test_vuio_client.py
    test_app.py
  frontend/
    package.json
    vite.config.js
    index.html
    src/
      main.jsx
      App.jsx
      api.js
      index.css
      pages/
        Dashboard.jsx
        Playlists.jsx
        Renderers.jsx
  Dockerfile
docker-compose.yml   # bestehende Datei, neuer `webapp`-Service
```

---

### Task 1: Backend-Grundgerüst + Datenbank-Layer

**Files:**
- Create: `webapp/backend/requirements.txt`
- Create: `webapp/backend/db.py`
- Create: `webapp/backend/test_db.py`

- [ ] **Step 1: `requirements.txt` anlegen**

```
fastapi
uvicorn
httpx
numpy
```

- [ ] **Step 2: Fehlschlagenden Test schreiben**

`webapp/backend/test_db.py`:
```python
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np

from crate_mind.analysis import db as analysis_db
import db


def _make_test_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = analysis_db.get_connection(tmp.name)

    analysis_db.upsert_track(conn, "/music/a.mp3", mtime=1.0, size=100, status="ok")
    analysis_db.upsert_features(conn, "/music/a.mp3", {
        "bpm": 120.0, "key": "C major",
        "mood_happy": 0.8, "mood_aggressive": 0.1, "mood_relaxed": 0.2,
        "mood_party": 0.7, "danceability": 0.9,
        "embedding": np.ones(200, dtype=np.float32),
    })

    analysis_db.upsert_track(conn, "/music/b.mp3", mtime=1.0, size=100, status="ok")
    analysis_db.upsert_features(conn, "/music/b.mp3", {
        "bpm": 90.0, "key": "A minor",
        "mood_happy": 0.3, "mood_aggressive": 0.2, "mood_relaxed": 0.6,
        "mood_party": 0.2, "danceability": 0.4,
        "embedding": np.zeros(200, dtype=np.float32),
    })

    analysis_db.upsert_track(conn, "/music/c.mp3", mtime=1.0, size=100, status="failed")
    conn.close()
    return tmp.name


def test_fetch_stats_counts_status_and_aggregates():
    path = _make_test_db()
    conn = db.get_connection(path)

    stats = db.fetch_stats(conn)

    assert stats["status_counts"]["ok"] == 2
    assert stats["status_counts"]["failed"] == 1
    assert stats["key_counts"] == {"C major": 1, "A minor": 1}
    assert any(b["bucket"] == "120-140" and b["count"] == 1 for b in stats["bpm_histogram"])
    assert any(b["bucket"] == "80-100" and b["count"] == 1 for b in stats["bpm_histogram"])
    assert abs(stats["mood_averages"]["mood_happy"] - 0.55) < 1e-6


def test_load_ok_tracks_returns_only_ok_with_embedding():
    path = _make_test_db()
    conn = db.get_connection(path)

    tracks = db.load_ok_tracks(conn)

    assert {t["path"] for t in tracks} == {"/music/a.mp3", "/music/b.mp3"}
    a = next(t for t in tracks if t["path"] == "/music/a.mp3")
    assert a["embedding"].shape == (200,)
    assert a["bpm"] == 120.0


def test_search_ok_tracks_matches_substring():
    path = _make_test_db()
    conn = db.get_connection(path)

    results = db.search_ok_tracks(conn, "a.mp3")

    assert [r["path"] for r in results] == ["/music/a.mp3"]


if __name__ == "__main__":
    test_fetch_stats_counts_status_and_aggregates()
    test_load_ok_tracks_returns_only_ok_with_embedding()
    test_search_ok_tracks_matches_substring()
    print("All db tests passed.")
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag bestätigen**

Run: `python webapp/backend/test_db.py`
Expected: `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 4: `db.py` implementieren**

`webapp/backend/db.py`:
```python
import sqlite3

import numpy as np

MOOD_COLUMNS = ["mood_happy", "mood_aggressive", "mood_relaxed", "mood_party", "danceability"]


def get_connection(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _bpm_histogram(bpms: list, bucket_size: int = 20) -> list:
    buckets = {}
    for bpm in bpms:
        lo = int(bpm // bucket_size) * bucket_size
        label = f"{lo}-{lo + bucket_size}"
        buckets[label] = buckets.get(label, 0) + 1
    return [
        {"bucket": label, "count": count}
        for label, count in sorted(buckets.items(), key=lambda kv: int(kv[0].split("-")[0]))
    ]


def fetch_stats(conn: sqlite3.Connection) -> dict:
    status_counts = dict(conn.execute("SELECT status, COUNT(*) FROM tracks GROUP BY status").fetchall())

    bpms = [row[0] for row in conn.execute("SELECT bpm FROM features WHERE bpm IS NOT NULL").fetchall()]
    key_counts = {}
    for (key,) in conn.execute("SELECT key FROM features WHERE key IS NOT NULL").fetchall():
        key_counts[key] = key_counts.get(key, 0) + 1

    mood_averages = {}
    for column in MOOD_COLUMNS:
        avg = conn.execute(f"SELECT AVG({column}) FROM features WHERE {column} IS NOT NULL").fetchone()[0]
        mood_averages[column] = avg if avg is not None else 0.0

    return {
        "status_counts": status_counts,
        "bpm_histogram": _bpm_histogram(bpms),
        "key_counts": key_counts,
        "mood_averages": mood_averages,
    }


def load_ok_tracks(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        """
        SELECT t.path, f.bpm, f.key, f.mood_happy, f.mood_aggressive, f.mood_relaxed,
               f.mood_party, f.danceability, f.embedding
        FROM tracks t JOIN features f ON f.path = t.path
        WHERE t.status = 'ok' AND f.embedding IS NOT NULL
        """
    ).fetchall()

    tracks = []
    for path, bpm, key, happy, aggressive, relaxed, party, dance, emb_blob in rows:
        tracks.append({
            "path": path,
            "bpm": bpm,
            "key": key,
            "mood_happy": happy,
            "mood_aggressive": aggressive,
            "mood_relaxed": relaxed,
            "mood_party": party,
            "danceability": dance,
            "embedding": np.frombuffer(emb_blob, dtype=np.float32),
        })
    return tracks


def search_ok_tracks(conn: sqlite3.Connection, query: str, limit: int = 20) -> list:
    like = f"%{query}%"
    rows = conn.execute(
        """
        SELECT t.path, f.bpm, f.key
        FROM tracks t JOIN features f ON f.path = t.path
        WHERE t.status = 'ok' AND t.path LIKE ?
        LIMIT ?
        """,
        (like, limit),
    ).fetchall()
    return [{"path": path, "bpm": bpm, "key": key} for path, bpm, key in rows]
```

- [ ] **Step 5: Test laufen lassen, Erfolg bestätigen**

Run: `python webapp/backend/test_db.py`
Expected: `All db tests passed.`

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/requirements.txt webapp/backend/db.py webapp/backend/test_db.py
git commit -m "feat(webapp): add read-only db layer with stats, track loading and search"
```

---

### Task 2: Presets + Preset-Filter

**Files:**
- Create: `webapp/backend/presets.py`
- Create: `webapp/backend/test_presets.py`

- [ ] **Step 1: Fehlschlagenden Test schreiben**

`webapp/backend/test_presets.py`:
```python
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


def test_workout_filters_by_bpm_and_danceability():
    tracks = [
        _track(bpm=140, danceability=0.8, mood_party=0.5, mood_relaxed=0.1),
        _track(bpm=80, danceability=0.2, mood_party=0.1, mood_relaxed=0.7),
    ]
    result = presets.filter_tracks(tracks, "workout")
    assert len(result) == 1
    assert result[0]["bpm"] == 140


def test_chill_filters_by_relaxed_mood():
    tracks = [
        _track(bpm=140, danceability=0.8, mood_party=0.5, mood_relaxed=0.1),
        _track(bpm=80, danceability=0.2, mood_party=0.1, mood_relaxed=0.7),
    ]
    result = presets.filter_tracks(tracks, "chill")
    assert len(result) == 1
    assert result[0]["mood_relaxed"] == 0.7


def test_filter_tracks_respects_limit():
    tracks = [_track(bpm=140, danceability=0.9, mood_party=0.9, mood_relaxed=0.1) for _ in range(5)]
    result = presets.filter_tracks(tracks, "party", limit=2)
    assert len(result) == 2


def test_unknown_preset_raises_key_error():
    try:
        presets.filter_tracks([], "does-not-exist")
        assert False, "expected KeyError"
    except KeyError:
        pass


if __name__ == "__main__":
    test_workout_filters_by_bpm_and_danceability()
    test_chill_filters_by_relaxed_mood()
    test_filter_tracks_respects_limit()
    test_unknown_preset_raises_key_error()
    print("All presets tests passed.")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python webapp/backend/test_presets.py`
Expected: `ModuleNotFoundError: No module named 'presets'`

- [ ] **Step 3: `presets.py` implementieren**

`webapp/backend/presets.py`:
```python
PRESETS = {
    "workout": {"min_bpm": 120, "min_danceability": 0.6},
    "chill": {"max_bpm": 100, "min_mood_relaxed": 0.5},
    "party": {"min_danceability": 0.6, "min_mood_party": 0.5},
}

_THRESHOLD_CHECKS = {
    "min_bpm": lambda track, value: track["bpm"] is not None and track["bpm"] >= value,
    "max_bpm": lambda track, value: track["bpm"] is not None and track["bpm"] <= value,
    "min_danceability": lambda track, value: track["danceability"] is not None and track["danceability"] >= value,
    "min_mood_party": lambda track, value: track["mood_party"] is not None and track["mood_party"] >= value,
    "min_mood_relaxed": lambda track, value: track["mood_relaxed"] is not None and track["mood_relaxed"] >= value,
}


def filter_tracks(tracks: list, preset_name: str, limit: int = 30) -> list:
    preset = PRESETS[preset_name]
    matches = [
        track for track in tracks
        if all(_THRESHOLD_CHECKS[key](track, value) for key, value in preset.items())
    ]
    return matches[:limit]
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `python webapp/backend/test_presets.py`
Expected: `All presets tests passed.`

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/presets.py webapp/backend/test_presets.py
git commit -m "feat(webapp): add preset definitions and threshold-based filtering"
```

---

### Task 3: Embedding-Similarity

**Files:**
- Create: `webapp/backend/similarity.py`
- Create: `webapp/backend/test_similarity.py`

- [ ] **Step 1: Fehlschlagenden Test schreiben**

`webapp/backend/test_similarity.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import similarity


def _track(path, embedding):
    return {"path": path, "embedding": np.array(embedding, dtype=np.float32)}


def test_ranks_by_cosine_similarity_descending():
    seed = _track("/seed.mp3", [1.0, 0.0, 0.0])
    close = _track("/close.mp3", [0.99, 0.01, 0.0])
    far = _track("/far.mp3", [0.0, 1.0, 0.0])
    tracks = [seed, far, close]

    result = similarity.top_similar(seed, tracks, limit=10)

    assert [t["path"] for t in result] == ["/close.mp3", "/far.mp3"]


def test_excludes_seed_even_if_present_in_input():
    seed = _track("/seed.mp3", [1.0, 0.0, 0.0])
    other = _track("/other.mp3", [1.0, 0.0, 0.0])
    tracks = [seed, other]

    result = similarity.top_similar(seed, tracks)

    assert all(t["path"] != "/seed.mp3" for t in result)


def test_respects_limit():
    seed = _track("/seed.mp3", [1.0, 0.0])
    others = [_track(f"/t{i}.mp3", [1.0, 0.0]) for i in range(5)]

    result = similarity.top_similar(seed, others, limit=2)

    assert len(result) == 2


if __name__ == "__main__":
    test_ranks_by_cosine_similarity_descending()
    test_excludes_seed_even_if_present_in_input()
    test_respects_limit()
    print("All similarity tests passed.")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python webapp/backend/test_similarity.py`
Expected: `ModuleNotFoundError: No module named 'similarity'`

- [ ] **Step 3: `similarity.py` implementieren**

`webapp/backend/similarity.py`:
```python
import numpy as np


def top_similar(seed: dict, tracks: list, limit: int = 30) -> list:
    others = [t for t in tracks if t["path"] != seed["path"]]
    if not others:
        return []

    embeddings = np.stack([t["embedding"] for t in others]).astype(np.float32)
    seed_vec = seed["embedding"].astype(np.float32)

    norms = np.linalg.norm(embeddings, axis=1)
    seed_norm = np.linalg.norm(seed_vec)
    scores = (embeddings @ seed_vec) / (norms * seed_norm + 1e-8)

    order = np.argsort(-scores)
    return [others[i] for i in order[:limit]]
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `python webapp/backend/test_similarity.py`
Expected: `All similarity tests passed.`

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/similarity.py webapp/backend/test_similarity.py
git commit -m "feat(webapp): add cosine-similarity based seed-track ranking"
```

---

### Task 4: VuIO-MCP-Client

**Files:**
- Create: `webapp/backend/vuio_client.py`
- Create: `webapp/backend/test_vuio_client.py`

**Kontext für den Implementierer:** VuIO hat keine REST-Endpunkte für
Playlists. Alles läuft über den MCP-HTTP-Endpunkt `POST {VUIO_BASE_URL}/mcp`
(JSON-RPC 2.0, `method: "tools/call"`). Protokoll-Details (verifiziert
gegen den echten Server auf `minime-3.local`):

- Header: `Content-Type: application/json`, `MCP-Protocol-Version: 2026-07-28`,
  `Mcp-Method: tools/call`, `Mcp-Name: <tool_name>`. Falls `VUIO_TOKEN`
  gesetzt ist: zusätzlich `Authorization: Bearer <token>`.
- Body: `{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "<tool_name>", "arguments": {...}, "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}}`
- Response ist eine JSON-RPC-Response. Das eigentliche Tool-Ergebnis steht
  entweder in `result.structuredContent` (bevorzugt) oder als JSON-String in
  `result.content[0].text` (Standard-MCP-Fallback) - beide Formen müssen
  unterstützt werden.
- Tools, die gebraucht werden: `list_renderers` (keine Argumente, liefert
  `{"renderers": [...]}`), `search_media` (`query`, `category`, `limit`,
  liefert `{"files": [{"id": ..., "path": ..., ...}]}`), `create_playlist`
  (`name`, liefert `{"playlist_id": ...}`), `add_to_playlist`
  (`playlist_id`, `media_file_ids`), `cast_playlist_to_renderer`
  (`playlist_id`, `renderer_id`), `get_playback_status` (`renderer_id`
  optional).

- [ ] **Step 1: Fehlschlagenden Test schreiben**

`webapp/backend/test_vuio_client.py`:
```python
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vuio_client


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


def test_call_tool_parses_structured_content():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"renderers": []}}}
    with patch("vuio_client.httpx.post", return_value=FakeResponse(payload)):
        result = vuio_client._call_tool("list_renderers", {})
    assert result == {"renderers": []}


def test_call_tool_parses_text_content_fallback():
    inner = json.dumps({"playlist_id": 42})
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": inner}]}}
    with patch("vuio_client.httpx.post", return_value=FakeResponse(payload)):
        result = vuio_client._call_tool("create_playlist", {"name": "x"})
    assert result == {"playlist_id": 42}


def test_call_tool_raises_vuio_error_on_jsonrpc_error():
    payload = {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "boom"}}
    with patch("vuio_client.httpx.post", return_value=FakeResponse(payload)):
        try:
            vuio_client._call_tool("list_renderers", {})
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


def test_create_playlist_creates_then_adds_resolved_file_ids():
    def fake_call_tool(name, arguments):
        if name == "create_playlist":
            return {"playlist_id": 7}
        if name == "search_media":
            return {"files": [{"id": 99, "path": "/music/a.mp3"}]}
        if name == "add_to_playlist":
            assert arguments == {"playlist_id": 7, "media_file_ids": [99]}
            return {"status": "ok"}
        raise AssertionError(f"unexpected tool call: {name}")

    with patch("vuio_client._call_tool", side_effect=fake_call_tool):
        playlist_id = vuio_client.create_playlist("My Playlist", ["/music/a.mp3"])

    assert playlist_id == 7


def test_find_file_id_raises_when_path_not_found():
    with patch("vuio_client._call_tool", return_value={"files": [{"id": 1, "path": "/other.mp3"}]}):
        try:
            vuio_client.find_file_id("/missing.mp3")
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


if __name__ == "__main__":
    test_call_tool_parses_structured_content()
    test_call_tool_parses_text_content_fallback()
    test_call_tool_raises_vuio_error_on_jsonrpc_error()
    test_create_playlist_creates_then_adds_resolved_file_ids()
    test_find_file_id_raises_when_path_not_found()
    print("All vuio_client tests passed.")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python webapp/backend/test_vuio_client.py`
Expected: `ModuleNotFoundError: No module named 'vuio_client'`

- [ ] **Step 3: `vuio_client.py` implementieren**

`webapp/backend/vuio_client.py`:
```python
import json
import os

import httpx

VUIO_BASE_URL = os.environ.get("VUIO_BASE_URL", "http://localhost:8080")
VUIO_TOKEN = os.environ.get("VUIO_TOKEN")
PROTOCOL_VERSION = "2026-07-28"


class VuioError(Exception):
    pass


def _call_tool(name: str, arguments: dict) -> dict:
    url = f"{VUIO_BASE_URL}/mcp"
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
            "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": name,
    }
    if VUIO_TOKEN:
        headers["Authorization"] = f"Bearer {VUIO_TOKEN}"

    try:
        response = httpx.post(url, json=body, headers=headers, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as e:
        raise VuioError(f"VuIO unreachable at {url}: {e}") from e

    if "error" in payload:
        raise VuioError(f"VuIO tool '{name}' failed: {payload['error']}")

    result = payload["result"]
    if "structuredContent" in result:
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


def list_renderers() -> list:
    return _call_tool("list_renderers", {})["renderers"]


def find_file_id(path: str) -> int:
    filename = path.rsplit("/", 1)[-1]
    # ponytail: one search_media call per track; fine for typical playlist
    # sizes (<100 tracks), batch if that ever becomes the bottleneck.
    results = _call_tool("search_media", {"query": filename, "category": "audio", "limit": 10})
    for f in results["files"]:
        if f["path"] == path:
            return f["id"]
    raise VuioError(f"Track not found in VuIO library: {path}")


def create_playlist(name: str, track_paths: list) -> int:
    created = _call_tool("create_playlist", {"name": name})
    playlist_id = created["playlist_id"]
    file_ids = [find_file_id(path) for path in track_paths]
    _call_tool("add_to_playlist", {"playlist_id": playlist_id, "media_file_ids": file_ids})
    return playlist_id


def cast_playlist(playlist_id: int, renderer_id: str) -> dict:
    return _call_tool("cast_playlist_to_renderer", {"playlist_id": playlist_id, "renderer_id": renderer_id})


def get_playback_status(renderer_id: str = None) -> dict:
    arguments = {"renderer_id": renderer_id} if renderer_id else {}
    return _call_tool("get_playback_status", arguments)
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `python webapp/backend/test_vuio_client.py`
Expected: `All vuio_client tests passed.`

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/vuio_client.py webapp/backend/test_vuio_client.py
git commit -m "feat(webapp): add VuIO MCP HTTP client for playlists, renderers and casting"
```

---

### Task 5: FastAPI-App verdrahten

**Files:**
- Create: `webapp/backend/app.py`
- Create: `webapp/backend/test_app.py`

- [ ] **Step 1: Fehlschlagenden Test schreiben**

`webapp/backend/test_app.py`:
```python
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
from fastapi.testclient import TestClient

from crate_mind.analysis import db as analysis_db


def _make_test_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = analysis_db.get_connection(tmp.name)
    analysis_db.upsert_track(conn, "/music/a.mp3", mtime=1.0, size=100, status="ok")
    analysis_db.upsert_features(conn, "/music/a.mp3", {
        "bpm": 120.0, "key": "C major",
        "mood_happy": 0.8, "mood_aggressive": 0.1, "mood_relaxed": 0.2,
        "mood_party": 0.7, "danceability": 0.9,
        "embedding": np.ones(200, dtype=np.float32),
    })
    conn.close()
    return tmp.name


os.environ["DB_PATH"] = _make_test_db()

import app as app_module
import vuio_client


def test_stats_endpoint_returns_counts():
    with TestClient(app_module.app) as client:
        response = client.get("/api/stats")
    assert response.status_code == 200
    assert response.json()["status_counts"]["ok"] == 1


def test_presets_endpoint_lists_presets():
    with TestClient(app_module.app) as client:
        response = client.get("/api/presets")
    assert "workout" in response.json()


def test_tracks_search_endpoint():
    with TestClient(app_module.app) as client:
        response = client.get("/api/tracks", params={"q": "a.mp3"})
    assert response.json()["tracks"][0]["path"] == "/music/a.mp3"


def test_preview_preset_mode():
    with TestClient(app_module.app) as client:
        response = client.post("/api/playlists/preview", json={"mode": "preset", "preset_name": "party"})
    assert response.status_code == 200
    assert response.json()["tracks"][0]["path"] == "/music/a.mp3"


def test_preview_unknown_seed_returns_404():
    with TestClient(app_module.app) as client:
        response = client.post("/api/playlists/preview", json={"mode": "seed", "seed_path": "/no/such.mp3"})
    assert response.status_code == 404


def test_create_playlist_maps_vuio_error_to_502():
    with patch.object(vuio_client, "create_playlist", side_effect=vuio_client.VuioError("down")):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists", json={"name": "x", "track_paths": ["/music/a.mp3"]})
    assert response.status_code == 502


def test_create_playlist_success():
    with patch.object(vuio_client, "create_playlist", return_value=7):
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists", json={"name": "x", "track_paths": ["/music/a.mp3"]})
    assert response.status_code == 200
    assert response.json()["playlist_id"] == 7


def test_renderers_endpoint():
    with patch.object(vuio_client, "list_renderers", return_value=[{"id": "r1", "friendly_name": "TV"}]):
        with TestClient(app_module.app) as client:
            response = client.get("/api/renderers")
    assert response.json()["renderers"][0]["id"] == "r1"


def test_cast_endpoint():
    with patch.object(vuio_client, "cast_playlist", return_value={"status": "ok"}) as mock_cast:
        with TestClient(app_module.app) as client:
            response = client.post("/api/playlists/7/cast", json={"renderer_id": "r1"})
    assert response.status_code == 200
    mock_cast.assert_called_once_with(7, "r1")


if __name__ == "__main__":
    test_stats_endpoint_returns_counts()
    test_presets_endpoint_lists_presets()
    test_tracks_search_endpoint()
    test_preview_preset_mode()
    test_preview_unknown_seed_returns_404()
    test_create_playlist_maps_vuio_error_to_502()
    test_create_playlist_success()
    test_renderers_endpoint()
    test_cast_endpoint()
    print("All app tests passed.")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python webapp/backend/test_app.py`
Expected: `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: `app.py` implementieren**

`webapp/backend/app.py`:
```python
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import presets
import similarity
import vuio_client

DB_PATH = os.environ.get("DB_PATH", "/data/library.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.get_connection(DB_PATH)
    app.state.conn = conn
    app.state.tracks = db.load_ok_tracks(conn)
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PreviewRequest(BaseModel):
    mode: str
    preset_name: Optional[str] = None
    seed_path: Optional[str] = None
    limit: int = 30


class CreatePlaylistRequest(BaseModel):
    name: str
    track_paths: list


class CastRequest(BaseModel):
    renderer_id: str


@app.get("/api/stats")
def get_stats():
    return db.fetch_stats(app.state.conn)


@app.get("/api/presets")
def get_presets():
    return presets.PRESETS


@app.get("/api/tracks")
def search_tracks(q: str = "", limit: int = 20):
    return {"tracks": db.search_ok_tracks(app.state.conn, q, limit)}


@app.post("/api/playlists/preview")
def preview_playlist(req: PreviewRequest):
    tracks = app.state.tracks
    if not tracks:
        raise HTTPException(status_code=404, detail="Keine analysierten Tracks vorhanden")

    if req.mode == "preset":
        if req.preset_name not in presets.PRESETS:
            raise HTTPException(status_code=400, detail=f"Unbekanntes Preset: {req.preset_name}")
        matches = presets.filter_tracks(tracks, req.preset_name, limit=req.limit)
    elif req.mode == "seed":
        seed = next((t for t in tracks if t["path"] == req.seed_path), None)
        if seed is None:
            raise HTTPException(status_code=404, detail=f"Seed-Track nicht gefunden: {req.seed_path}")
        matches = similarity.top_similar(seed, tracks, limit=req.limit)
    else:
        raise HTTPException(status_code=400, detail=f"Unbekannter Modus: {req.mode}")

    return {"tracks": [{"path": t["path"], "bpm": t["bpm"], "key": t["key"]} for t in matches]}


@app.post("/api/playlists")
def add_playlist(req: CreatePlaylistRequest):
    try:
        playlist_id = vuio_client.create_playlist(req.name, req.track_paths)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"playlist_id": playlist_id}


@app.get("/api/renderers")
def list_renderers():
    try:
        return {"renderers": vuio_client.list_renderers()}
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/playlists/{playlist_id}/cast")
def cast_playlist(playlist_id: int, req: CastRequest):
    try:
        return vuio_client.cast_playlist(playlist_id, req.renderer_id)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/playback-status")
def playback_status(renderer_id: Optional[str] = None):
    try:
        return vuio_client.get_playback_status(renderer_id)
    except vuio_client.VuioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `python webapp/backend/test_app.py`
Expected: `All app tests passed.`

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/app.py webapp/backend/test_app.py
git commit -m "feat(webapp): wire FastAPI endpoints for stats, presets, tracks and playlists"
```

---

### Task 6: Frontend-Grundgerüst + Dashboard-Seite

**Kontext für den Implementierer:** Ab hier gibt es laut Design-Spec
bewusst keine automatisierten Frontend-Tests - Verifikation erfolgt
manuell über `npm run dev` und Durchklicken im Browser, mit dem Backend
aus Task 5 parallel laufend (`uvicorn app:app --reload` in
`webapp/backend`, Port 8000; Vite-Dev-Server proxied `/api` dorthin,
siehe `vite.config.js`).

**Files:**
- Create: `webapp/frontend/package.json`
- Create: `webapp/frontend/vite.config.js`
- Create: `webapp/frontend/index.html`
- Create: `webapp/frontend/src/main.jsx`
- Create: `webapp/frontend/src/App.jsx`
- Create: `webapp/frontend/src/api.js`
- Create: `webapp/frontend/src/index.css`
- Create: `webapp/frontend/src/pages/Dashboard.jsx`

- [ ] **Step 1: `package.json` anlegen**

```json
{
  "name": "cratemind-webapp-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "recharts": "^2.12.7"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 2: `vite.config.js` anlegen**

```js
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
```

- [ ] **Step 3: `index.html` anlegen**

```html
<!doctype html>
<html lang="de">
  <head>
    <meta charset="UTF-8" />
    <title>CrateMind</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

- [ ] **Step 4: `src/api.js` anlegen**

```js
const BASE = "/api";

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const getStats = () => request("/stats");
export const getPresets = () => request("/presets");
export const searchTracks = (q) => request(`/tracks?q=${encodeURIComponent(q)}&limit=10`);
export const previewPlaylist = (body) =>
  request("/playlists/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const createPlaylist = (body) =>
  request("/playlists", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const getRenderers = () => request("/renderers");
export const castPlaylist = (playlistId, rendererId) =>
  request(`/playlists/${playlistId}/cast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ renderer_id: rendererId }),
  });
export const getPlaybackStatus = (rendererId) =>
  request(`/playback-status${rendererId ? `?renderer_id=${encodeURIComponent(rendererId)}` : ""}`);
```

- [ ] **Step 5: `src/index.css` anlegen**

```css
body {
  margin: 0;
  font-family: system-ui, sans-serif;
  background: #111;
  color: #eee;
}

.top-nav {
  display: flex;
  gap: 1.5rem;
  align-items: center;
  padding: 1rem 1.5rem;
  background: #1a1a1a;
  border-bottom: 1px solid #333;
}

.top-nav .brand {
  font-weight: 700;
  margin-right: 1rem;
}

.top-nav a {
  color: #ccc;
  text-decoration: none;
}

.top-nav a.active {
  color: #fff;
  font-weight: 600;
}

main {
  padding: 1.5rem;
}

.tile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1rem;
}

.tile {
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
}

.error {
  color: #f66;
}
```

- [ ] **Step 6: `src/pages/Dashboard.jsx` anlegen**

```jsx
import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { getStats } from "../api.js";

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getStats().then(setStats).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="error">Fehler: {error}</p>;
  if (!stats) return <p>Lade...</p>;

  const analyzed = stats.status_counts.ok || 0;
  if (analyzed === 0) {
    return <p>Noch keine Analyse-Daten vorhanden.</p>;
  }

  const keyData = Object.entries(stats.key_counts).map(([key, count]) => ({ key, count }));

  return (
    <div className="tile-grid">
      <div className="tile">
        <h3>Analyse-Fortschritt</h3>
        <ul>
          {Object.entries(stats.status_counts).map(([status, count]) => (
            <li key={status}>{status}: {count}</li>
          ))}
        </ul>
      </div>
      <div className="tile">
        <h3>BPM-Verteilung</h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={stats.bpm_histogram}>
            <XAxis dataKey="bucket" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="count" fill="#8884d8" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="tile">
        <h3>Key-Verteilung</h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={keyData}>
            <XAxis dataKey="key" hide />
            <YAxis />
            <Tooltip />
            <Bar dataKey="count" fill="#82ca9d" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="tile">
        <h3>Mood-Durchschnitte</h3>
        <ul>
          {Object.entries(stats.mood_averages).map(([mood, value]) => (
            <li key={mood}>{mood}: {value.toFixed(2)}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: `src/App.jsx` und `src/main.jsx` anlegen (Renderers/Playlists-Seiten sind Platzhalter bis Task 7/8)**

`webapp/frontend/src/pages/Playlists.jsx` (Platzhalter, wird in Task 7 ersetzt):
```jsx
export default function Playlists() {
  return <p>Kommt in Task 7.</p>;
}
```

`webapp/frontend/src/pages/Renderers.jsx` (Platzhalter, wird in Task 8 ersetzt):
```jsx
export default function Renderers() {
  return <p>Kommt in Task 8.</p>;
}
```

`webapp/frontend/src/App.jsx`:
```jsx
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Playlists from "./pages/Playlists.jsx";
import Renderers from "./pages/Renderers.jsx";

export default function App() {
  return (
    <BrowserRouter>
      <nav className="top-nav">
        <span className="brand">CrateMind</span>
        <NavLink to="/">Dashboard</NavLink>
        <NavLink to="/playlists">Playlists</NavLink>
        <NavLink to="/renderers">Renderer</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/playlists" element={<Playlists />} />
          <Route path="/renderers" element={<Renderers />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
```

`webapp/frontend/src/main.jsx`:
```jsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 8: Manuell verifizieren**

Backend starten: `cd webapp/backend && DB_PATH=/tmp/test-library.db uvicorn app:app --reload`
(vorher einmal eine Test-DB mit Daten anlegen, z.B. via `python -c` wie in
`test_app.py` gezeigt, damit das Dashboard etwas anzeigt.)

Frontend starten: `cd webapp/frontend && npm install && npm run dev`

Im Browser öffnen (URL, die Vite ausgibt): Dashboard mit den vier Kacheln
(Analyse-Fortschritt, BPM, Key, Mood) sollte Daten aus dem Backend zeigen.
Top-Nav mit Dashboard/Playlists/Renderer sollte sichtbar sein und
zwischen den (noch leeren) Seiten navigieren.

- [ ] **Step 9: Commit**

```bash
git add webapp/frontend/
git commit -m "feat(webapp): scaffold React frontend with top-nav and dashboard page"
```

---

### Task 7: Frontend Playlists-Seite

**Files:**
- Modify: `webapp/frontend/src/pages/Playlists.jsx`

- [ ] **Step 1: `Playlists.jsx` implementieren**

```jsx
import { useEffect, useState } from "react";
import {
  getStats,
  getPresets,
  previewPlaylist,
  createPlaylist,
  getRenderers,
  castPlaylist,
  searchTracks,
} from "../api.js";

export default function Playlists() {
  const [hasTracks, setHasTracks] = useState(null);
  const [presets, setPresets] = useState({});
  const [mode, setMode] = useState("preset");
  const [presetName, setPresetName] = useState("");
  const [seedQuery, setSeedQuery] = useState("");
  const [seedResults, setSeedResults] = useState([]);
  const [seedPath, setSeedPath] = useState("");
  const [preview, setPreview] = useState([]);
  const [playlistName, setPlaylistName] = useState("");
  const [playlistId, setPlaylistId] = useState(null);
  const [renderers, setRenderers] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    getStats().then((s) => setHasTracks((s.status_counts.ok || 0) > 0));
    getPresets().then((p) => {
      setPresets(p);
      setPresetName(Object.keys(p)[0] || "");
    });
  }, []);

  const moveTrack = (index, direction) => {
    const target = index + direction;
    if (target < 0 || target >= preview.length) return;
    const next = [...preview];
    [next[index], next[target]] = [next[target], next[index]];
    setPreview(next);
  };

  if (hasTracks === false) {
    return <p>Noch keine analysierten Tracks vorhanden - Playlist-Generierung ist noch nicht möglich.</p>;
  }

  const searchSeed = async (q) => {
    setSeedQuery(q);
    if (q.length < 2) {
      setSeedResults([]);
      return;
    }
    const result = await searchTracks(q);
    setSeedResults(result.tracks);
  };

  const runPreview = async () => {
    setError(null);
    try {
      const body = mode === "preset" ? { mode, preset_name: presetName } : { mode, seed_path: seedPath };
      const result = await previewPlaylist(body);
      setPreview(result.tracks);
    } catch (e) {
      setError(e.message);
    }
  };

  const removeTrack = (path) => setPreview(preview.filter((t) => t.path !== path));

  const handleCreate = async () => {
    setError(null);
    try {
      const result = await createPlaylist({ name: playlistName, track_paths: preview.map((t) => t.path) });
      setPlaylistId(result.playlist_id);
      setRenderers((await getRenderers()).renderers);
    } catch (e) {
      setError(e.message);
    }
  };

  const handleCast = async (rendererId) => {
    setError(null);
    try {
      await castPlaylist(playlistId, rendererId);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div>
      {error && <p className="error">Fehler: {error}</p>}

      <div className="tile">
        <h3>Playlist generieren</h3>
        <label>
          <input type="radio" checked={mode === "preset"} onChange={() => setMode("preset")} /> Preset
        </label>
        <label>
          <input type="radio" checked={mode === "seed"} onChange={() => setMode("seed")} /> Seed-Track
        </label>

        {mode === "preset" ? (
          <select value={presetName} onChange={(e) => setPresetName(e.target.value)}>
            {Object.keys(presets).map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        ) : (
          <div>
            <input
              type="text"
              placeholder="Track suchen..."
              value={seedQuery}
              onChange={(e) => searchSeed(e.target.value)}
            />
            <ul>
              {seedResults.map((t) => (
                <li key={t.path}>
                  <button
                    onClick={() => {
                      setSeedPath(t.path);
                      setSeedQuery(t.path);
                      setSeedResults([]);
                    }}
                  >
                    {t.path}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <button onClick={runPreview}>Vorschau erzeugen</button>
      </div>

      {preview.length > 0 && (
        <div className="tile">
          <h3>Vorschau ({preview.length} Tracks)</h3>
          <ul>
            {preview.map((t, i) => (
              <li key={t.path}>
                {t.path} ({t.bpm ? t.bpm.toFixed(0) : "?"} BPM, {t.key})
                <button onClick={() => moveTrack(i, -1)} disabled={i === 0}>↑</button>
                <button onClick={() => moveTrack(i, 1)} disabled={i === preview.length - 1}>↓</button>
                <button onClick={() => removeTrack(t.path)}>Entfernen</button>
              </li>
            ))}
          </ul>
          <input
            type="text"
            placeholder="Playlist-Name"
            value={playlistName}
            onChange={(e) => setPlaylistName(e.target.value)}
          />
          <button onClick={handleCreate}>In VuIO anlegen</button>
        </div>
      )}

      {playlistId && (
        <div className="tile">
          <h3>Auf Renderer abspielen</h3>
          {renderers.map((r) => (
            <button key={r.id} onClick={() => handleCast(r.id)}>{r.friendly_name}</button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Manuell verifizieren**

Mit laufendem Backend + Frontend (siehe Task 6, Step 8): Preset wählen →
"Vorschau erzeugen" → Liste erscheint → Tracks mit ↑/↓ umsortieren, einen
entfernen → Namen eingeben → "In VuIO anlegen" (nur mit erreichbarem VuIO
auf `minime-3.local` sinnvoll testbar; ohne echtes VuIO sollte ein 502 mit
Fehlermeldung im Frontend erscheinen, kein Absturz). Seed-Modus: Track
suchen, aus Trefferliste wählen, Vorschau erzeugen. Mit einer leeren
Test-DB (keine `status='ok'`-Tracks) sollte statt der Generierungs-Kachel
der Hinweistext erscheinen.

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/pages/Playlists.jsx
git commit -m "feat(webapp): implement playlist generation, preview, editing and creation UI"
```

---

### Task 8: Frontend Renderer-Seite

**Files:**
- Modify: `webapp/frontend/src/pages/Renderers.jsx`

- [ ] **Step 1: `Renderers.jsx` implementieren**

```jsx
import { useEffect, useState } from "react";
import { getRenderers, getPlaybackStatus } from "../api.js";

export default function Renderers() {
  const [renderers, setRenderers] = useState([]);
  const [status, setStatus] = useState({});
  const [error, setError] = useState(null);

  useEffect(() => {
    getRenderers()
      .then((r) => setRenderers(r.renderers))
      .catch((e) => setError(e.message));
  }, []);

  const checkStatus = async (rendererId) => {
    try {
      const result = await getPlaybackStatus(rendererId);
      setStatus((prev) => ({ ...prev, [rendererId]: result }));
    } catch (e) {
      setError(e.message);
    }
  };

  if (error) return <p className="error">Fehler: {error}</p>;

  return (
    <div className="tile-grid">
      {renderers.map((r) => (
        <div className="tile" key={r.id}>
          <h3>{r.friendly_name}</h3>
          <p>{r.protocol}</p>
          <button onClick={() => checkStatus(r.id)}>Status abfragen</button>
          {status[r.id] && <pre>{JSON.stringify(status[r.id], null, 2)}</pre>}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Manuell verifizieren**

Mit laufendem Backend + Frontend: Renderer-Seite öffnen, Liste der
VuIO-Renderer sollte erscheinen (nur mit erreichbarem VuIO sinnvoll
testbar), "Status abfragen" zeigt rohes JSON an.

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/pages/Renderers.jsx
git commit -m "feat(webapp): implement renderer list and playback status page"
```

---

### Task 9: Docker-Image + docker-compose-Service + CI

**Files:**
- Create: `webapp/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.github/workflows/docker-build.yml`

- [ ] **Step 1: `webapp/Dockerfile` anlegen**

```dockerfile
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY webapp/frontend/package.json webapp/frontend/package-lock.json* ./
RUN npm install
COPY webapp/frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY webapp/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY webapp/backend/ .
COPY --from=frontend-build /app/frontend/dist ./static

ENV DB_PATH=/data/library.db
ENV VUIO_BASE_URL=http://192.168.0.54:8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: `docker-compose.yml` um `webapp`-Service erweitern**

```yaml
services:
  analysis:
    build: .
    volumes:
      - /Volumes/Platte/Musik:/music:ro
      - ./data:/data
    environment:
      - MUSIC_DIR=/music
      - DB_PATH=/data/library.db
      - SCAN_INTERVAL_SECONDS=1800
    restart: unless-stopped

  webapp:
    build:
      context: .
      dockerfile: webapp/Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data:ro
    environment:
      - DB_PATH=/data/library.db
      - VUIO_BASE_URL=http://192.168.0.54:8080
    restart: unless-stopped
```

- [ ] **Step 3: CI-Job für die Webapp hinzufügen**

In `.github/workflows/docker-build.yml`, nach dem bestehenden Job
`build-and-smoke-test` einen zweiten Job ergänzen (Datei beginnt weiter
oben unverändert mit `name: Docker Build` / `on:` / `jobs:`):

```yaml
  webapp-build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install backend dependencies
        run: pip install -r webapp/backend/requirements.txt

      - name: Run backend tests
        run: |
          python webapp/backend/test_db.py
          python webapp/backend/test_presets.py
          python webapp/backend/test_similarity.py
          python webapp/backend/test_vuio_client.py
          python webapp/backend/test_app.py

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install frontend dependencies
        working-directory: webapp/frontend
        run: npm install

      - name: Build frontend
        working-directory: webapp/frontend
        run: npm run build

      - name: Build webapp Docker image
        run: docker build -t crate-mind-webapp -f webapp/Dockerfile .
```

- [ ] **Step 4: Lokal/per CI verifizieren**

Push auf einen Branch, dann:
```bash
gh run list --limit 1
gh run watch <run-id> --exit-status
```
Erwartet: beide Jobs (`build-and-smoke-test`, `webapp-build-and-test`)
grün. Bei Fehlschlag: `gh run view <run-id> --log-failed`.

- [ ] **Step 5: Commit**

```bash
git add webapp/Dockerfile docker-compose.yml .github/workflows/docker-build.yml
git commit -m "feat(webapp): add Docker image, compose service and CI build/test job"
```

---

## Nach Abschluss aller Tasks

Finaler Review der gesamten Branch-Diff gegen das Design-Spec (wie schon
für die Essentia-Pipeline: ein gründlicher `superpowers:code-reviewer`-Lauf
über den ganzen Branch), dann PR öffnen und laut Nutzerpräferenz per
GitHub Actions CI absichern, bevor gemergt wird.

Deployment auf `minime-3.local` (Docker-Compose-Rebuild inkl. neuem
`webapp`-Service) macht der Nutzer selbst, wie schon bei der
Essentia-Pipeline vereinbart - nur auf Nachfrage unterstützen.
