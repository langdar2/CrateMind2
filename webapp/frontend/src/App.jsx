import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Playlists from "./pages/Playlists.jsx";
import Renderers from "./pages/Renderers.jsx";

export default function App() {
  return (
    <BrowserRouter>
      <nav className="top-nav">
        <span className="brand">CrateMind</span>
        <NavLink to="/">Dashboard</NavLink>
        <NavLink to="/playlists">Playlists</NavLink>
        <NavLink to="/renderers">Renderer</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/playlists" element={<Playlists />} />
          <Route path="/renderers" element={<Renderers />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
