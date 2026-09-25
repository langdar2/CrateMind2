# Fehler-Übersicht im Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the failure reason for tracks the analysis pipeline fails to process, and surface a searchable, paginated list of them in an expandable "Analyse-Fortschritt" tile on the Dashboard.

**Architecture:** Add a nullable `error_message` column to the analysis pipeline's `tracks` table (migrated in place since `minime-3.local` already has data). The pipeline captures `str(exception)` on failure and clears it on success. A one-time startup migration resets pre-existing `failed` tracks with no stored reason back to `pending` so they get re-analyzed and gain a reason. The read-only webapp backend gets a new query function and endpoint to search failed tracks with pagination; the frontend adds a client function and makes the existing tile expandable with a search box, list, and "Mehr laden" button.

**Tech Stack:** Python 3.11, sqlite3, FastAPI, React (Vite), plain `assert`-based tests (matches existing project convention).

---

### Task 1: Analysis pipeline — schema migration + error_message in upsert_track

**Files:**
- Modify: `crate_mind/analysis/db.py`
- Test: `crate_mind/analysis/test_db.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `crate_mind/analysis/test_db.py`:

```python
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from crate_mind.analysis import db


def test_get_connection_adds_error_message_column_to_existing_table():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    # Simulate a pre-existing DB from before this feature: tracks table
    # without error_message, already containing a failed row.
    legacy_conn = sqlite3.connect(tmp.name)
    legacy_conn.executescript(
        """
        CREATE TABLE tracks (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            last_scanned REAL NOT NULL
        );
        """
    )
    legacy_conn.execute(
        "INSERT INTO tracks (path, mtime, size, status, last_scanned) VALUES (?, ?, ?, ?, ?)",
        ("/music/old-failed.mp3", 1.0, 100, "failed", 1.0),
    )
    legacy_conn.commit()
    legacy_conn.close()

    conn = db.get_connection(tmp.name)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()}
    assert "error_message" in columns


def test_get_connection_is_idempotent_when_column_already_exists():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    conn1 = db.get_connection(tmp.name)
    conn1.close()

    # Reconnecting must not raise "duplicate column name".
    conn2 = db.get_connection(tmp.name)
    columns = {row[1] for row in conn2.execute("PRAGMA table_info(tracks)").fetchall()}
    assert "error_message" in columns


def test_upsert_track_sets_error_message_on_failed():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = db.get_connection(tmp.name)

    db.upsert_track(conn, "/music/bad.mp3", mtime=1.0, size=100, status="failed", error_message="boom")

    row = conn.execute("SELECT status, error_message FROM tracks WHERE path = ?", ("/music/bad.mp3",)).fetchone()
    assert row == ("failed", "boom")


def test_upsert_track_clears_error_message_on_ok():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = db.get_connection(tmp.name)

    db.upsert_track(conn, "/music/a.mp3", mtime=1.0, size=100, status="failed", error_message="boom")
    db.upsert_track(conn, "/music/a.mp3", mtime=2.0, size=200, status="ok")

    row = conn.execute("SELECT status, error_message FROM tracks WHERE path = ?", ("/music/a.mp3",)).fetchone()
    assert row == ("ok", None)


def test_reset_failed_without_reason_resets_to_pending():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = db.get_connection(tmp.name)

    db.upsert_track(conn, "/music/old.mp3", mtime=1.0, size=100, status="failed", error_message=None)
    db.upsert_track(conn, "/music/new.mp3", mtime=1.0, size=100, status="failed", error_message="boom")

    db.reset_failed_without_reason(conn)

    old_status = conn.execute("SELECT status FROM tracks WHERE path = ?", ("/music/old.mp3",)).fetchone()[0]
    new_status = conn.execute("SELECT status FROM tracks WHERE path = ?", ("/music/new.mp3",)).fetchone()[0]
    assert old_status == "pending"
    assert new_status == "failed"


if __name__ == "__main__":
    test_get_connection_adds_error_message_column_to_existing_table()
    test_get_connection_is_idempotent_when_column_already_exists()
    test_upsert_track_sets_error_message_on_failed()
    test_upsert_track_clears_error_message_on_ok()
    test_reset_failed_without_reason_resets_to_pending()
    print("All analysis db tests passed.")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 crate_mind/analysis/test_db.py`
Expected: `AttributeError: module 'crate_mind.analysis.db' has no attribute 'reset_failed_without_reason'` (or a `sqlite3.OperationalError: no such column: error_message` from the earlier tests, since the column doesn't exist yet)

- [ ] **Step 3: Implement the migration and error_message support**

In `crate_mind/analysis/db.py`, replace the `get_connection` function and `upsert_track` function, and add `reset_failed_without_reason`:

```python
def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()}
    if "error_message" not in columns:
        conn.execute("ALTER TABLE tracks ADD COLUMN error_message TEXT")
        conn.commit()
    return conn
