import { useState } from "react";
import { useInterval } from "../hooks.js";
import { getStats, getNowPlaying } from "../api.js";

const POLL_MS = 3000;

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
    getNowPlaying()
      .then(({ playing }) => setActiveRenderer(playing))
      .catch(() => {});
  }, POLL_MS);

  if (!analyzing && !activeRenderer) return null;

  return (
    <div className="status-bar">
      <span>
        {activeRenderer ? `${activeRenderer.title || "Wiedergabe"} → ${activeRenderer.renderer}` : ""}
      </span>
      <span>
        {analyzing && <span className="status-accent">Analyse: {progress}%</span>}
      </span>
    </div>
  );
}
