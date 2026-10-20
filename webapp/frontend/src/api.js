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
export const getRecentTracks = (limit = 10) => request(`/tracks/recent?limit=${limit}`);
export const getGraphArtists = () => request("/graph/artists");
export const getGraphPlaylist = (artists, limit = 30) =>
  request("/graph/playlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ artists, limit }),
  });
export const getArtistGraph = (artist, limit = 20) =>
  request(`/graph/${encodeURIComponent(artist)}?limit=${limit}`);
export const searchTracks = (q) => request(`/tracks?q=${encodeURIComponent(q)}&limit=10`);
export const getFailedTracks = (q, limit, offset) =>
  request(`/tracks/failed?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`);
export const retryFailedTracks = () => request("/tracks/retry-failed", { method: "POST" });
export const previewWishlist = (text, limit = 50) =>
  request("/playlists/wishlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, limit }),
  });
export const previewPlaylist = (body) =>
  request("/playlists/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const suggestPlaylistName = (trackPaths) =>
  request("/playlists/suggest-name", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ track_paths: trackPaths }),
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
export const getNowPlaying = () => request("/now-playing");
export const getSchedules = () => request("/schedules");
export const getScheduleCandidates = () => request("/schedules/candidates");
export const saveSchedule = (playlistId, body) =>
  request(`/schedules/${playlistId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const deleteSchedule = (playlistId) =>
  request(`/schedules/${playlistId}`, { method: "DELETE" });
export const runSchedule = (playlistId) =>
  request(`/schedules/${playlistId}/run`, { method: "POST" });
export const getPlaybackStatus = (rendererId) =>
  request(`/playback-status${rendererId ? `?renderer_id=${encodeURIComponent(rendererId)}` : ""}`);

export const getLlmConfig = () => request("/llm/config");
export const saveLlmConfig = (body) =>
  request("/llm/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const testLlm = (body) =>
  request("/llm/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

const jsonBody = (body) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const qs = (params) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== "")).toString();

export const getCategories = (kind, params = {}) =>
  request(`/library/categories?${qs({ kind, ...params })}`);
export const getLibraryTracks = (params) => request(`/library/tracks?${qs(params)}`);
export const searchLibrary = (q) => request(`/library/search?${qs({ q })}`);
export const browseFolder = (path, offset = 0) =>
  request(`/library/folders?${qs({ path, offset: offset || null })}`);
export const getVuioPlaylists = () => request("/library/playlists");
export const getVuioPlaylistTracks = (id) => request(`/library/playlists/${id}`);
export const castMedia = (fileId, rendererId) =>
  request("/library/cast", jsonBody({ file_id: fileId, renderer_id: rendererId }));
export const controlRenderer = (action, rendererId) =>
  request("/library/control", jsonBody({ action, renderer_id: rendererId }));
export const coverUrl = (id) => `${BASE}/media/${id}/cover`;
export const streamUrl = (id) => `${BASE}/media/${id}/stream`;
export const groupCoverUrl = (params) => `${BASE}/library/cover?${qs(params)}`;
