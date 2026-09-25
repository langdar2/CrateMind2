# Frontend Redesign ("Midnight Glass") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the entire CrateMind2 frontend into the approved "Midnight Glass" visual design with a sidebar layout and a persistent live status bar, and add polling-based realtime updates for analysis progress and renderer playback status.

**Architecture:** Pure CSS + React changes, no new npm dependencies. A small `useInterval` hook centralizes the polling pattern used by the Dashboard, Renderers page, and the new persistent status bar. Design tokens live as CSS custom properties in `index.css`.

**Tech Stack:** React 18, react-router-dom, vanilla CSS (no framework), Vite.

Reference spec: `docs/superpowers/specs/2026-09-25-frontend-redesign-design.md`

---

### Task 1: Design tokens and global styles

**Files:**
- Modify: `webapp/frontend/src/index.css` (full rewrite)

- [ ] **Step 1: Rewrite `index.css` with the Midnight Glass design tokens and base styles**

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --bg-grad-start: #161227;
  --bg-grad-end: #0c0f22;
  --glass-bg: rgba(255, 255, 255, 0.06);
  --glass-bg-strong: rgba(255, 255, 255, 0.09);
  --glass-border: rgba(255, 255, 255, 0.1);
  --accent-from: #7c5cff;
  --accent-to: #5ce1ff;
  --text-primary: #ffffff;
  --text-secondary: #b7b7d1;
  --text-muted: #7c7c94;
  --danger: #ff8fa3;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: "Inter", system-ui, sans-serif;
  background: linear-gradient(160deg, var(--bg-grad-start), var(--bg-grad-end) 60%);
  background-attachment: fixed;
  color: var(--text-primary);
  min-height: 100vh;
}

.app-shell {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 70px;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.04);
  border-right: 1px solid var(--glass-border);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 0;
  gap: 18px;
}

.sidebar .brand {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--accent-from), var(--accent-to));
  margin-bottom: 8px;
}

.sidebar a {
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  text-decoration: none;
}

.sidebar a:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
}

.sidebar a.active {
  color: var(--text-primary);
  background: var(--glass-bg-strong);
}

.sidebar a svg {
  width: 20px;
  height: 20px;
}

.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

main {
  padding: 1.5rem;
  flex: 1;
}

.tile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1rem;
  align-items: start;
}

.tile {
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  padding: 1.1rem;
  margin-bottom: 1rem;
  backdrop-filter: blur(6px);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.25);
}

.tile h3 {
  margin-top: 0;
}

.progress-bar {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  height: 8px;
  overflow: hidden;
  margin: 10px 0;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-from), var(--accent-to));
  transition: width 0.3s ease;
}

.status-bar {
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(6px);
  border-top: 1px solid var(--glass-border);
  padding: 10px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-secondary);
  gap: 16px;
}

.status-bar .status-accent {
  background: linear-gradient(90deg, var(--accent-from), var(--accent-to));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-weight: 600;
}

input[type="text"],
select {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid var(--glass-border);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 8px 10px;
  font-family: inherit;
  font-size: 13px;
}

input[type="text"]::placeholder {
  color: var(--text-muted);
}

button {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--glass-border);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 8px 14px;
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
}

button:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.14);
}

button:disabled {
  opacity: 0.4;
  cursor: default;
}

.btn-primary {
  background: linear-gradient(90deg, var(--accent-from), var(--accent-to));
  border: none;
  color: #0c0f22;
  font-weight: 600;
}

.card-row {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--glass-border);
  border-radius: 10px;
  padding: 8px 12px;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-row .path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.error {
  color: var(--danger);
}

.field-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-list .field {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
}

.field-list .field .label {
  color: var(--text-muted);
}
```

- [ ] **Step 2: Verify the app still builds**

Run: `cd webapp/frontend && npm run build`
Expected: build succeeds, no CSS/syntax errors.

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/index.css
git commit -m "style: add Midnight Glass design tokens and base styles"
```

---

### Task 2: `useInterval` polling hook

**Files:**
- Create: `webapp/frontend/src/hooks.js`

- [ ] **Step 1: Create the hook**

```javascript
import { useEffect, useRef } from "react";

// ponytail: passing delayMs=null pauses polling (no interval created/cleared).
export function useInterval(callback, delayMs) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (delayMs === null) return;
    const id = setInterval(() => callbackRef.current(), delayMs);
    return () => clearInterval(id);
  }, [delayMs]);
}
```

- [ ] **Step 2: Manual verification**

