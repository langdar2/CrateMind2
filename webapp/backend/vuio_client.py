import os

import httpx

VUIO_BASE_URL = os.environ.get("VUIO_BASE_URL", "http://minime-3.local:8080")
VUIO_TOKEN = os.environ.get("VUIO_TOKEN")

PROTOCOL_VERSION = "2026-07-28"


class VuioError(Exception):
    pass


def _call_tool(tool_name: str, arguments: dict):
    headers = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": tool_name,
    }
    if VUIO_TOKEN:
        headers["Authorization"] = f"Bearer {VUIO_TOKEN}"

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
            "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION},
        },
    }

    try:
        response = httpx.post(f"{VUIO_BASE_URL}/mcp", headers=headers, json=body, timeout=10)
        response.raise_for_status()
        response_json = response.json()
    except Exception as exc:
        raise VuioError(f"Failed to reach VuIO server: {exc}") from exc

    if "error" in response_json:
        error = response_json["error"]
        if isinstance(error, dict) and "message" in error:
            raise VuioError(error["message"])
        raise VuioError(str(error))

    result = response_json["result"]
    if "structuredContent" in result:
        return result["structuredContent"]

    import json

    return json.loads(result["content"][0]["text"])


def list_renderers() -> list[dict]:
    result = _call_tool("list_renderers", {})
    if isinstance(result, list):
        return result
    for value in result.values():
        if isinstance(value, list):
            return value
    return []


def find_file_id(query: str) -> int | None:
    result = _call_tool("search_media", {"query": query, "category": "audio", "limit": 1})
    for value in result.values():
        if isinstance(value, list):
            if not value:
                return None
            return value[0]["id"]
    return None


def create_playlist(name: str) -> int:
    result = _call_tool("create_playlist", {"name": name})
    if "id" in result:
        return result["id"]
    return result["playlist_id"]


def add_tracks(playlist_id: int, file_ids: list[int]) -> None:
    _call_tool("add_to_playlist", {"playlist_id": playlist_id, "media_file_ids": file_ids})


def cast_playlist(playlist_id: int, renderer_id: str) -> None:
    _call_tool("cast_playlist_to_renderer", {"playlist_id": playlist_id, "renderer_id": renderer_id})


def get_playback_status(renderer_id: str | None = None) -> dict:
    arguments = {"renderer_id": renderer_id} if renderer_id else {}
    return _call_tool("get_playback_status", arguments)
