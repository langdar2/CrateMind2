# Essentia Audio-Analyse-Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Docker-Container, der auf `minime-3.local` alle 30 Minuten den
Musik-Ordner scannt, neue/geänderte Tracks mit Essentia analysiert (Tempo,
Key, Mood-Tags, Danceability, Embedding) und die Ergebnisse in SQLite
speichert.

**Architecture:** Scan → Diff gegen SQLite → sequentielle Essentia-Analyse
der Differenzmenge → SQLite schreiben, in einer Endlosschleife mit Sleep
(kein Cron-Daemon). Siehe
[Design-Spec](../specs/2026-09-24-essentia-audio-analysis-design.md).

**Tech Stack:** Python 3.11, `essentia-tensorflow`, SQLite (`sqlite3`
stdlib), Docker, Docker Compose.

---

## File Structure

```
crate_mind/
  __init__.py
  analysis/
    __init__.py
    db.py          # SQLite schema + CRUD
    diff.py        # reine Diff-Entscheidungslogik
    scan.py        # Filesystem-Traversierung
    features.py    # Essentia-Feature-Extraktion + Self-Test
    main.py         # Scan-Loop, verdrahtet alles
tests/
  test_diff.py
Dockerfile
docker-compose.yml
requirements.txt
```

---

### Task 1: Projekt-Grundgerüst

**Files:**
- Create: `requirements.txt`
- Create: `crate_mind/__init__.py`
- Create: `crate_mind/analysis/__init__.py`
- Create: `.gitignore`

- [ ] **Step 1: `requirements.txt` anlegen**

```
essentia-tensorflow
numpy
```

- [ ] **Step 2: Package-Init-Dateien anlegen**

`crate_mind/__init__.py`:
```python
```

`crate_mind/analysis/__init__.py`:
```python
```

- [ ] **Step 3: `.gitignore` anlegen**

```
__pycache__/
*.pyc
data/
*.db
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt crate_mind/ .gitignore
git commit -m "chore: scaffold crate_mind analysis package"
```

---

### Task 2: Docker-Image mit Essentia + Modellen

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Dockerfile schreiben**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /models && \
    curl -sSL -o /models/msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/feature-extractors/musicnn/msd-musicnn-1.pb" && \
    curl -sSL -o /models/mood_happy-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/mood_happy/mood_happy-msd-musicnn-1.pb" && \
    curl -sSL -o /models/mood_aggressive-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/mood_aggressive/mood_aggressive-msd-musicnn-1.pb" && \
    curl -sSL -o /models/mood_relaxed-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/mood_relaxed/mood_relaxed-msd-musicnn-1.pb" && \
    curl -sSL -o /models/mood_party-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/mood_party/mood_party-msd-musicnn-1.pb" && \
    curl -sSL -o /models/danceability-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/danceability/danceability-msd-musicnn-1.pb"

ENV MODELS_DIR=/models
ENV MUSIC_DIR=/music
ENV DB_PATH=/data/library.db
ENV SCAN_INTERVAL_SECONDS=1800

COPY crate_mind/ ./crate_mind/

CMD ["python", "-m", "crate_mind.analysis.main"]
```

- [ ] **Step 2: Image bauen**

```bash
docker build -t crate-mind-analysis .
```

Erwartet: Build läuft durch, alle sechs `.pb`-Dateien werden erfolgreich
heruntergeladen (kein `curl: (22)`-Fehler in der Build-Ausgabe).

- [ ] **Step 3: Essentia-Import im Image smoke-testen**

```bash
docker run --rm crate-mind-analysis python -c "import essentia.standard; print('essentia ok')"
```

Erwartet: Ausgabe `essentia ok`, kein Import-Fehler.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat: add Dockerfile with essentia-tensorflow and musicnn models"
```

---

### Task 3: SQLite-Persistenz

**Files:**
- Create: `crate_mind/analysis/db.py`

- [ ] **Step 1: `db.py` schreiben**

