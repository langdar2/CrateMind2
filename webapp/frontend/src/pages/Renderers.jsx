import { useEffect, useState } from "react";
import { getRenderers, getPlaybackStatus } from "../api.js";

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

  if (error) return <p className="error">Fehler: {error}</p>;

  return (
    <div className="tile-grid">
      {renderers.map((r) => (
        <div className="tile" key={r.id}>
          <h3>{r.friendly_name}</h3>
          <p>{r.protocol}</p>
          <button onClick={() => checkStatus(r.id)}>Status abfragen</button>
          {status[r.id] && <pre>{JSON.stringify(status[r.id], null, 2)}</pre>}
        </div>
      ))}
    </div>
  );
}
