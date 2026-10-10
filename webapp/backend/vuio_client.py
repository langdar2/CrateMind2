import json
import os
from concurrent.futures import ThreadPoolExecutor

import httpx

VUIO_BASE_URL = os.environ.get("VUIO_BASE_URL", "http://localhost:8080")
VUIO_TOKEN = os.environ.get("VUIO_TOKEN")
PROTOCOL_VERSION = "2026-07-28"
# Per-renderer playback probe. Live renderers reply in milliseconds, so this
# only ever cuts short the ones that will never answer.
PLAYBACK_PROBE_TIMEOUT = 2.0

# Paths are stored in our DB using the analysis container's mount (MUSIC_DIR,
# e.g. /music), but VUIO indexes the same files under their real host path.
# ponytail: single prefix swap; switch to a real path-mapping table if VUIO
# ever sees multiple music roots.
MUSIC_DIR = os.environ.get("MUSIC_DIR", "/music")
VUIO_MUSIC_DIR = os.environ.get("VUIO_MUSIC_DIR", MUSIC_DIR)


def to_vuio_path(path: str) -> str:
    if VUIO_MUSIC_DIR != MUSIC_DIR and path.startswith(MUSIC_DIR + "/"):
        return VUIO_MUSIC_DIR + path[len(MUSIC_DIR):]
    return path


class VuioError(Exception):
    pass


def _call_tool(name: str, arguments: dict, timeout: float = 10.0) -> dict:
    url = f"{VUIO_BASE_URL}/mcp"
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
            "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": name,
    }
    if VUIO_TOKEN:
        headers["Authorization"] = f"Bearer {VUIO_TOKEN}"

    try:
        response = httpx.post(url, json=body, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as e:
        raise VuioError(f"VuIO unreachable at {url}: {e}") from e
    except json.JSONDecodeError as e:
        raise VuioError(f"VuIO returned a non-JSON response from {url}: {e}") from e

    if "error" in payload:
        raise VuioError(f"VuIO tool '{name}' failed: {payload['error']}")

    try:
        result = payload["result"]
        if "structuredContent" in result:
            return result["structuredContent"]
        text = result["content"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        raise VuioError(f"unexpected response shape from VuIO for tool '{name}': {e}") from e

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # VUIO reports some failures (a missing playlist, say) as plain prose
        # in a perfectly successful JSON-RPC envelope. Surface its wording
        # instead of letting the decode blow up as a 500.
        raise VuioError(f"VuIO tool '{name}' failed: {text.strip()[:200]}") from None


def list_renderers() -> list:
    result = _call_tool("list_renderers", {})
    try:
        return result["renderers"]
    except (KeyError, TypeError) as e:
        raise VuioError(f"unexpected response shape from VuIO for tool 'list_renderers': {e}") from e


def find_file_id(path: str) -> int:
    vuio_path = to_vuio_path(path)
    filename = vuio_path.rsplit("/", 1)[-1]
    # ponytail: one search_media call per track; fine for typical playlist
    # sizes (<100 tracks), batch if that ever becomes the bottleneck.
    results = _call_tool("search_media", {"query": filename, "category": "audio", "limit": 10})
    try:
        files = results["files"]
        for f in files:
            if f["path"] == vuio_path:
                return f["id"]
    except (KeyError, TypeError) as e:
        raise VuioError(f"unexpected response shape from VuIO for tool 'search_media': {e}") from e
    raise VuioError(f"Track not found in VuIO library: {vuio_path}")


def list_playlists() -> list:
    result = _call_tool("list_playlists", {})
    try:
        return result["playlists"]
    except (KeyError, TypeError) as e:
        raise VuioError(f"unexpected response shape from VuIO for tool 'list_playlists': {e}") from e


def create_playlist(name: str, track_paths: list, description: str = None) -> int:
    arguments = {"name": name}
    if description:
        arguments["description"] = description
    created = _call_tool("create_playlist", arguments)
    try:
        playlist_id = created["playlist_id"]
    except (KeyError, TypeError) as e:
        raise VuioError(f"unexpected response shape from VuIO for tool 'create_playlist': {e}") from e
    file_ids = [find_file_id(path) for path in track_paths]
    _call_tool("add_to_playlist", {"playlist_id": playlist_id, "media_file_ids": file_ids})
    return playlist_id


def from_vuio_path(vuio_path: str) -> str:
    """Inverse of to_vuio_path: VUIO's host path back to the one our DB uses."""
    if VUIO_MUSIC_DIR != MUSIC_DIR and vuio_path.startswith(VUIO_MUSIC_DIR + "/"):
        return MUSIC_DIR + vuio_path[len(VUIO_MUSIC_DIR):]
    return vuio_path


def path_for_media_id(media_id: int) -> str:
    """Our DB path for a VUIO media id, or None if it maps to nothing."""
    info = _call_tool("get_media_info", {"file_id": media_id})
    path = info.get("path") if isinstance(info, dict) else None
    return from_vuio_path(path) if path else None


def replace_playlist_tracks(playlist_id: int, track_paths: list) -> int:
    """Swap a playlist's contents, keeping the playlist itself.

    Renderers and DLNA clients hold on to the playlist id, so refilling it
    beats deleting and recreating. Resolve the new tracks first: if one of
    them is missing from VUIO we fail before the old contents are gone.
    """
    file_ids = [find_file_id(path) for path in track_paths]

    existing = _call_tool("get_playlist_tracks", {"playlist_id": playlist_id})
    try:
        old_ids = [t["id"] for t in existing["tracks"]]
    except (KeyError, TypeError) as e:
        raise VuioError(f"unexpected response shape from VuIO for tool 'get_playlist_tracks': {e}") from e

    # ponytail: VUIO removes one track per call; fine for playlist-sized lists.
    for media_file_id in old_ids:
        _call_tool("remove_from_playlist", {"playlist_id": playlist_id, "media_file_id": media_file_id})
    if file_ids:
        _call_tool("add_to_playlist", {"playlist_id": playlist_id, "media_file_ids": file_ids})
    return len(file_ids)


def cast_playlist(playlist_id: int, renderer_id: str) -> dict:
    return _call_tool("cast_playlist_to_renderer", {"playlist_id": playlist_id, "renderer_id": renderer_id})


def get_playback_status(renderer_id: str = None) -> dict:
    arguments = {"renderer_id": renderer_id} if renderer_id else {}
    return _call_tool("get_playback_status", arguments)


def all_playback_status() -> dict:
    """Playback state of every renderer, asked one at a time.

    get_playback_status() with no id only reports casts this server started
    (`last_sent_by_this_server`), so anything begun from another app shows up
    as an empty list - the fan-out is the only way to see it. Probing the
    renderers serially takes ~10s because unreachable ones sit out their
    timeout, hence the threads.
    """
    try:
        renderers = list_renderers()
    except VuioError:
        return {"renderers": []}

    def probe(renderer):
        try:
            # A renderer that is up answers in well under 100ms; one that is
            # merely advertised (a Chromecast that is off, say) never answers
            # at all and would otherwise hold the whole poll for 10s.
            status = _call_tool("get_playback_status", {"renderer_id": renderer["id"]},
                                timeout=PLAYBACK_PROBE_TIMEOUT)
            return status.get("renderers") or []
        except VuioError:
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        groups = pool.map(probe, renderers)
    return {"renderers": [entry for group in groups for entry in group]}
