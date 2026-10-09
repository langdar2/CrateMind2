import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Playlists from "./pages/Playlists.jsx";
import Renderers from "./pages/Renderers.jsx";
import Graph from "./pages/Graph.jsx";
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

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <nav className="sidebar">
          <div className="brand" />
          <NavLink to="/" end title="Dashboard">
            <DashboardIcon />
          </NavLink>
          <NavLink to="/playlists" title="Playlists">
            <PlaylistIcon />
          </NavLink>
          <NavLink to="/graph" title="Klang-Graph">
            <GraphIcon />
          </NavLink>
          <NavLink to="/renderers" title="Renderer">
            <RendererIcon />
          </NavLink>
        </nav>
        <div className="app-main">
          <main>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/playlists" element={<Playlists />} />
              <Route path="/graph" element={<Graph />} />
              <Route path="/renderers" element={<Renderers />} />
            </Routes>
          </main>
          <StatusBar />
        </div>
      </div>
    </BrowserRouter>
  );
}
