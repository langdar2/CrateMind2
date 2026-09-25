import { useEffect, useRef, useState } from "react";
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
  const seedQueryRef = useRef("");

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
