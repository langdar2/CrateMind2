const BASE = "/api";

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const getStats = () => request("/stats");
export const getPresets = () => request("/presets");
export const searchTracks = (q) => request(`/tracks?q=${encodeURIComponent(q)}&limit=10`);
export const previewPlaylist = (body) =>
  request("/playlists/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const createPlaylist = (body) =>
  request("/playlists", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const getRenderers = () => request("/renderers");
export const castPlaylist = (playlistId, rendererId) =>
  request(`/playlists/${playlistId}/cast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ renderer_id: rendererId }),
  });
export const getPlaybackStatus = (rendererId) =>
  request(`/playback-status${rendererId ? `?renderer_id=${encodeURIComponent(rendererId)}` : ""}`);
