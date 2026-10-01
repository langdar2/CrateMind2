import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { getStats, getFailedTracks, retryFailedTracks, getRecentTracks } from "../api.js";
import { useInterval } from "../hooks.js";

const PAGE_SIZE = 50;
const POLL_MS = 3000;
const TICKER_MS = 2500;

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [failedTracks, setFailedTracks] = useState([]);
  const [failedTotal, setFailedTotal] = useState(0);
  const [failedError, setFailedError] = useState(null);
  const [retrying, setRetrying] = useState(false);
  const [recentTracks, setRecentTracks] = useState([]);
  const [tickerIndex, setTickerIndex] = useState(0);

  useEffect(() => {
    getStats().then(setStats).catch((e) => setError(e.message));
    getRecentTracks(8).then((r) => setRecentTracks(r.tracks)).catch(() => {});
  }, []);

  const pending = stats ? stats.status_counts.pending || 0 : undefined;
  useInterval(
    () => {
      getStats().then(setStats).catch(() => {});
    },
    pending === undefined || pending > 0 ? POLL_MS : null
  );

  // ponytail: reuse the same poll cadence to refresh "recently analyzed" tracks,
  // then cycle through them locally for the ticker animation - no websocket needed.
  useInterval(() => {
    getRecentTracks(8).then((r) => setRecentTracks(r.tracks)).catch(() => {});
  }, POLL_MS);

  useInterval(
    () => setTickerIndex((i) => (i + 1) % recentTracks.length),
    recentTracks.length > 1 ? TICKER_MS : null
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

  const handleRetryFailed = async () => {
    setRetrying(true);
    setFailedError(null);
    try {
      await retryFailedTracks();
      loadFailed(query, 0, false);
      getStats().then(setStats).catch(() => {});
    } catch (e) {
      setFailedError(e.message);
    } finally {
      setRetrying(false);
    }
  };

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
  const tickerTrack = recentTracks.length > 0 ? recentTracks[tickerIndex % recentTracks.length] : null;

  return (
    <div className="tile-grid">
      <div className="tile">
        <h3 onClick={() => setExpanded(!expanded)} style={{ cursor: "pointer" }}>
          Analyse-Fortschritt {expanded ? "▾" : "▸"}
        </h3>
        <div className="progress-bar">
          <div className="progress-bar-fill" style={{ width: `${progressPct}%` }} />
        </div>
        {tickerTrack && (
          <div className="ticker" key={tickerTrack.path}>
            <span className="ticker-path">{tickerTrack.path.split("/").pop()}</span>
            <span className="chips">
              <span className="chip">{tickerTrack.bpm ? tickerTrack.bpm.toFixed(0) : "?"} BPM</span>
              <span className="chip">{tickerTrack.key}</span>
              {tickerTrack.danceability != null && (
                <span className="chip">Dance {tickerTrack.danceability.toFixed(2)}</span>
              )}
              {tickerTrack.mood_happy != null && (
                <span className="chip">Happy {tickerTrack.mood_happy.toFixed(2)}</span>
              )}
            </span>
          </div>
        )}
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
            <button
              className="btn-primary"
              onClick={handleRetryFailed}
              disabled={retrying || !(counts.failed > 0)}
              style={{ marginLeft: "8px" }}
            >
              {retrying ? "Wird gestartet..." : "Analyse für fehlende Tracks starten"}
            </button>
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
            <XAxis dataKey="bucket" stroke="#9999cc" />
            <YAxis stroke="#9999cc" />
            <Tooltip contentStyle={{ background: "#000000", border: "2px solid #ff9966" }} />
            <Bar dataKey="count" fill="#ff9966" radius={[0, 0, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="tile">
        <h3>Key-Verteilung</h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={keyData}>
            <XAxis dataKey="key" hide />
            <YAxis stroke="#9999cc" />
            <Tooltip contentStyle={{ background: "#000000", border: "2px solid #ff9966" }} />
            <Bar dataKey="count" fill="#99ccff" radius={[0, 0, 0, 0]} />
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
