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
