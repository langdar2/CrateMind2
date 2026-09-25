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
