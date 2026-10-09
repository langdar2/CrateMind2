import { useEffect, useMemo, useRef, useState } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from "d3-force";
import { getGraphArtists, getArtistGraph } from "../api.js";

const WIDTH = 900;
const HEIGHT = 560;
const NEIGHBOURS = 14;

// Node colour tracks how much the artist is played; grey means the Apple
// export never saw them, which is most of the library.
function colorFor(percentile) {
  if (percentile == null) return "#555577";
  if (percentile >= 90) return "#ff9966";
  if (percentile >= 70) return "#ffcc66";
  if (percentile >= 40) return "#cc99cc";
  return "#6699cc";
}

function radiusFor(trackCount) {
  return 10 + Math.min(22, Math.sqrt(trackCount) * 1.6);
}

export default function Graph() {
  const [artists, setArtists] = useState([]);
  const [current, setCurrent] = useState(null);
  const [data, setData] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [layout, setLayout] = useState({ nodes: [], edges: [] });
  const simRef = useRef(null);

  useEffect(() => {
    getGraphArtists()
      .then((r) => {
        setArtists(r.artists);
        if (r.artists.length) {
          const biggest = [...r.artists].sort((a, b) => b.track_count - a.track_count)[0];
          setCurrent(biggest.id);
        }
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!current) return;
    getArtistGraph(current, NEIGHBOURS).then(setData).catch((e) => setError(e.message));
  }, [current]);

  // Run the force layout off-screen and copy positions into state each tick;
  // d3 owns the physics, React owns the DOM.
  useEffect(() => {
    if (!data) return;
    simRef.current?.stop();

    const nodes = data.nodes.map((n) => ({ ...n }));
    const edges = data.edges.map((e) => ({ ...e }));
    const sim = forceSimulation(nodes)
      .force("link", forceLink(edges).id((d) => d.id)
        // Similar artists sit closer: a 0.9 edge is much shorter than a 0.35 one.
        .distance((d) => 260 - d.weight * 200).strength((d) => d.weight))
      .force("charge", forceManyBody().strength(-700))
      .force("center", forceCenter(WIDTH / 2, HEIGHT / 2))
      .force("collide", forceCollide().radius((d) => radiusFor(d.track_count) + 12))
      .on("tick", () => {
        // Keep everything inside the viewBox - the simulation happily pushes
        // nodes past the top edge, and labels sit below each circle.
        for (const n of nodes) {
          const pad = radiusFor(n.track_count) + 18;
          n.x = Math.max(pad, Math.min(WIDTH - pad, n.x));
          n.y = Math.max(pad, Math.min(HEIGHT - pad, n.y));
        }
        setLayout({ nodes: [...nodes], edges: [...edges] });
      });

    simRef.current = sim;
    return () => sim.stop();
  }, [data]);

  const matches = useMemo(() => {
    if (query.length < 2) return [];
    const q = query.toLowerCase();
    return artists.filter((a) => a.id.includes(q)).slice(0, 8);
  }, [query, artists]);

  if (error) return <p className="error">Fehler: {error}</p>;
  if (!data) return <p>Lade Graph...</p>;

  const centre = data.nodes.find((n) => n.is_center);

  return (
    <div>
      <div className="tile">
        <h3>Klang-Nachbarschaft</h3>
        <input
          type="text"
          placeholder="Künstler suchen..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {matches.length > 0 && (
          <ul>
            {matches.map((a) => (
              <li
                key={a.id}
                className="card-row"
                style={{ cursor: "pointer" }}
                onClick={() => {
                  setCurrent(a.id);
                  setQuery("");
                }}
              >
                <span className="path">{a.label}</span>
                <span className="chips">
                  <span className="chip">{a.track_count} Tracks</span>
                </span>
              </li>
            ))}
          </ul>
        )}
        <div className="graph-legend">
          <span className="chip chip-score">{centre?.label}</span>
          <span className="chip">{centre?.track_count} Tracks</span>
          {centre?.percentile != null && <span className="chip">Top {Math.max(1, 100 - centre.percentile)}%</span>}
          <span className="chip">{data.nodes.length - 1} ähnliche Künstler</span>
        </div>
      </div>

      <div className="tile">
        <svg className="graph-canvas" viewBox={`0 0 ${WIDTH} ${HEIGHT}`}>
          {layout.edges.map((e, i) => (
            <line
              key={i}
              x1={e.source.x} y1={e.source.y}
              x2={e.target.x} y2={e.target.y}
              stroke="#ff9966"
              strokeOpacity={Math.max(0.08, (e.weight - 0.3) * 0.9)}
              strokeWidth={1 + e.weight * 2}
            />
          ))}
          {layout.nodes.map((n) => (
            <g
              key={n.id}
              transform={`translate(${n.x},${n.y})`}
              style={{ cursor: "pointer" }}
              onClick={() => setCurrent(n.id)}
            >
              <circle
                r={radiusFor(n.track_count)}
                fill={colorFor(n.percentile)}
                stroke={n.is_center ? "#99ccff" : "#000"}
                strokeWidth={n.is_center ? 4 : 2}
              />
              <text
                y={radiusFor(n.track_count) + 14}
                textAnchor="middle"
                className="graph-label"
              >
                {n.label}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}
