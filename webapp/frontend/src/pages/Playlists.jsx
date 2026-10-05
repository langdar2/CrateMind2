import { useEffect, useRef, useState } from "react";
import {
  getStats,
  previewPlaylist,
  createPlaylist,
  getRenderers,
  castPlaylist,
  searchTracks,
} from "../api.js";

const MODES = [
  { id: "manual", label: "Manuell" },
  { id: "prompt", label: "Prompt" },
  { id: "seed", label: "Seed-Track" },
  { id: "smart", label: "Smart (Vibe)" },
];

const MOOD_FIELDS = [
  { key: "danceability", label: "Danceability" },
  { key: "mood_happy", label: "Happy" },
  { key: "mood_aggressive", label: "Aggressive" },
  { key: "mood_relaxed", label: "Relaxed" },
  { key: "mood_party", label: "Party" },
];

export default function Playlists() {
  const [hasTracks, setHasTracks] = useState(null);
  const [mode, setMode] = useState("manual");
  const [prompt, setPrompt] = useState("");
  const [seedQuery, setSeedQuery] = useState("");
  const [seedResults, setSeedResults] = useState([]);
  const [seedPath, setSeedPath] = useState("");
  const [moodPrompt, setMoodPrompt] = useState("");
  const [bpmRange, setBpmRange] = useState([80, 160]);
  const [minPercentile, setMinPercentile] = useState(0);
  const [moodMins, setMoodMins] = useState({});
  const [preview, setPreview] = useState([]);
  const [playlistName, setPlaylistName] = useState("");
  const [playlistId, setPlaylistId] = useState(null);
  const [renderers, setRenderers] = useState([]);
  const [error, setError] = useState(null);
  const seedQueryRef = useRef("");

  useEffect(() => {
    getStats().then((s) => setHasTracks((s.status_counts.ok || 0) > 0));
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
    seedQueryRef.current = q;
    if (q.length < 2) {
      setSeedResults([]);
      return;
    }
    const result = await searchTracks(q);
    if (seedQueryRef.current === q) {
      setSeedResults(result.tracks);
    }
  };

  const manualCriteria = () => {
    const criteria = { min_bpm: bpmRange[0], max_bpm: bpmRange[1] };
    // Only send it when engaged - a min_percentile of 0 would still sort
    // favourites to the top and hide everything the import could not score.
    if (minPercentile > 0) criteria.min_percentile = minPercentile;
    for (const [key, value] of Object.entries(moodMins)) {
      criteria[`min_${key}`] = value;
    }
    return criteria;
  };

  const runPreview = async (body) => {
    setError(null);
    try {
      const result = await previewPlaylist(
        body ||
          (mode === "manual"
            ? { mode, criteria: manualCriteria() }
            : mode === "prompt"
            ? { mode, prompt }
            : mode === "smart"
            ? { mode, seed_path: seedPath || undefined, mood_prompt: moodPrompt }
            : { mode, seed_path: seedPath })
      );
      setPreview(result.tracks);
    } catch (e) {
      setError(e.message);
    }
  };

  // ponytail: manual mode is free (no LLM/API cost), so auto-preview on every
  // slider change with a short debounce; other modes keep the explicit button.
  useEffect(() => {
    if (mode !== "manual" || hasTracks !== true) return;
    const timer = setTimeout(() => runPreview({ mode, criteria: manualCriteria() }), 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, hasTracks, bpmRange, minPercentile, moodMins]);

  const toggleMoodField = (key, checked) => {
    setMoodMins((prev) => {
      const next = { ...prev };
      if (checked) next[key] = 0.5;
      else delete next[key];
      return next;
    });
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
        <div className="segmented">
          {MODES.map((m) => (
            <button
              key={m.id}
              className={mode === m.id ? "active" : ""}
              onClick={() => setMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>

        {mode === "manual" && (
          <div className="field-list" style={{ marginTop: "12px" }}>
            <div className="slider-row">
              <span className="label">BPM</span>
              <input
                type="range"
                min="40"
                max="200"
                value={bpmRange[0]}
                onChange={(e) => setBpmRange([Math.min(+e.target.value, bpmRange[1]), bpmRange[1]])}
              />
              <input
                type="range"
                min="40"
                max="200"
                value={bpmRange[1]}
                onChange={(e) => setBpmRange([bpmRange[0], Math.max(+e.target.value, bpmRange[0])])}
              />
              <span className="slider-value">{bpmRange[0]}–{bpmRange[1]}</span>
            </div>
            <div className="slider-row">
              <span className="label">Vorliebe</span>
              <input
                type="range"
                min="0"
                max="95"
                step="5"
                value={minPercentile}
                onChange={(e) => setMinPercentile(+e.target.value)}
                style={{ gridColumn: "2 / 4" }}
              />
              <span className="slider-value">
                {minPercentile > 0 ? `Top ${100 - minPercentile}%` : "egal"}
              </span>
            </div>
            {MOOD_FIELDS.map((f) => (
              <div className="slider-row" key={f.key}>
                <label className="label">
                  <input
                    type="checkbox"
                    checked={f.key in moodMins}
                    onChange={(e) => toggleMoodField(f.key, e.target.checked)}
                  />{" "}
                  {f.label}
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  disabled={!(f.key in moodMins)}
                  value={moodMins[f.key] ?? 0.5}
                  onChange={(e) => setMoodMins((prev) => ({ ...prev, [f.key]: +e.target.value }))}
                />
                <span className="slider-value">{f.key in moodMins ? `≥ ${moodMins[f.key].toFixed(2)}` : "—"}</span>
              </div>
            ))}
          </div>
        )}

        {mode === "prompt" && (
          <input
            type="text"
            placeholder="z.B. 'energiegeladenes Workout' oder 'entspannter Sonntagmorgen'"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        )}

        {(mode === "seed" || mode === "smart") && (
          <div>
            <input
              type="text"
              placeholder={mode === "smart" ? "Optional: Seed-Track suchen..." : "Track suchen..."}
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
        )}

        {mode === "smart" && (
          <input
            type="text"
            placeholder="Beschreibe die Stimmung, z.B. 'entspannter Sonntagmorgen'"
            value={moodPrompt}
            onChange={(e) => setMoodPrompt(e.target.value)}
          />
        )}

        {mode !== "manual" && <button onClick={() => runPreview()}>Vorschau erzeugen</button>}
      </div>

      {preview.length > 0 && (
        <div className="tile">
          <h3>Vorschau ({preview.length} Tracks)</h3>
          <ul>
            {preview.map((t, i) => (
              <li key={t.path} className="card-row">
                <span className="path">
                  {t.path}
                  <span className="chips">
                    <span className="chip">{t.bpm ? t.bpm.toFixed(0) : "?"} BPM</span>
                    <span className="chip">{t.key}</span>
                    {t.danceability != null && <span className="chip">Dance {t.danceability.toFixed(2)}</span>}
                    {t.percentile != null && (
                      <span className="chip chip-score">Top {Math.max(1, 100 - t.percentile)}%</span>
                    )}
                  </span>
                </span>
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
    </div>
  );
}