```

```python
def upsert_track(conn, path, mtime, size, status, error_message=None) -> None:
    conn.execute(
        """
        INSERT INTO tracks (path, mtime, size, status, last_scanned, error_message)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            mtime = excluded.mtime,
            size = excluded.size,
            status = excluded.status,
            last_scanned = excluded.last_scanned,
            error_message = excluded.error_message
        """,
        (path, mtime, size, status, time.time(), error_message),
    )
    conn.commit()
```

```python
def reset_failed_without_reason(conn) -> None:
    conn.execute("UPDATE tracks SET status = 'pending' WHERE status = 'failed' AND error_message IS NULL")
    conn.commit()
```

Note: `Path` is already imported at the top of the file (used in the existing `get_connection`). No new imports needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 crate_mind/analysis/test_db.py`
Expected: `All analysis db tests passed.`

- [ ] **Step 5: Commit**

```bash
git add crate_mind/analysis/db.py crate_mind/analysis/test_db.py
git commit -m "$(cat <<'EOF'
feat(analysis): persist failure reason on tracks

Adds a nullable error_message column (migrated in place for existing
DBs), extends upsert_track to set/clear it, and adds a one-time reset
for pre-existing failed tracks that have no stored reason.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Analysis pipeline — wire exception message into run_cycle + startup reset

**Files:**
- Modify: `crate_mind/analysis/main.py`

- [ ] **Step 1: Read the current file to confirm line numbers**

Run: `grep -n "except Exception\|def run_cycle\|def main\|get_connection" crate_mind/analysis/main.py`

- [ ] **Step 2: Update the except branch to capture the exception message**

In `crate_mind/analysis/main.py`, inside `run_cycle`, change:

```python
            except Exception:
                db.upsert_track(conn, path, mtime, size, status="failed")
                db.delete_features(conn, path)
                print(f"Failed to analyze: {path}")
                traceback.print_exc()
```

to:

```python
            except Exception as e:
                db.upsert_track(conn, path, mtime, size, status="failed", error_message=str(e))
                db.delete_features(conn, path)
                print(f"Failed to analyze: {path}")
                traceback.print_exc()
```

- [ ] **Step 3: Call the one-time reset once at startup**

Find where `db.get_connection(...)` is called in `main()` (or module-level startup code) and add a call to `db.reset_failed_without_reason(conn)` immediately after obtaining the connection, before the scan loop starts. For example, if `main()` currently reads:

```python
def main():
    music_dir = os.environ.get("MUSIC_DIR", "/music")
    db_path = os.environ.get("DB_PATH", "/data/library.db")
    conn = db.get_connection(db_path)

    while True:
        run_cycle(conn, music_dir)
        time.sleep(int(os.environ.get("SCAN_INTERVAL_SECONDS", "1800")))
```

change it to:

```python
def main():
    music_dir = os.environ.get("MUSIC_DIR", "/music")
    db_path = os.environ.get("DB_PATH", "/data/library.db")
    conn = db.get_connection(db_path)
    db.reset_failed_without_reason(conn)

    while True:
        run_cycle(conn, music_dir)
        time.sleep(int(os.environ.get("SCAN_INTERVAL_SECONDS", "1800")))
