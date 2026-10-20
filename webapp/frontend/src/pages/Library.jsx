import { useEffect, useMemo, useRef, useState } from "react";
import {
  getCategories, getLibraryTracks, searchLibrary, browseFolder, getVuioPlaylists,
  getVuioPlaylistTracks, getRenderers, castMedia, coverUrl, groupCoverUrl,
} from "../api.js";
import Busy from "../components/Busy.jsx";
import { usePlayer, formatTime } from "../components/Player.jsx";

const TABS = [
  { key: "artist", label: "Künstler" },
  { key: "album_artist", label: "Album-Künstler" },
  { key: "album", label: "Alben" },
  { key: "genre", label: "Genres" },
  { key: "playlist", label: "Playlists" },
  { key: "folder", label: "Ordner" },
];

const PROTOCOLS = { airplay: "AirPlay", chromecast: "Chromecast", dlna: "DLNA" };

// "Evo One · AirPlay": devices often share a name across protocols, so the
// protocol is what tells them apart (and the model, when two still collide).
function rendererLabel(r, all) {
  const name = r.friendly_name || r.name || r.id;
  const protocol = PROTOCOLS[r.protocol] || r.protocol;
  const label = protocol ? `${name} · ${protocol}` : name;
  const clash = all.some((o) => o !== r && (o.friendly_name || o.name) === (r.friendly_name || r.name)
    && o.protocol === r.protocol);
  return clash && r.model ? `${label} (${r.model})` : label;
}

const PALETTE = ["#ff9966", "#ffcc66", "#cc99cc", "#6699cc", "#9999cc", "#ffcc99"];
const colourFor = (name) => PALETTE[[...name].reduce((n, c) => n + c.charCodeAt(0), 0) % PALETTE.length];

function Cover({ id, src, name, className = "" }) {
  const [failed, setFailed] = useState(false);
  const url = src || (id ? coverUrl(id) : null);
  useEffect(() => setFailed(false), [url]);
  if (url && !failed) {
    return <img className={`cover ${className}`} src={url} alt="" loading="lazy" onError={() => setFailed(true)} />;
  }
  return (
    <div className={`cover cover-fallback ${className}`} style={{ background: colourFor(name || "?") }}>
      {(name || "?").trim().charAt(0).toUpperCase()}
    </div>
  );
}