This hook is the standard React "saved callback in a ref" interval pattern — no dedicated test file (per the design spec's testing section: no new test framework for this app). It will be exercised indirectly in Task 4/5/7 (Network tab shows recurring requests). No action needed here beyond a quick read-through: confirm `delayMs === null` skips creating an interval and the cleanup always clears the previous one.

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/hooks.js
git commit -m "feat: add useInterval polling hook"
```

---

### Task 3: Sidebar layout + persistent status bar in `App.jsx`

**Files:**
- Modify: `webapp/frontend/src/App.jsx` (full rewrite)
- Create: `webapp/frontend/src/components/StatusBar.jsx`

- [ ] **Step 1: Create the status bar component**

```jsx
import { useState } from "react";
import { useInterval } from "../hooks.js";
import { getStats, getRenderers, getPlaybackStatus } from "../api.js";

const POLL_MS = 3000;

// ponytail: "active" is a heuristic (non-empty status with at least one
// truthy/non-idle value) since VuIO's playback-status shape isn't fixed
// across DLNA/Chromecast/AirPlay. Good enough for a home-network status bar;
// revisit if a renderer's idle response starts showing up as "active".
function isActive(status) {
  if (!status || typeof status !== "object") return false;
  const values = Object.values(status);
  if (values.length === 0) return false;
  return values.some((v) => v !== null && v !== false && v !== "" && v !== "stopped" && v !== "idle");
}

function extractTrackLabel(status) {
  const candidate = status.title || status.track || status.now_playing || status.name;
  if (typeof candidate === "string") return candidate;
  return "Wiedergabe aktiv";
}

export default function StatusBar() {
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [activeRenderer, setActiveRenderer] = useState(null);

  useInterval(() => {
    getStats()
      .then((stats) => {
        const counts = stats.status_counts || {};
        const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
        const pending = counts.pending || 0;
        setAnalyzing(pending > 0);
        setProgress(total > 0 ? Math.round(((total - pending) / total) * 100) : 0);
      })
      .catch(() => {});
  }, POLL_MS);

  useInterval(() => {
    getRenderers()
      .then(async ({ renderers }) => {
        for (const renderer of renderers) {
          try {
            const status = await getPlaybackStatus(renderer.id);
            if (isActive(status)) {
              setActiveRenderer({ name: renderer.friendly_name, label: extractTrackLabel(status) });
              return;
            }
          } catch {
            // ignore unreachable renderer, try the next one
          }
        }
        setActiveRenderer(null);
      })
      .catch(() => {});
  }, POLL_MS);

  if (!analyzing && !activeRenderer) return null;

  return (
    <div className="status-bar">
      <span>
        {activeRenderer ? `${activeRenderer.label} → ${activeRenderer.name}` : ""}
      </span>
      <span>
        {analyzing && <span className="status-accent">Analyse: {progress}%</span>}
      </span>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite `App.jsx` with the sidebar layout**

```jsx
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Playlists from "./pages/Playlists.jsx";
import Renderers from "./pages/Renderers.jsx";
import StatusBar from "./components/StatusBar.jsx";

const DashboardIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="3" width="8" height="8" rx="2" />
    <rect x="13" y="3" width="8" height="8" rx="2" />
    <rect x="3" y="13" width="8" height="8" rx="2" />
    <rect x="13" y="13" width="8" height="8" rx="2" />
  </svg>
);

const PlaylistIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="4" y1="6" x2="20" y2="6" />
    <line x1="4" y1="12" x2="20" y2="12" />
    <line x1="4" y1="18" x2="14" y2="18" />
  </svg>
);

const RendererIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="4" y="2" width="16" height="20" rx="2" />
    <circle cx="12" cy="15" r="4" />
    <line x1="12" y1="6" x2="12.01" y2="6" />
  </svg>
);

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <nav className="sidebar">
          <div className="brand" />
          <NavLink to="/" end title="Dashboard">
            <DashboardIcon />
          </NavLink>
          <NavLink to="/playlists" title="Playlists">
            <PlaylistIcon />
          </NavLink>
          <NavLink to="/renderers" title="Renderer">
            <RendererIcon />
          </NavLink>
        </nav>
        <div className="app-main">
          <main>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/playlists" element={<Playlists />} />
              <Route path="/renderers" element={<Renderers />} />
            </Routes>
          </main>
          <StatusBar />
        </div>
      </div>
    </BrowserRouter>
  );
}
```

- [ ] **Step 3: Verify build**

Run: `cd webapp/frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/App.jsx webapp/frontend/src/components/StatusBar.jsx
git commit -m "feat: sidebar layout and persistent live status bar"
```

---

### Task 4: Dashboard — glass tiles, progress bar, polling

**Files:**
- Modify: `webapp/frontend/src/pages/Dashboard.jsx` (full rewrite)

- [ ] **Step 1: Rewrite `Dashboard.jsx`**

```jsx
import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { getStats, getFailedTracks } from "../api.js";
import { useInterval } from "../hooks.js";

const PAGE_SIZE = 50;
const POLL_MS = 3000;

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

  const pending = stats ? stats.status_counts.pending || 0 : undefined;
  useInterval(
    () => {
      getStats().then(setStats).catch(() => {});
    },
    pending === undefined || pending > 0 ? POLL_MS : null
  );

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
  if (analyzed === 0 && pending === 0) {
    return <p>Noch keine Analyse-Daten vorhanden.</p>;
  }

  const counts = stats.status_counts;
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  const progressPct = total > 0 ? Math.round(((total - (counts.pending || 0)) / total) * 100) : 0;

  const keyData = Object.entries(stats.key_counts).map(([key, count]) => ({ key, count }));

  return (
    <div className="tile-grid">
      <div className="tile">
        <h3 onClick={() => setExpanded(!expanded)} style={{ cursor: "pointer" }}>
          Analyse-Fortschritt {expanded ? "▾" : "▸"}
        </h3>
        <div className="progress-bar">
          <div className="progress-bar-fill" style={{ width: `${progressPct}%` }} />
        </div>
        <ul className="field-list">
          {Object.entries(counts).map(([status, count]) => (
            <li key={status} className="field">
              <span className="label">{status}</span>
              <span>{count}</span>
            </li>
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
                <li key={t.path} className="card-row">
                  <span className="path">{t.path}</span>
                  <span className="error">{t.error_message}</span>
                </li>
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
            <XAxis dataKey="bucket" stroke="#7c7c94" />
            <YAxis stroke="#7c7c94" />
            <Tooltip contentStyle={{ background: "#161227", border: "1px solid rgba(255,255,255,0.1)" }} />
            <Bar dataKey="count" fill="#7c5cff" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="tile">
        <h3>Key-Verteilung</h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={keyData}>
            <XAxis dataKey="key" hide />
            <YAxis stroke="#7c7c94" />
            <Tooltip contentStyle={{ background: "#161227", border: "1px solid rgba(255,255,255,0.1)" }} />
            <Bar dataKey="count" fill="#5ce1ff" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="tile">
        <h3>Mood-Durchschnitte</h3>
        <ul className="field-list">
          {Object.entries(stats.mood_averages).map(([mood, value]) => (
            <li key={mood} className="field">
              <span className="label">{mood}</span>
              <span>{value.toFixed(2)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd webapp/frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/pages/Dashboard.jsx
git commit -m "style: restyle Dashboard with progress bar and live polling"
```

---

### Task 5: Renderers — glass cards, formatted status, polling

**Files:**
- Modify: `webapp/frontend/src/pages/Renderers.jsx` (full rewrite)

- [ ] **Step 1: Rewrite `Renderers.jsx`**

```jsx
import { useEffect, useState } from "react";
import { getRenderers, getPlaybackStatus } from "../api.js";
import { useInterval } from "../hooks.js";

const POLL_MS = 3000;

function formatStatus(status) {
  return Object.entries(status).map(([key, value]) => ({
    label: key,
    value: typeof value === "object" && value !== null ? JSON.stringify(value) : String(value),
  }));
}

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

  const trackedIds = Object.keys(status);
  useInterval(
    () => {
      trackedIds.forEach((id) => checkStatus(id));
    },
    trackedIds.length > 0 ? POLL_MS : null
  );

  if (error) return <p className="error">Fehler: {error}</p>;

  return (
    <div className="tile-grid">
      {renderers.map((r) => (
        <div className="tile" key={r.id}>
          <h3>{r.friendly_name}</h3>
          <p className="field-list"><span className="label">{r.protocol}</span></p>
          <button onClick={() => checkStatus(r.id)}>Status abfragen</button>
          {status[r.id] && (
            <ul className="field-list" style={{ marginTop: "10px" }}>
              {formatStatus(status[r.id]).map(({ label, value }) => (
                <li key={label} className="field">
                  <span className="label">{label}</span>
                  <span>{value}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd webapp/frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/pages/Renderers.jsx
git commit -m "style: restyle Renderers with formatted status and live polling"
```

---

### Task 6: Playlists — glass cards for seed results and preview rows

**Files:**
- Modify: `webapp/frontend/src/pages/Playlists.jsx:106-161` (JSX return block only; state/logic unchanged)

- [ ] **Step 1: Replace the seed-search results list**

Find this block (around line 113-136):

```jsx
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
```

Replace with:

```jsx
          <div>
            <input
              type="text"
              placeholder="Track suchen..."
              value={seedQuery}
              onChange={(e) => searchSeed(e.target.value)}
            />
            <ul>
              {seedResults.map((t) => (
                <li
                  key={t.path}
                  className="card-row"
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    setSeedPath(t.path);
                    setSeedQuery(t.path);
                    setSeedResults([]);
                  }}
                >
                  <span className="path">{t.path}</span>
                </li>
              ))}
            </ul>
          </div>
```

- [ ] **Step 2: Replace the preview list**

Find this block (around line 140-161):

```jsx
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
```

Replace with:

```jsx
      {preview.length > 0 && (
        <div className="tile">
          <h3>Vorschau ({preview.length} Tracks)</h3>
          <ul>
            {preview.map((t, i) => (
              <li key={t.path} className="card-row">
                <span className="path">{t.path} ({t.bpm ? t.bpm.toFixed(0) : "?"} BPM, {t.key})</span>
                <span style={{ display: "flex", gap: "4px" }}>
                  <button onClick={() => moveTrack(i, -1)} disabled={i === 0}>↑</button>
                  <button onClick={() => moveTrack(i, 1)} disabled={i === preview.length - 1}>↓</button>
                  <button onClick={() => removeTrack(t.path)}>Entfernen</button>
                </span>
              </li>
            ))}
          </ul>
          <input
            type="text"
            placeholder="Playlist-Name"
            value={playlistName}
            onChange={(e) => setPlaylistName(e.target.value)}
          />
          <button className="btn-primary" onClick={handleCreate}>In VuIO anlegen</button>
        </div>
      )}
```

- [ ] **Step 3: Restyle the renderer-cast buttons**

Find (around line 163-170):

```jsx
      {playlistId && (
        <div className="tile">
          <h3>Auf Renderer abspielen</h3>
          {renderers.map((r) => (
            <button key={r.id} onClick={() => handleCast(r.id)}>{r.friendly_name}</button>
          ))}
        </div>
      )}
```

Replace with:

```jsx
      {playlistId && (
        <div className="tile">
          <h3>Auf Renderer abspielen</h3>
          {renderers.map((r) => (
            <button key={r.id} className="btn-primary" onClick={() => handleCast(r.id)} style={{ marginRight: "8px" }}>
              {r.friendly_name}
            </button>
          ))}
        </div>
      )}
```

- [ ] **Step 4: Verify build**

Run: `cd webapp/frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/pages/Playlists.jsx
git commit -m "style: restyle Playlists seed results and preview rows"
```

---

### Task 7: Full verification

- [ ] **Step 1: Build the whole frontend**

Run: `cd webapp/frontend && npm run build`
Expected: succeeds with no errors (pre-existing chunk-size warning is fine).

- [ ] **Step 2: Run the dev server and visually check every page in the browser**

Run: `cd webapp/frontend && npm run dev` (or use the project's preview tooling)

Check:
- Sidebar renders with 3 icons, active route highlighted, gradient brand mark visible.
- Dashboard: glass tiles, gradient progress bar reflecting real `status_counts`, charts still render, expandable failed-tracks section still works (search + "Mehr laden").
- Playlists: seed search results and preview rows render as glass rows; creating/casting a playlist still works end-to-end.
- Renderers: cards show formatted (non-JSON-dump) status fields after clicking "Status abfragen"; once fetched, requests to `/api/playback-status` for that renderer recur automatically every ~3s in the Network tab.
- Status bar: hidden when nothing is analyzing/casting; open the Network tab and confirm `/api/stats` requests recur every ~3s while `pending > 0`, and stop once `pending` reaches 0 (may require a live pipeline run to fully observe; at minimum confirm no requests fire when `pending` is already 0 on load).

- [ ] **Step 3: Fix any issues found, then do a final commit if changes were needed**

```bash
git add -A
git commit -m "fix: address issues found during frontend redesign verification"
```

(Skip this commit if no fixes were needed.)
