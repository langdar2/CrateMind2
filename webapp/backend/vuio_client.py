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


def list_roots() -> list:
    result = _call_tool("list_library_roots", {})
    try:
        return result["roots"]
    except (KeyError, TypeError) as e:
        raise VuioError(f"unexpected response shape from VuIO for tool 'list_library_roots': {e}") from e


def browse_folder(path: str, offset: int = 0, limit: int = 200) -> dict:
    return _call_tool("browse_folder", {"path": path, "category": "audio", "offset": offset, "limit": limit})


def list_categories(kind: str, artist: str = None, genre: str = None) -> list:
    """[{name, count}] for artists, albums, genres or years, from VuIO's index."""
    arguments = {"kind": kind}
    if artist:
        arguments["artist"] = artist
    if genre:
        arguments["genre"] = genre
    result = _call_tool("list_music_categories", arguments)
    # The exact envelope is VuIO's to choose: take the first list in it, and
    # accept the usual spellings for the name and the count.
    items = result if isinstance(result, list) else next(
        (v for v in result.values() if isinstance(v, list)), []) if isinstance(result, dict) else []
    out = []
    for item in items:
        if isinstance(item, str):
            out.append({"name": item, "count": None})
        elif isinstance(item, dict):
            name = next((item[k] for k in ("name", "value", "label", kind) if item.get(k) not in (None, "")), None)
            count = next((item[k] for k in ("track_count", "count", "tracks") if k in item), None)
            if name is not None:
                out.append({"name": str(name), "count": count})
    return out


def find_music(artist: str = None, album: str = None, album_artist: str = None,
               genre: str = None, year: int = None, limit: int = 500) -> list:
    arguments = {"limit": limit}
    for key, value in (("artist", artist), ("album", album), ("album_artist", album_artist),
                       ("genre", genre), ("year", year)):
        if value not in (None, ""):
            arguments[key] = value
    result = _call_tool("find_music", arguments)
    return _files_of(result)


def search_audio(query: str, limit: int = 50) -> list:
    return _files_of(_call_tool("search_media", {"query": query, "category": "audio", "limit": limit}))


def playlist_tracks(playlist_id: int) -> list:
    return _files_of(_call_tool("get_playlist_tracks", {"playlist_id": playlist_id}))


def _files_of(result) -> list:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("tracks", "files", "results"):
            if isinstance(result.get(key), list):
                return result[key]
    return []


def media_info(file_id: int) -> dict:
    info = _call_tool("get_media_info", {"file_id": file_id})
    if not isinstance(info, dict):
        raise VuioError(f"unexpected response shape from VuIO for tool 'get_media_info'")
    return info


def cast_media(file_id: int, renderer_id: str) -> dict:
    return _call_tool("cast_media_to_renderer", {"file_id": file_id, "renderer_id": renderer_id})


def control_renderer(action: str, renderer_id: str = None) -> dict:
    arguments = {"action": action}
    if renderer_id:
        arguments["renderer_id"] = renderer_id
    return _call_tool("control_renderer", arguments)


def track_summary(file: dict) -> dict:
    """The few fields the browser needs; VuIO's records are large."""
    return {
        "id": file.get("id"),
        "title": file.get("title") or (file.get("filename") or "").rsplit(".", 1)[0],
        "artist": file.get("artist"),
        "album": file.get("album"),
        "album_artist": file.get("album_artist"),
        "track_number": file.get("track_number"),
        "disc_number": file.get("disc_number"),
        "duration": file.get("duration_seconds") or None,
        "year": file.get("year"),
        "genre": file.get("genre"),
        "codec": file.get("codec"),
    }


def media_url(file_id: int, kind: str) -> str:
    """VuIO's own URL for a track's audio ('stream') or artwork ('cover'),
    rebuilt on our configured base so it works whatever address VuIO
    advertises for itself."""
    info = media_info(file_id)
    source = info.get("stream_url" if kind == "stream" else "cover_url")
    if not source:
        raise VuioError(f"no {kind} for media {file_id}")
    path = "/" + source.split("://", 1)[-1].split("/", 1)[-1] if "://" in source else source
    return VUIO_BASE_URL.rstrip("/") + path


PLAY_QUEUE_PREFIX = "CrateMind Wiedergabe"


def play_on_renderer(file_ids: list, renderer_id: str, start: int = 0) -> dict:
    """Play a list of tracks on a device, beginning at position `start`.

    VuIO plays playlists, not ad-hoc lists, so the tracks go into a playlist of
    their own, one per device. It is built before the old one is removed: the
    old one may still be what the device is playing, and a failed cast must
    leave things as they were.
    """
    if not file_ids:
        raise VuioError("nothing to play")
    start = max(0, min(start, len(file_ids) - 1))
    name = f"{PLAY_QUEUE_PREFIX} ({renderer_id})"
    created = _call_tool("create_playlist", {"name": name, "description": "Von CrateMind angelegt, wird beim nächsten Abspielen ersetzt"})
    try:
        playlist_id = created["playlist_id"]
    except (KeyError, TypeError) as e:
        raise VuioError(f"unexpected response shape from VuIO for tool 'create_playlist': {e}") from e
    try:
        _call_tool("add_to_playlist", {"playlist_id": playlist_id, "media_file_ids": file_ids})
        result = _call_tool("cast_playlist_to_renderer",
                            {"playlist_id": playlist_id, "renderer_id": renderer_id, "track_index": start})
    except VuioError:
        _call_tool("delete_playlist", {"playlist_id": playlist_id})
        raise
    for old in list_playlists():
        if old.get("name") == name and old.get("id") != playlist_id:
            try:
                _call_tool("delete_playlist", {"playlist_id": old["id"]})
            except VuioError:
                pass  # a leftover playlist is clutter, not a failure
    return result if isinstance(result, dict) else {}
