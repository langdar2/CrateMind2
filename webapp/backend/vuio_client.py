import json
import os

import httpx

VUIO_BASE_URL = os.environ.get("VUIO_BASE_URL", "http://localhost:8080")
VUIO_TOKEN = os.environ.get("VUIO_TOKEN")
PROTOCOL_VERSION = "2026-07-28"


class VuioError(Exception):
    pass


def _call_tool(name: str, arguments: dict) -> dict:
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
        response = httpx.post(url, json=body, headers=headers, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as e:
        raise VuioError(f"VuIO unreachable at {url}: {e}") from e

    if "error" in payload:
        raise VuioError(f"VuIO tool '{name}' failed: {payload['error']}")

    try:
        result = payload["result"]
        if "structuredContent" in result:
            return result["structuredContent"]
        return json.loads(result["content"][0]["text"])
    except (KeyError, IndexError, TypeError) as e:
        raise VuioError(f"unexpected response shape from VuIO for tool '{name}': {e}") from e


def list_renderers() -> list:
    return _call_tool("list_renderers", {})["renderers"]


def find_file_id(path: str) -> int:
    filename = path.rsplit("/", 1)[-1]
    # ponytail: one search_media call per track; fine for typical playlist
    # sizes (<100 tracks), batch if that ever becomes the bottleneck.
    results = _call_tool("search_media", {"query": filename, "category": "audio", "limit": 10})
    for f in results["files"]:
        if f["path"] == path:
            return f["id"]
    raise VuioError(f"Track not found in VuIO library: {path}")


def create_playlist(name: str, track_paths: list) -> int:
    created = _call_tool("create_playlist", {"name": name})
    playlist_id = created["playlist_id"]
    file_ids = [find_file_id(path) for path in track_paths]
    _call_tool("add_to_playlist", {"playlist_id": playlist_id, "media_file_ids": file_ids})
    return playlist_id


def cast_playlist(playlist_id: int, renderer_id: str) -> dict:
    return _call_tool("cast_playlist_to_renderer", {"playlist_id": playlist_id, "renderer_id": renderer_id})


def get_playback_status(renderer_id: str = None) -> dict:
    arguments = {"renderer_id": renderer_id} if renderer_id else {}
    return _call_tool("get_playback_status", arguments)