```

(If the actual structure of `main()` differs from this example, apply the same change in spirit: call `db.reset_failed_without_reason(conn)` exactly once, right after `get_connection`, before the first `run_cycle`.)

- [ ] **Step 4: Manually verify with a quick script**

Run:
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from crate_mind.analysis import db, main as analysis_main

tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
tmp.close()
conn = db.get_connection(tmp.name)

def boom(*a, **k):
    raise ValueError('bad file')

import crate_mind.analysis.features as features
features.load_audio_for_analysis = boom

analysis_main.run_cycle(conn, '/nonexistent')
print('run_cycle executed without crashing')
"
```
Expected: `run_cycle executed without crashing` (this just confirms the module still imports and runs; the real exercise of the except-branch is covered by Task 1's unit tests plus manual review of the diff).

- [ ] **Step 5: Commit**

```bash
git add crate_mind/analysis/main.py
git commit -m "$(cat <<'EOF'
feat(analysis): capture exception message on analysis failure

run_cycle now stores str(exception) as error_message when a track
fails to analyze. main() resets pre-existing failed-without-reason
tracks to pending once at startup so they get a reason on retry.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Webapp backend — search_failed_tracks query function

**Files:**
- Modify: `webapp/backend/db.py`
- Test: `webapp/backend/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `webapp/backend/test_db.py` (before the `if __name__ == "__main__":` block):

```python
def test_search_failed_tracks_returns_error_message_and_total():
    path = _make_test_db()
    conn = analysis_db.get_connection(path)
    analysis_db.upsert_track(conn, "/music/c.mp3", mtime=1.0, size=100, status="failed", error_message="decode error")
    conn.close()
    conn = db.get_connection(path)

    result = db.search_failed_tracks(conn)

    assert result["total"] == 1
    assert result["tracks"] == [{"path": "/music/c.mp3", "error_message": "decode error"}]


def test_search_failed_tracks_filters_by_query():
    path = _make_test_db()
    conn = analysis_db.get_connection(path)
    analysis_db.upsert_track(conn, "/music/c.mp3", mtime=1.0, size=100, status="failed", error_message="decode error")
    analysis_db.upsert_track(conn, "/music/d.mp3", mtime=1.0, size=100, status="failed", error_message="io error")
    conn.close()
    conn = db.get_connection(path)

    result = db.search_failed_tracks(conn, query="d.mp3")

    assert result["total"] == 1
    assert result["tracks"][0]["path"] == "/music/d.mp3"


def test_search_failed_tracks_paginates_with_limit_and_offset():
    path = _make_test_db()
    conn = analysis_db.get_connection(path)
    analysis_db.upsert_track(conn, "/music/c.mp3", mtime=1.0, size=100, status="failed", error_message="e1")
    analysis_db.upsert_track(conn, "/music/d.mp3", mtime=1.0, size=100, status="failed", error_message="e2")
    analysis_db.upsert_track(conn, "/music/e.mp3", mtime=1.0, size=100, status="failed", error_message="e3")
    conn.close()
    conn = db.get_connection(path)

    page1 = db.search_failed_tracks(conn, limit=2, offset=0)
    page2 = db.search_failed_tracks(conn, limit=2, offset=2)

    assert page1["total"] == 3
    assert len(page1["tracks"]) == 2
    assert page2["total"] == 3
    assert len(page2["tracks"]) == 1
```

Note: the existing `_make_test_db()` in this file already creates `/music/c.mp3` with `status="failed"` and no `error_message` — the new tests above re-upsert it with an explicit `error_message` where needed, and the pre-existing `test_fetch_stats_counts_status_and_aggregates` test already counts it as `status_counts["failed"] == 1` regardless of `error_message`, so no existing test breaks.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 webapp/backend/test_db.py`
Expected: `AttributeError: module 'db' has no attribute 'search_failed_tracks'`

- [ ] **Step 3: Implement search_failed_tracks**

In `webapp/backend/db.py`, add this function after `search_ok_tracks`:

```python
def search_failed_tracks(conn: sqlite3.Connection, query: str = "", limit: int = 50, offset: int = 0) -> dict:
    like = f"%{query}%"
    total = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE status = 'failed' AND path LIKE ?",
        (like,),
    ).fetchone()[0]
    rows = conn.execute(
        """
        SELECT path, error_message
        FROM tracks
        WHERE status = 'failed' AND path LIKE ?
        ORDER BY path
        LIMIT ? OFFSET ?
        """,
        (like, limit, offset),
    ).fetchall()
    return {
        "tracks": [{"path": path, "error_message": error_message} for path, error_message in rows],
        "total": total,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 webapp/backend/test_db.py`
Expected: `All db tests passed.`

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/db.py webapp/backend/test_db.py
git commit -m "$(cat <<'EOF'
feat(webapp): add search_failed_tracks query with pagination

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Webapp backend — /api/tracks/failed endpoint

**Files:**
- Modify: `webapp/backend/app.py`
- Test: `webapp/backend/test_app.py`

- [ ] **Step 1: Write the failing test**

Append to `webapp/backend/test_app.py` (before the `if __name__ == "__main__":` block):

```python
def test_failed_tracks_endpoint():
    with TestClient(app_module.app) as client:
        response = client.get("/api/tracks/failed")
    assert response.status_code == 200
    body = response.json()
    assert "tracks" in body
    assert "total" in body


def test_failed_tracks_endpoint_filters_by_query():
    with TestClient(app_module.app) as client:
        response = client.get("/api/tracks/failed", params={"q": "nomatch"})
    assert response.status_code == 200
    assert response.json()["tracks"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 webapp/backend/test_app.py`
Expected: `AssertionError` from `response.status_code == 200` (404, since the route doesn't exist yet)

- [ ] **Step 3: Find the existing /api/tracks endpoint for pattern reference**

Run: `grep -n "/api/tracks\|search_ok_tracks" webapp/backend/app.py`

- [ ] **Step 4: Add the new endpoint**

In `webapp/backend/app.py`, add a new route near the existing `/api/tracks` endpoint, following the same pattern (reading `conn` from app state, using query params). Add:

```python
@app.get("/api/tracks/failed")
def get_failed_tracks(q: str = "", limit: int = 50, offset: int = 0):
    return db.search_failed_tracks(app.state.conn, query=q, limit=limit, offset=offset)
```

Match the exact way the existing `/api/tracks` handler accesses the connection (e.g. `app.state.conn` vs. a module-level `conn` vs. a dependency) — use `grep -n "def get_tracks\|app.state.conn\|^conn = " webapp/backend/app.py` first and mirror whatever pattern that handler already uses instead of assuming `app.state.conn`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 webapp/backend/test_app.py`
Expected: `All app tests passed.`

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/app.py webapp/backend/test_app.py
git commit -m "$(cat <<'EOF'
feat(webapp): add GET /api/tracks/failed endpoint

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Webapp frontend — expandable failed-tracks list in Dashboard

**Files:**
- Modify: `webapp/frontend/src/api.js`
- Modify: `webapp/frontend/src/pages/Dashboard.jsx`

- [ ] **Step 1: Add the API client function**

In `webapp/frontend/src/api.js`, add after `searchTracks`:

```javascript
export const getFailedTracks = (q, limit, offset) =>
  request(`/tracks/failed?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`);
```

- [ ] **Step 2: Make the Analyse-Fortschritt tile expandable**

Replace the full contents of `webapp/frontend/src/pages/Dashboard.jsx` with:

```jsx
import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { getStats, getFailedTracks } from "../api.js";

const PAGE_SIZE = 50;

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [failedTracks, setFailedTracks] = useState([]);
  const [failedTotal, setFailedTotal] = useState(0);
  const [failedError, setFailedError] = useState(null);

  useEffect(() => {
    getStats().then(setStats).catch((e) => setError(e.message));
  }, []);

  const loadFailed = (q, offset, append) => {
    setFailedError(null);
    getFailedTracks(q, PAGE_SIZE, offset)
      .then((result) => {
        setFailedTracks((prev) => (append ? [...prev, ...result.tracks] : result.tracks));
        setFailedTotal(result.total);
      })
      .catch((e) => setFailedError(e.message));
  };

  useEffect(() => {
    if (!expanded) return;
    loadFailed(query, 0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded, query]);

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
        <h3 onClick={() => setExpanded(!expanded)} style={{ cursor: "pointer" }}>
          Analyse-Fortschritt {expanded ? "▾" : "▸"}
        </h3>
        <ul>
          {Object.entries(stats.status_counts).map(([status, count]) => (
            <li key={status}>{status}: {count}</li>
          ))}
        </ul>
        {expanded && (
          <div>
            <input
              type="text"
              placeholder="Pfad durchsuchen..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {failedError && <p className="error">Fehler: {failedError}</p>}
            <ul>
              {failedTracks.map((t) => (
                <li key={t.path}>{t.path} — {t.error_message}</li>
              ))}
            </ul>
            {failedTracks.length < failedTotal && (
              <button onClick={() => loadFailed(query, failedTracks.length, true)}>Mehr laden</button>
            )}
          </div>
        )}
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

- [ ] **Step 3: Verify the frontend builds**

Run: `cd webapp/frontend && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/api.js webapp/frontend/src/pages/Dashboard.jsx
git commit -m "$(cat <<'EOF'
feat(webapp): expandable failed-tracks list on Dashboard

Analyse-Fortschritt tile is now clickable and expands into a
search box + paginated list of failed tracks with their error
messages, loaded via the new /api/tracks/failed endpoint.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Full verification pass

**Files:** None (verification only)

- [ ] **Step 1: Run every backend test file**

Run:
```bash
python3 tests/test_diff.py
python3 crate_mind/analysis/test_db.py
python3 webapp/backend/test_db.py
python3 webapp/backend/test_app.py
```
Expected: all four print their respective "All ... passed." success line, no assertion errors.

- [ ] **Step 2: Run the frontend build**

Run: `cd webapp/frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Confirm no leftover debug code**

Run: `git diff main --stat` (or `git log --oneline` since Task 1) to review the full set of changed files matches exactly: `crate_mind/analysis/db.py`, `crate_mind/analysis/test_db.py`, `crate_mind/analysis/main.py`, `webapp/backend/db.py`, `webapp/backend/test_db.py`, `webapp/backend/app.py`, `webapp/backend/test_app.py`, `webapp/frontend/src/api.js`, `webapp/frontend/src/pages/Dashboard.jsx`.
