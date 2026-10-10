import { useEffect, useState } from "react";
import {
  getSchedules,
  getScheduleCandidates,
  saveSchedule,
  deleteSchedule,
  runSchedule,
} from "../api.js";

const WEEKDAYS = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];

function summarise(recipe) {
  if (!recipe) return "kein Rezept";
  const c = recipe.criteria || {};
  const parts = [];
  if (c.min_bpm || c.max_bpm) parts.push(`${c.min_bpm ?? "?"}–${c.max_bpm ?? "?"} BPM`);
  if (c.min_percentile) parts.push(`Top ${100 - c.min_percentile}%`);
  if (c.min_danceability) parts.push(`Dance ≥ ${c.min_danceability}`);
  if (recipe.discovery) parts.push(`${Math.round(recipe.discovery * 100)}% neu`);
  if (recipe.limit) parts.push(`${recipe.limit} Tracks`);
  return parts.join(" · ") || recipe.mode;
}

function formatRun(entry) {
  if (!entry.last_run) return "noch nie gelaufen";
  const when = new Date(entry.last_run * 1000).toLocaleString("de-DE", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
  return `${when} · ${entry.last_result || ""}`;
}

export default function Schedules() {
  const [entries, setEntries] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [newPlaylist, setNewPlaylist] = useState("");
  const [newSlot, setNewSlot] = useState({ weekday: 1, hour: 7, minute: 0 });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = () =>
    Promise.all([getSchedules(), getScheduleCandidates().catch(() => ({ candidates: [] }))])
      .then(([s, c]) => {
        setEntries(s.schedules);
        setCandidates(c.candidates);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const addSchedule = async () => {
    const chosen = candidates.find((c) => String(c.playlist_id) === newPlaylist);
    if (!chosen) return;
    setError(null);
    setBusy("new");
    try {
      await saveSchedule(chosen.playlist_id, { name: chosen.name, ...newSlot, enabled: true });
      setNewPlaylist("");
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const update = async (entry, changes) => {
    setError(null);
    try {
      await saveSchedule(entry.playlist_id, {
        name: entry.name,
        weekday: entry.weekday,
        hour: entry.hour,
        minute: entry.minute,
        enabled: entry.enabled,
        ...changes,
      });
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const act = async (playlistId, fn) => {
    setError(null);
    setBusy(playlistId);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  if (error && !entries) return <p className="error">Fehler: {error}</p>;
  if (!entries) return <p>Lade Zeitpläne...</p>;

  return (
    <div>
      {error && <p className="error">Fehler: {error}</p>}

      <div className="tile">
        <h3>Neuen Mix einplanen</h3>
        {candidates.length === 0 ? (
          <p>
            {entries.length === 0
              ? "Noch keine Playlist mit Rezept vorhanden. Lege im Playlists-Tab eine an - sie merkt sich ihr Rezept und kann danach hier eingeplant werden."
              : "Alle Playlists mit Rezept sind bereits eingeplant."}
          </p>
        ) : (
          <>
            <div className="slider-row" style={{ marginTop: "8px" }}>
              <span className="label">Playlist</span>
              <select
                value={newPlaylist}
                onChange={(e) => setNewPlaylist(e.target.value)}
                style={{ gridColumn: "2 / 4" }}
              >
                <option value="">— auswählen —</option>
                {candidates.map((c) => (
                  <option key={c.playlist_id} value={c.playlist_id}>
                    {c.name} ({c.track_count} Tracks)
                  </option>
                ))}
              </select>
              <span />
            </div>

            <div className="slider-row">
              <span className="label">Wochentag</span>
              <select
                value={newSlot.weekday}
                onChange={(e) => setNewSlot({ ...newSlot, weekday: +e.target.value })}
                style={{ gridColumn: "2 / 4" }}
              >
                {WEEKDAYS.map((day, i) => (
                  <option key={day} value={i}>{day}</option>
                ))}
              </select>
              <span />
            </div>

            <div className="slider-row">
              <span className="label">Uhrzeit</span>
              <input
                type="range" min="0" max="23"
                value={newSlot.hour}
                onChange={(e) => setNewSlot({ ...newSlot, hour: +e.target.value })}
              />
              <input
                type="range" min="0" max="55" step="5"
                value={newSlot.minute}
                onChange={(e) => setNewSlot({ ...newSlot, minute: +e.target.value })}
              />
              <span className="slider-value">
                {String(newSlot.hour).padStart(2, "0")}:{String(newSlot.minute).padStart(2, "0")}
              </span>
            </div>

            <button
              className="btn-primary"
              disabled={!newPlaylist || busy === "new"}
              onClick={addSchedule}
              style={{ marginTop: "10px" }}
            >
              {busy === "new" ? "Wird angelegt..." : "Zeitplan anlegen"}
            </button>
          </>
        )}
      </div>

      {entries.map((entry) => (
        <div className="tile" key={entry.playlist_id}>
          <h3>{entry.name}</h3>

          <div className="chips">
            <span className="chip chip-score">{entry.describes}</span>
            <span className="chip">{summarise(entry.recipe)}</span>
            {!entry.enabled && <span className="chip">pausiert</span>}
          </div>

          <div className="slider-row" style={{ marginTop: "12px" }}>
            <span className="label">Wochentag</span>
            <select
              value={entry.weekday}
              onChange={(e) => update(entry, { weekday: +e.target.value })}
              style={{ gridColumn: "2 / 4" }}
            >
              {WEEKDAYS.map((day, i) => (
                <option key={day} value={i}>{day}</option>
              ))}
            </select>
            <span />
          </div>

          <div className="slider-row">
            <span className="label">Uhrzeit</span>
            <input
              type="range" min="0" max="23"
              value={entry.hour}
              onChange={(e) => update(entry, { hour: +e.target.value })}
            />
            <input
              type="range" min="0" max="55" step="5"
              value={entry.minute - (entry.minute % 5)}
              onChange={(e) => update(entry, { minute: +e.target.value })}
            />
            <span className="slider-value">
              {String(entry.hour).padStart(2, "0")}:{String(entry.minute).padStart(2, "0")}
            </span>
          </div>

          <ul className="field-list" style={{ marginTop: "10px" }}>
            <li className="field">
              <span className="label">Zuletzt</span>
              <span>{formatRun(entry)}</span>
            </li>
            <li className="field">
              <span className="label">Als Nächstes</span>
              <span>{entry.enabled ? entry.next_run.replace("T", " ") : "—"}</span>
            </li>
          </ul>

          <div style={{ display: "flex", gap: "8px", marginTop: "10px", flexWrap: "wrap" }}>
            <button
              className="btn-primary"
              disabled={busy === entry.playlist_id}
              onClick={() => act(entry.playlist_id, () => runSchedule(entry.playlist_id))}
            >
              {busy === entry.playlist_id ? "Läuft..." : "Jetzt neu befüllen"}
            </button>
            <button onClick={() => update(entry, { enabled: !entry.enabled })}>
              {entry.enabled ? "Pausieren" : "Fortsetzen"}
            </button>
            <button
              onClick={() => act(entry.playlist_id, () => deleteSchedule(entry.playlist_id))}
            >
              Zeitplan löschen
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
