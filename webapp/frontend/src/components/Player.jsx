import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { coverUrl, streamUrl } from "../api.js";

const PlayerContext = createContext(null);
export const usePlayer = () => useContext(PlayerContext);

export function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// One <audio> element for the whole app, so the music keeps playing while you
// move between pages, and the lock screen / headphone buttons work on a phone.
export function PlayerProvider({ children }) {
  const audioRef = useRef(null);
  const [queue, setQueue] = useState([]);
  const [index, setIndex] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState({ position: 0, duration: 0 });
  const [error, setError] = useState(null);

  const current = index >= 0 ? queue[index] : null;

  const playQueue = useCallback((tracks, start = 0) => {
    setError(null);
    setQueue(tracks);
    setIndex(start);
  }, []);

  const enqueue = useCallback((tracks) => {
    setQueue((q) => {
      if (q.length === 0) setIndex(0);
      return [...q, ...tracks];
    });
  }, []);

  const next = useCallback(() => setIndex((i) => (i + 1 < queue.length ? i + 1 : i)), [queue.length]);
  const previous = useCallback(() => {
    const audio = audioRef.current;
    if (audio && audio.currentTime > 3) audio.currentTime = 0;
    else setIndex((i) => Math.max(0, i - 1));
  }, []);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !current) return;
    if (audio.paused) audio.play().catch((e) => setError(e.message));
    else audio.pause();
  }, [current]);

  const seek = useCallback((seconds) => {
    if (audioRef.current) audioRef.current.currentTime = seconds;
  }, []);

  const stop = useCallback(() => {
    audioRef.current?.pause();
    setQueue([]);
    setIndex(-1);
    setTime({ position: 0, duration: 0 });
  }, []);

  // Load and start whenever the current track changes.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !current) {
      if (audio) audio.removeAttribute("src");
      return;
    }
    audio.src = streamUrl(current.id);
    audio.play().catch((e) => {
      // Browsers refuse autoplay without a gesture; the player bar's button then starts it.
      if (e.name !== "AbortError") setError(e.message);
    });
  }, [current?.id, index]);

  // Lock screen / notification controls on phones.
  useEffect(() => {
    if (!("mediaSession" in navigator) || !current) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: current.title || "",
      artist: current.artist || "",
      album: current.album || "",
      artwork: [{ src: new URL(coverUrl(current.id), window.location.href).href }],
    });
    navigator.mediaSession.setActionHandler("play", toggle);
    navigator.mediaSession.setActionHandler("pause", toggle);
    navigator.mediaSession.setActionHandler("nexttrack", next);
    navigator.mediaSession.setActionHandler("previoustrack", previous);
    navigator.mediaSession.setActionHandler("seekto", (d) => d.seekTime != null && seek(d.seekTime));
  }, [current, toggle, next, previous, seek]);

  const value = useMemo(
    () => ({ queue, index, current, playing, time, error, playQueue, enqueue, next, previous, toggle, seek, stop }),
    [queue, index, current, playing, time, error, playQueue, enqueue, next, previous, toggle, seek, stop]
  );

  return (
    <PlayerContext.Provider value={value}>
      {children}
      <audio
        ref={audioRef}
        preload="auto"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => (index + 1 < queue.length ? setIndex(index + 1) : setPlaying(false))}
        onTimeUpdate={(e) => setTime({ position: e.target.currentTime, duration: e.target.duration })}
        onError={() => current && setError(`„${current.title}" lässt sich nicht abspielen`)}
      />
    </PlayerContext.Provider>
  );
}

export default function PlayerBar() {
  const p = usePlayer();
  const [coverFailed, setCoverFailed] = useState(null);
  if (!p.current) return null;
  const { current, time } = p;
  const duration = Number.isFinite(time.duration) ? time.duration : current.duration || 0;
  const hasCover = coverFailed !== current.id;

  return (
    <>
    <div className="player-spacer" />
    <div className="player-bar">
      <div className="player-cover">
        {hasCover ? (
          <img src={coverUrl(current.id)} alt="" onError={() => setCoverFailed(current.id)} />
        ) : (
          <span>♪</span>
        )}
      </div>
      <div className="player-meta">
        <div className="player-title">{current.title}</div>
        <div className="player-sub">{p.error || [current.artist, current.album].filter(Boolean).join(" · ")}</div>
      </div>
      <div className="player-controls">
        <button aria-label="Zurück" onClick={p.previous}>⏮</button>
        <button className="btn-primary player-play" aria-label={p.playing ? "Pause" : "Wiedergabe"} onClick={p.toggle}>
          {p.playing ? "⏸" : "▶"}
        </button>
        <button aria-label="Weiter" onClick={p.next} disabled={p.index + 1 >= p.queue.length}>⏭</button>
      </div>
      <div className="player-seek">
        <span>{formatTime(time.position)}</span>
        <input
          type="range" min="0" max={duration || 0} step="1"
          value={Math.min(time.position, duration || 0)}
          onChange={(e) => p.seek(+e.target.value)}
          aria-label="Position"
        />
        <span>{formatTime(duration)}</span>
      </div>
      <button className="player-close" aria-label="Schließen" onClick={p.stop}>✕</button>
    </div>
    </>
  );
}