function TrackList({ tracks, renderers, rendererId, onCastError, heading }) {
  const player = usePlayer();
  const [castingId, setCastingId] = useState(null);
  const [castNote, setCastNote] = useState(null);

  const cast = async (track) => {
    setCastingId(track.id);
    setCastNote(null);
    try {
      await castMedia(track.id, rendererId);
      const device = renderers.find((r) => r.id === rendererId);
      setCastNote(`„${track.title}" läuft auf ${device ? rendererLabel(device, renderers) : "dem Gerät"}`);
    } catch (e) {
      onCastError(e.message);
    } finally {
      setCastingId(null);
    }
  };

  if (!tracks.length) return <p>Keine Titel gefunden.</p>;
  return (
    <div>
      <div className="library-actions">
        <button className="btn-primary" onClick={() => player.playQueue(tracks, 0)}>▶ Alle abspielen</button>
        <button onClick={() => player.playQueue([...tracks].sort(() => Math.random() - 0.5), 0)}>🔀 Zufällig</button>
        <button onClick={() => player.enqueue(tracks)}>＋ Warteschlange</button>
        <span className="library-count">{heading ?? `${tracks.length} Titel`}</span>
      </div>
      {castNote && <p className="library-note">{castNote}</p>}
      <ul className="track-list">
        {tracks.map((t, i) => (
          <li key={t.id} className={player.current?.id === t.id ? "track-row is-current" : "track-row"}>
            <button className="track-main" onClick={() => player.playQueue(tracks, i)}>
              <Cover id={t.id} name={t.album || t.title} className="cover-sm" />
              <span className="track-text">
                <span className="track-title">{t.title}</span>
                <span className="track-sub">
                  {[t.artist, t.album].filter(Boolean).join(" · ")}
                  {t.album_artist && t.album_artist !== t.artist && (
                    <span className="track-albumartist"> · Album von {t.album_artist}</span>
                  )}
                </span>
              </span>
              <span className="track-time">{t.duration ? formatTime(t.duration) : ""}</span>
            </button>
            {rendererId && (
              <button className="track-cast" title="Auf dem gewählten Gerät abspielen"
                      disabled={castingId === t.id} onClick={() => cast(t)}>📡</button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Who the albums in a list belong to, when that is not obvious from the heading (a compilation, a featured artist).
function albumArtists(tracks) {
  const names = [...new Set((tracks || []).map((t) => t.album_artist).filter(Boolean))];
  return names.length > 0 && names.length <= 3 ? names : [];
}

export default function Library() {
  const [tab, setTab] = useState("artist");
  const [stack, setStack] = useState([]); // drill-down: [{title, load}]
  const [items, setItems] = useState(null);
  const [tracks, setTracks] = useState(null);
  const [folder, setFolder] = useState(null);
  const [roots, setRoots] = useState([]); // library roots: going up from one returns to the list of roots
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState(null);
  const [renderers, setRenderers] = useState([]);
  const [rendererId, setRendererId] = useState(() => localStorage.getItem("cratemind:renderer") || "");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const loadId = useRef(0);

  const run = async (fn) => {
    const id = ++loadId.current;
    setBusy(true);
    setError(null);
    try {
      const result = await fn();
      if (id === loadId.current) return result;
    } catch (e) {
      if (id === loadId.current) setError(e.message);
    } finally {
      if (id === loadId.current) setBusy(false);
    }
    return undefined;
  };

  useEffect(() => {
    getRenderers().then((r) => setRenderers(r.renderers || [])).catch(() => {});
  }, []);

  // Top level of a tab.
  useEffect(() => {
    setStack([]);
    setTracks(null);
    setItems(null);
    setFolder(null);
    setFilter("");
    setSearchResult(null);
    setQuery("");
    run(async () => {
      if (tab === "playlist") {
        const r = await getVuioPlaylists();
        setItems(r.playlists.map((p) => ({ name: p.name, count: p.track_count, id: p.id, sub: p.description })));
      } else if (tab === "folder") {
        const top = await browseFolder(null);
        setRoots(top.folders.map((f) => f.path));
        setFolder(top);
      } else {
        const r = await getCategories(tab);
        setItems(r.items);
      }
    });
  }, [tab]);

  // Debounced search.
  useEffect(() => {
    if (query.trim().length < 2) {
      setSearchResult(null);
      return;
    }
    const t = setTimeout(() => run(async () => setSearchResult((await searchLibrary(query)).tracks)), 350);
    return () => clearTimeout(t);
  }, [query]);

  const open = (item) => {
    const title = item.name;
    const load =
      tab === "playlist" ? () => getVuioPlaylistTracks(item.id)
      : tab === "artist" ? () => getLibraryTracks({ artist: item.name })
      : tab === "album_artist" ? () => getLibraryTracks({ album_artist: item.name })
      : tab === "album" ? () => getLibraryTracks({ album: item.name })
      : () => getLibraryTracks({ genre: item.name });
    setStack([{ title }]);
    setTracks(null);
    run(async () => setTracks((await load()).tracks));
  };

  const openFolder = (path, offset = 0) =>
    run(async () => {
      const page = await browseFolder(path, offset);
      setFolder(offset ? { ...page, folders: folder.folders, tracks: [...folder.tracks, ...page.tracks] } : page);
    });

  const back = () => {
    setStack([]);
    setTracks(null);
  };

  const chooseRenderer = (id) => {
    setRendererId(id);
    localStorage.setItem("cratemind:renderer", id);
  };

  const shown = useMemo(() => {
    if (!items) return [];
    const f = filter.trim().toLowerCase();
    return f ? items.filter((i) => i.name.toLowerCase().includes(f)) : items;
  }, [items, filter]);

  const trackProps = { renderers, rendererId, onCastError: setError };
  const inDetail = stack.length > 0;

  return (
    <div className="library">
      <div className="tile">
        <h3>Bibliothek</h3>
        <input type="text" className="library-search" placeholder="Titel, Künstler, Album suchen…"
               value={query} onChange={(e) => setQuery(e.target.value)} />
        {renderers.length > 0 && (
          <div className="library-renderer">
            <span className="label">Gerät</span>
            <select value={rendererId} onChange={(e) => chooseRenderer(e.target.value)}>
              <option value="">Nur in diesem Browser</option>
              {[...renderers]
                .sort((a, b) => rendererLabel(a, renderers).localeCompare(rendererLabel(b, renderers), "de"))
                .map((r) => <option key={r.id} value={r.id}>{rendererLabel(r, renderers)}</option>)}
            </select>
          </div>
        )}
        {!searchResult && (
          <div className="library-tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t.key} role="tab" aria-selected={tab === t.key}
                      className={tab === t.key ? "is-active" : ""} onClick={() => setTab(t.key)}>
                {t.label}
              </button>
            ))}
          </div>
        )}
        <Busy active={busy} hint="Frage die Bibliothek ab" />
        {error && <p className="error">Fehler: {error}</p>}
      </div>

      {searchResult ? (
        <div className="tile"><h3>Treffer</h3><TrackList tracks={searchResult} {...trackProps} /></div>
      ) : inDetail ? (
        <div className="tile">
          <div className="library-detail-head">
            <button className="library-back" onClick={back}>← {TABS.find((t) => t.key === tab).label}</button>
            <h3>{stack[0].title}</h3>
            {tab !== "album_artist" && albumArtists(tracks).map((n) => (
              <span key={n} className="chip chip-new">Album-Künstler: {n}</span>
            ))}
          </div>
          {tracks ? <TrackList tracks={tracks} {...trackProps} /> : !busy && null}
        </div>
      ) : tab === "folder" ? (
        <div className="tile">
          {folder && (
            <>
              <p className="library-path">{folder.path || "Medienordner"}</p>
              <ul className="folder-list">
                {folder.path && (
                  <li><button onClick={() => openFolder(roots.includes(folder.path) || !folder.parent ? null : folder.parent)}>↰ Eine Ebene hoch</button></li>
                )}
                {folder.folders.map((f) => (
                  <li key={f.path}>
                    <button onClick={() => openFolder(f.path)}>
                      📁 {f.name}{f.count != null && <span className="folder-count"> · {f.count}</span>}
                    </button>
                  </li>
                ))}
              </ul>
              {folder.tracks.length > 0 && <TrackList tracks={folder.tracks} {...trackProps} />}
              {folder.next_offset != null && (
                <button onClick={() => openFolder(folder.path, folder.next_offset)}>Mehr laden</button>
              )}
            </>
          )}
        </div>
      ) : (
        <div className="tile">
          {items && items.length > 12 && (
            <input type="text" placeholder="Liste filtern…" value={filter} onChange={(e) => setFilter(e.target.value)} />
          )}
          {items && shown.length === 0 && <p>Nichts gefunden.</p>}
          <ul className={tab === "album" || tab === "playlist" ? "grid-list grid-albums" : "grid-list"}>
            {shown.map((item) => (
              <li key={item.id ?? item.name}>
                <button className="grid-item" onClick={() => open(item)}>
                  <Cover name={item.name}
                         src={tab === "album" ? groupCoverUrl({ album: item.name })
                           : tab === "artist" ? groupCoverUrl({ artist: item.name })
                           : tab === "album_artist" ? groupCoverUrl({ album_artist: item.name }) : null} />
                  <span className="grid-name">{item.name}</span>
                  {item.count != null && <span className="grid-count">{item.count} Titel</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
