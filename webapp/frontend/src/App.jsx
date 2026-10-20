import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Playlists from "./pages/Playlists.jsx";
import Renderers from "./pages/Renderers.jsx";
import Graph from "./pages/Graph.jsx";
import Schedules from "./pages/Schedules.jsx";
import Llm from "./pages/Llm.jsx";
import Library from "./pages/Library.jsx";
import PlayerBar, { PlayerProvider } from "./components/Player.jsx";
import StatusBar from "./components/StatusBar.jsx";

const DashboardIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="3" width="8" height="8" rx="2" />
    <rect x="13" y="3" width="8" height="8" rx="2" />
    <rect x="3" y="13" width="8" height="8" rx="2" />
    <rect x="13" y="13" width="8" height="8" rx="2" />
  </svg>
);

const PlaylistIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="4" y1="6" x2="20" y2="6" />
    <line x1="4" y1="12" x2="20" y2="12" />
    <line x1="4" y1="18" x2="14" y2="18" />
  </svg>
);

const RendererIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="4" y="2" width="16" height="20" rx="2" />
    <circle cx="12" cy="15" r="4" />
    <line x1="12" y1="6" x2="12.01" y2="6" />
  </svg>
);

const GraphIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="5" r="2.5" />
    <circle cx="5" cy="18" r="2.5" />
    <circle cx="19" cy="18" r="2.5" />
    <line x1="12" y1="7.5" x2="5.8" y2="15.7" />
    <line x1="12" y1="7.5" x2="18.2" y2="15.7" />
    <line x1="7.5" y1="18" x2="16.5" y2="18" />
  </svg>
);

const ScheduleIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="9" />
    <polyline points="12 7 12 12 16 14" />
  </svg>
);

const LlmIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="5" y="5" width="14" height="14" rx="2" />
    <rect x="9" y="9" width="6" height="6" />
    <line x1="9" y1="2" x2="9" y2="5" /><line x1="15" y1="2" x2="15" y2="5" />
    <line x1="9" y1="19" x2="9" y2="22" /><line x1="15" y1="19" x2="15" y2="22" />
  </svg>
);

const LibraryIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="3" />
    <line x1="12" y1="3" x2="12" y2="1" />
  </svg>
);

export default function App() {
  return (
    <BrowserRouter>
      <PlayerProvider>
      <div className="app-shell">
        <nav className="sidebar">
          <div className="brand" />
          <NavLink to="/" end title="Dashboard">
            <DashboardIcon />
          </NavLink>
          <NavLink to="/library" title="Bibliothek">
            <LibraryIcon />
          </NavLink>
          <NavLink to="/playlists" title="Playlists">
            <PlaylistIcon />
          </NavLink>
          <NavLink to="/schedules" title="Automatische Mixe">
            <ScheduleIcon />
          </NavLink>
          <NavLink to="/graph" title="Klang-Graph">
            <GraphIcon />
          </NavLink>
          <NavLink to="/llm" title="Lokales LLM">
            <LlmIcon />
          </NavLink>
          <NavLink to="/renderers" title="Renderer">
            <RendererIcon />
          </NavLink>
        </nav>
        <div className="app-main">
          <main>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/library" element={<Library />} />
              <Route path="/playlists" element={<Playlists />} />
              <Route path="/schedules" element={<Schedules />} />
              <Route path="/graph" element={<Graph />} />
              <Route path="/llm" element={<Llm />} />
              <Route path="/renderers" element={<Renderers />} />
            </Routes>
          </main>
          <StatusBar />
        </div>
      </div>
      <PlayerBar />
      </PlayerProvider>
    </BrowserRouter>
  );
}
