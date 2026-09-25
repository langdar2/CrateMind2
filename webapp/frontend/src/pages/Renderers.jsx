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
