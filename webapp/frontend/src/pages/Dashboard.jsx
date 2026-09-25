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
