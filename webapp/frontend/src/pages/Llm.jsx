import { useEffect, useState } from "react";
import { getLlmConfig, saveLlmConfig, testLlm } from "../api.js";
import Busy from "../components/Busy.jsx";

export default function Llm() {
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [keyHint, setKeyHint] = useState("");
  const [models, setModels] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getLlmConfig()
      .then((c) => {
        setBaseUrl(c.base_url);
        setModel(c.model);
        setKeyHint(c.has_key ? c.key_hint : "");
        setLoaded(true);
      })
      .catch((e) => setError(e.message));
  }, []);

  const test = async () => {
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      const r = await testLlm({ base_url: baseUrl, model, api_key: apiKey || null });
      setModels(r.models);
      setResult(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setError(null);
    setSaved(false);
    try {
      const c = await saveLlmConfig({ base_url: baseUrl, model, api_key: apiKey || null });
      setKeyHint(c.has_key ? c.key_hint : "");
      setApiKey("");
      setSaved(true);
    } catch (e) {
      setError(e.message);
    }
  };

  if (!loaded && !error) return <p>Lade Konfiguration...</p>;

  const options = models.includes(model) || !model ? models : [model, ...models];

  return (
    <div>
      <div className="tile">
        <h3>Lokales LLM (oMLX)</h3>
        <p>
          Das Modell schreibt Namen und Beschreibungen, übersetzt Prompts in Filter
          und bewertet Titel. Änderungen gelten sofort, ohne Neustart.
        </p>

        <ul className="field-list" style={{ marginTop: "10px" }}>
          <li className="field">
            <span className="label">Server</span>
            <input type="text" value={baseUrl} placeholder="http://192.168.0.3:8001"
                   onChange={(e) => { setBaseUrl(e.target.value); setSaved(false); }} />
          </li>
          <li className="field">
            <span className="label">API-Key</span>
            <input type="password" value={apiKey} autoComplete="off"
                   placeholder={keyHint ? `gespeichert: ${keyHint}` : "kein Key gespeichert"}
                   onChange={(e) => { setApiKey(e.target.value); setSaved(false); }} />
          </li>
          <li className="field">
            <span className="label">Modell</span>
            {options.length > 0 ? (
              <select value={model} onChange={(e) => { setModel(e.target.value); setSaved(false); }}>
                {options.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : (
              <input type="text" value={model}
                     onChange={(e) => { setModel(e.target.value); setSaved(false); }} />
            )}
          </li>
        </ul>

        <div style={{ display: "flex", gap: "8px", marginTop: "10px", flexWrap: "wrap" }}>
          <button disabled={busy} onClick={test}>
            {busy ? "Teste..." : "Verbindung testen"}
          </button>
          <button className="btn-primary" disabled={busy || !baseUrl || !model} onClick={save}>
            Speichern
          </button>
        </div>
        <Busy active={busy} hint="Frage Server und Modell an – der erste Aufruf lädt das Modell" />

        {saved && <p>Gespeichert.</p>}
        {error && <p className="error">Fehler: {error}</p>}
        {result && result.ok && (
          <p>
            Verbindung steht, {result.models.length} Modelle gefunden.
            {result.answer !== null && <> Das Modell antwortet: „{result.answer}“</>}
          </p>
        )}
        {result && !result.ok && <p className="error">Test fehlgeschlagen: {result.error}</p>}
      </div>
    </div>
  );
}