```python
import sqlite3
import time
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tracks (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_scanned REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS features (
    path TEXT PRIMARY KEY REFERENCES tracks(path),
    bpm REAL,
    key TEXT,
    mood_happy REAL,
    mood_aggressive REAL,
    mood_relaxed REAL,
    mood_party REAL,
    danceability REAL,
    embedding BLOB
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def get_track_row(conn: sqlite3.Connection, path: str):
    row = conn.execute(
        "SELECT mtime, size, status FROM tracks WHERE path = ?", (path,)
    ).fetchone()
    if row is None:
        return None
    return {"mtime": row[0], "size": row[1], "status": row[2]}


def all_track_paths(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT path FROM tracks").fetchall()
    return {r[0] for r in rows}


def upsert_track(conn: sqlite3.Connection, path: str, mtime: float, size: int, status: str) -> None:
    conn.execute(
        """
        INSERT INTO tracks (path, mtime, size, status, last_scanned)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            mtime = excluded.mtime,
            size = excluded.size,
            status = excluded.status,
            last_scanned = excluded.last_scanned
        """,
        (path, mtime, size, status, time.time()),
    )
    conn.commit()


def upsert_features(conn: sqlite3.Connection, path: str, features: dict) -> None:
    conn.execute(
        """
        INSERT INTO features
            (path, bpm, key, mood_happy, mood_aggressive, mood_relaxed, mood_party, danceability, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            bpm = excluded.bpm,
            key = excluded.key,
            mood_happy = excluded.mood_happy,
            mood_aggressive = excluded.mood_aggressive,
            mood_relaxed = excluded.mood_relaxed,
            mood_party = excluded.mood_party,
            danceability = excluded.danceability,
            embedding = excluded.embedding
        """,
        (
            path,
            features["bpm"],
            features["key"],
            features["mood_happy"],
            features["mood_aggressive"],
            features["mood_relaxed"],
            features["mood_party"],
            features["danceability"],
            features["embedding"].tobytes(),
        ),
    )
    conn.commit()


def delete_track(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM features WHERE path = ?", (path,))
    conn.execute("DELETE FROM tracks WHERE path = ?", (path,))
    conn.commit()
```

Kein dedizierter Test hier (laut Spec-Testing-Abschnitt bewusst nur Diff-
Logik und die Essentia-Pipeline getestet — CRUD-Funktionen sind trivial und
werden in Task 7 end-to-end mitgeprüft).

- [ ] **Step 2: Commit**

```bash
git add crate_mind/analysis/db.py
git commit -m "feat: add sqlite persistence for tracks and features"
```

---

### Task 4: Diff-Logik (TDD)

**Files:**
- Create: `crate_mind/analysis/diff.py`
- Create: `tests/test_diff.py`

- [ ] **Step 1: Failing Test schreiben**

`tests/test_diff.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crate_mind.analysis.diff import classify_file, find_deleted, DiffResult


def test_new_file_has_no_existing_row():
    result = classify_file(mtime=100.0, size=2048, existing_row=None)
    assert result == DiffResult.NEW


def test_changed_file_has_different_mtime():
    existing = {"mtime": 100.0, "size": 2048, "status": "ok"}
    result = classify_file(mtime=200.0, size=2048, existing_row=existing)
    assert result == DiffResult.CHANGED


def test_changed_file_has_different_size():
    existing = {"mtime": 100.0, "size": 2048, "status": "ok"}
    result = classify_file(mtime=100.0, size=4096, existing_row=existing)
    assert result == DiffResult.CHANGED


def test_unchanged_file_matches_existing_row():
    existing = {"mtime": 100.0, "size": 2048, "status": "ok"}
    result = classify_file(mtime=100.0, size=2048, existing_row=existing)
    assert result == DiffResult.UNCHANGED


def test_previously_failed_file_is_unchanged_if_still_same():
    existing = {"mtime": 100.0, "size": 2048, "status": "failed"}
    result = classify_file(mtime=100.0, size=2048, existing_row=existing)
    assert result == DiffResult.UNCHANGED


def test_find_deleted_returns_paths_missing_from_filesystem():
    db_paths = {"/music/a.mp3", "/music/b.mp3", "/music/c.mp3"}
    fs_paths = {"/music/a.mp3", "/music/c.mp3"}
    assert find_deleted(db_paths, fs_paths) == {"/music/b.mp3"}


def test_find_deleted_returns_empty_set_when_nothing_removed():
    db_paths = {"/music/a.mp3"}
    fs_paths = {"/music/a.mp3"}
    assert find_deleted(db_paths, fs_paths) == set()


if __name__ == "__main__":
    test_new_file_has_no_existing_row()
    test_changed_file_has_different_mtime()
    test_changed_file_has_different_size()
    test_unchanged_file_matches_existing_row()
    test_previously_failed_file_is_unchanged_if_still_same()
    test_find_deleted_returns_paths_missing_from_filesystem()
    test_find_deleted_returns_empty_set_when_nothing_removed()
    print("All diff tests passed.")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `python tests/test_diff.py`
Expected: `ModuleNotFoundError: No module named 'crate_mind.analysis.diff'`

- [ ] **Step 3: `diff.py` implementieren**

```python
from enum import Enum


class DiffResult(str, Enum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


def classify_file(mtime: float, size: int, existing_row: dict | None) -> DiffResult:
    if existing_row is None:
        return DiffResult.NEW
    if existing_row["mtime"] != mtime or existing_row["size"] != size:
        return DiffResult.CHANGED
    return DiffResult.UNCHANGED


def find_deleted(db_paths: set, fs_paths: set) -> set:
    return db_paths - fs_paths
```

- [ ] **Step 4: Test laufen lassen, Erfolg verifizieren**

Run: `python tests/test_diff.py`
Expected: `All diff tests passed.`

- [ ] **Step 5: Commit**

```bash
git add crate_mind/analysis/diff.py tests/test_diff.py
git commit -m "feat: add diff logic for detecting new/changed/deleted tracks"
```

---

### Task 5: Filesystem-Scanner

**Files:**
- Create: `crate_mind/analysis/scan.py`

- [ ] **Step 1: `scan.py` schreiben**

```python
import os
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav", ".aiff", ".alac"}


def scan_music_dir(root: str) -> dict:
    """Returns {absolute_path: (mtime, size)} for every audio file under root."""
    found = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            full_path = os.path.join(dirpath, name)
            stat = os.stat(full_path)
            found[full_path] = (stat.st_mtime, stat.st_size)
    return found
```

Kein dedizierter Test (reiner `os.walk`-Wrapper, laut Spec-Testing-Abschnitt
nicht in Scope — wird in Task 7 end-to-end mitgeprüft).

- [ ] **Step 2: Commit**

```bash
git add crate_mind/analysis/scan.py
git commit -m "feat: add filesystem scanner for audio files"
```

---

### Task 6: Essentia-Feature-Extraktion + Self-Test

**Files:**
- Create: `crate_mind/analysis/features.py`

Klassen-Reihenfolge der Mood/Danceability-Modelle wurde gegen die
offiziellen Metadaten-JSONs von essentia.upf.edu geprüft (nicht einheitlich
— pro Modell verschieden):

| Modell | classes (Essentia-Reihenfolge) | Ziel-Index |
|---|---|---|
| mood_happy | `["happy", "non_happy"]` | 0 |
| mood_aggressive | `["aggressive", "not_aggressive"]` | 0 |
| mood_relaxed | `["non_relaxed", "relaxed"]` | 1 |
| mood_party | `["non_party", "party"]` | 1 |
| danceability | `["danceable", "not_danceable"]` | 0 |

- [ ] **Step 1: `features.py` schreiben**

```python
import argparse
import os

import numpy as np
from essentia.standard import (
    KeyExtractor,
    MonoLoader,
    Resample,
    RhythmExtractor2013,
    TensorflowPredict2D,
    TensorflowPredictMusiCNN,
)

MODELS_DIR = os.environ.get("MODELS_DIR", "/models")
EMBEDDING_MODEL_PATH = os.path.join(MODELS_DIR, "msd-musicnn-1.pb")

# (model filename, index of the positive/target class in the model's softmax output)
MOOD_MODELS = {
    "mood_happy": ("mood_happy-msd-musicnn-1.pb", 0),
    "mood_aggressive": ("mood_aggressive-msd-musicnn-1.pb", 0),
    "mood_relaxed": ("mood_relaxed-msd-musicnn-1.pb", 1),
    "mood_party": ("mood_party-msd-musicnn-1.pb", 1),
    "danceability": ("danceability-msd-musicnn-1.pb", 0),
}

_embedding_model = None
_mood_models = None  # name -> (TensorflowPredict2D instance, positive_index)


def _load_models():
    global _embedding_model, _mood_models
    if _embedding_model is None:
        _embedding_model = TensorflowPredictMusiCNN(
            graphFilename=EMBEDDING_MODEL_PATH, output="model/dense/BiasAdd"
        )
        _mood_models = {
            name: (
                TensorflowPredict2D(
                    graphFilename=os.path.join(MODELS_DIR, filename), output="model/Softmax"
                ),
                positive_index,
            )
            for name, (filename, positive_index) in MOOD_MODELS.items()
        }
    return _embedding_model, _mood_models


def extract_features(audio_16k: np.ndarray, audio_44k: np.ndarray) -> dict:
    """audio_16k: mono float32 samples at 16000 Hz (MusiCNN input).
    audio_44k: mono float32 samples at 44100 Hz (tempo/key input)."""
    embedding_model, mood_models = _load_models()

    embeddings = embedding_model(audio_16k)
    embedding_vector = np.mean(embeddings, axis=0).astype(np.float32)

    moods = {}
    for name, (model, positive_index) in mood_models.items():
        predictions = model(embeddings)
        moods[name] = float(np.mean(predictions, axis=0)[positive_index])

    rhythm_extractor = RhythmExtractor2013(method="multifeature")
    bpm, _, _, _, _ = rhythm_extractor(audio_44k)

    key_extractor = KeyExtractor()
    key, scale, _ = key_extractor(audio_44k)

    return {
        "bpm": float(bpm),
        "key": f"{key} {scale}",
        "mood_happy": moods["mood_happy"],
        "mood_aggressive": moods["mood_aggressive"],
        "mood_relaxed": moods["mood_relaxed"],
        "mood_party": moods["mood_party"],
        "danceability": moods["danceability"],
        "embedding": embedding_vector,
    }


def load_audio_for_analysis(path: str):
    """Returns (audio_16k, audio_44k) as mono float32 numpy arrays."""
    audio_44k = MonoLoader(filename=path, sampleRate=44100)()
    audio_16k = MonoLoader(filename=path, sampleRate=16000)()
    return audio_16k, audio_44k


def _make_click_track(duration_seconds: float = 15.0, bpm: float = 120.0, sample_rate: int = 44100) -> np.ndarray:
    samples = np.zeros(int(duration_seconds * sample_rate), dtype=np.float32)
    interval = 60.0 / bpm
    click_length = int(0.01 * sample_rate)
    t = 0.0
    while t < duration_seconds:
        start = int(t * sample_rate)
        end = min(start + click_length, len(samples))
        samples[start:end] = 0.8
        t += interval
    return samples


def self_test() -> None:
    audio_44k = _make_click_track(duration_seconds=15.0, bpm=120.0, sample_rate=44100)
    audio_16k = Resample(inputSampleRate=44100, outputSampleRate=16000)(audio_44k)

    result = extract_features(audio_16k, audio_44k)

    assert 20 <= result["bpm"] <= 300, f"BPM out of range: {result['bpm']}"
    assert result["embedding"].shape == (200,), f"Unexpected embedding shape: {result['embedding'].shape}"
    for mood_key in ("mood_happy", "mood_aggressive", "mood_relaxed", "mood_party", "danceability"):
        value = result[mood_key]
        assert 0.0 <= value <= 1.0, f"{mood_key} out of range: {value}"

    printable = {k: v for k, v in result.items() if k != "embedding"}
    print("Self-test passed:", printable)
    print("Embedding shape:", result["embedding"].shape)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        parser.print_help()
```

- [ ] **Step 2: Image neu bauen (neue Datei muss ins Image)**

```bash
docker build -t crate-mind-analysis .
```

- [ ] **Step 3: Self-Test im Container laufen lassen**

```bash
docker run --rm crate-mind-analysis python -m crate_mind.analysis.features --self-test
```

Erwartet: `Self-test passed: {...}` mit BPM nahe 120 (Click-Track), Mood-
Werten zwischen 0 und 1, gefolgt von `Embedding shape: (200,)`.

Falls die Embedding-Shape abweicht: die 200 kommt aus der `msd-musicnn-1`-
Modell-Dokumentation (Eingabe-Shape `[200]` der Klassifikator-Köpfe) — bei
Abweichung den Assert in `self_test()` an die tatsächlich beobachtete Shape
anpassen und kurz dokumentieren, woher die andere Zahl kommt.

- [ ] **Step 4: Commit**

```bash
git add crate_mind/analysis/features.py
git commit -m "feat: add essentia feature extraction with mood/tempo/key/embedding"
```

---

### Task 7: Scan-Loop verdrahten

**Files:**
- Create: `crate_mind/analysis/main.py`

- [ ] **Step 1: `main.py` schreiben**

```python
import os
import time
import traceback

from crate_mind.analysis import db, diff, features, scan


def run_cycle(conn, music_dir: str) -> None:
    fs_entries = scan.scan_music_dir(music_dir)
    fs_paths = set(fs_entries.keys())
    db_paths = db.all_track_paths(conn)

    for deleted_path in diff.find_deleted(db_paths, fs_paths):
        db.delete_track(conn, deleted_path)
        print(f"Removed (deleted from disk): {deleted_path}")

    for path, (mtime, size) in fs_entries.items():
        existing_row = db.get_track_row(conn, path)
        result = diff.classify_file(mtime, size, existing_row)
        if result == diff.DiffResult.UNCHANGED:
            continue

        try:
            audio_16k, audio_44k = features.load_audio_for_analysis(path)
            extracted = features.extract_features(audio_16k, audio_44k)
            db.upsert_features(conn, path, extracted)
            db.upsert_track(conn, path, mtime, size, status="ok")
            print(f"Analyzed: {path}")
        except Exception:
            db.upsert_track(conn, path, mtime, size, status="failed")
            print(f"Failed to analyze: {path}")
            traceback.print_exc()


def main() -> None:
    music_dir = os.environ.get("MUSIC_DIR", "/music")
    db_path = os.environ.get("DB_PATH", "/data/library.db")
    interval = int(os.environ.get("SCAN_INTERVAL_SECONDS", "1800"))

    conn = db.get_connection(db_path)

    while True:
        print("Starting scan cycle...")
        run_cycle(conn, music_dir)
        print(f"Cycle complete. Sleeping {interval}s.")
        time.sleep(interval)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Image neu bauen**

```bash
docker build -t crate-mind-analysis .
```

- [ ] **Step 3: End-to-End gegen ein paar echte Test-Dateien prüfen**

Lege lokal 2-3 kurze Audiodateien in einen Test-Ordner, z.B. `./test-music/`,
und starte einen einmaligen Container-Lauf dagegen:

```bash
mkdir -p ./test-music ./test-data
cp ~/Music/irgendein_kurzer_track.mp3 ./test-music/
docker run --rm \
  -v "$(pwd)/test-music:/music:ro" \
  -v "$(pwd)/test-data:/data" \
  -e SCAN_INTERVAL_SECONDS=99999 \
  crate-mind-analysis \
  python -c "
from crate_mind.analysis import db, main as m
conn = db.get_connection('/data/library.db')
m.run_cycle(conn, '/music')
"
sqlite3 ./test-data/library.db "SELECT path, bpm, key, mood_happy FROM tracks JOIN features USING(path);"
```

Expected: eine Zeile pro Testdatei mit plausiblem BPM/Key/Mood-Wert, `status
= 'ok'` in der `tracks`-Tabelle.

- [ ] **Step 4: Commit**

```bash
git add crate_mind/analysis/main.py
git commit -m "feat: wire scan, diff, essentia analysis and db into main loop"
```

---

### Task 8: Deployment-Konfiguration

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: `docker-compose.yml` schreiben**

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
```

- [ ] **Step 2: Lokal (oder auf dem Zielhost) Compose-Syntax prüfen**

```bash
docker compose config
```

Expected: gibt die aufgelöste Config ohne Fehler aus.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose deployment config"
```

---

### Task 9: Deployment auf minime-3.local

**Files:** keine neuen — nur Ausführung auf dem Zielhost

- [ ] **Step 1: Projekt auf den Host kopieren**

```bash
rsync -av --exclude .git --exclude test-music --exclude test-data --exclude data \
  ~/projects/CrateMind2/ dirk.lange@minime-3.local:~/crate-mind-analysis/
```

- [ ] **Step 2: Container auf dem Host starten**

```bash
ssh dirk.lange@minime-3.local "cd ~/crate-mind-analysis && docker compose up -d --build"
```

- [ ] **Step 3: Logs prüfen**

```bash
ssh dirk.lange@minime-3.local "cd ~/crate-mind-analysis && docker compose logs -f --tail=50"
```

Expected: `Starting scan cycle...`, danach `Analyzed: <pfad>`-Zeilen für die
ersten Tracks, kein Absturz. Bei 32.582 Tracks läuft der initiale Backfill
über mehrere Stunden bis Tage verteilt auf wiederholte 30-Minuten-Zyklen —
das ist erwartet (siehe Design-Spec, Datenfluss-Abschnitt).

- [ ] **Step 4: Stichprobe in der SQLite-DB prüfen**

```bash
ssh dirk.lange@minime-3.local "sqlite3 ~/crate-mind-analysis/data/library.db \
  'SELECT COUNT(*) FROM tracks; SELECT COUNT(*) FROM tracks WHERE status = \"ok\";'"
```

Expected: wachsende Zahlen bei wiederholter Ausführung über die Zeit.

- [ ] **Step 5: Commit (falls Host-spezifische Anpassungen nötig waren)**

```bash
git add -A
git commit -m "chore: deployment adjustments for minime-3.local" --allow-empty
```

---

## Out of Scope

Scoring gegen den Apple-Music-Verlauf, Web-App/UI, VuIO-API-Integration —
siehe Design-Spec.
