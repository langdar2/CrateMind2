import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vuio_client


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._payload


def test_call_tool_parses_structured_content():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"renderers": []}}}
    with patch("vuio_client.httpx.post", return_value=FakeResponse(payload)):
        result = vuio_client._call_tool("list_renderers", {})
    assert result == {"renderers": []}


def test_call_tool_parses_text_content_fallback():
    inner = json.dumps({"playlist_id": 42})
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": inner}]}}
    with patch("vuio_client.httpx.post", return_value=FakeResponse(payload)):
        result = vuio_client._call_tool("create_playlist", {"name": "x"})
    assert result == {"playlist_id": 42}


def test_call_tool_raises_vuio_error_on_jsonrpc_error():
    payload = {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "boom"}}
    with patch("vuio_client.httpx.post", return_value=FakeResponse(payload)):
        try:
            vuio_client._call_tool("list_renderers", {})
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


def test_call_tool_raises_vuio_error_on_malformed_content():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}
    with patch("vuio_client.httpx.post", return_value=FakeResponse(payload)):
        try:
            vuio_client._call_tool("list_renderers", {})
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


def test_create_playlist_creates_then_adds_resolved_file_ids():
    def fake_call_tool(name, arguments):
        if name == "create_playlist":
            return {"playlist_id": 7}
        if name == "search_media":
            return {"files": [{"id": 99, "path": "/music/a.mp3"}]}
        if name == "add_to_playlist":
            assert arguments == {"playlist_id": 7, "media_file_ids": [99]}
            return {"status": "ok"}
        raise AssertionError(f"unexpected tool call: {name}")

    with patch("vuio_client._call_tool", side_effect=fake_call_tool):
        playlist_id = vuio_client.create_playlist("My Playlist", ["/music/a.mp3"])

    assert playlist_id == 7


def test_find_file_id_raises_when_path_not_found():
    with patch("vuio_client._call_tool", return_value={"files": [{"id": 1, "path": "/other.mp3"}]}):
        try:
            vuio_client.find_file_id("/missing.mp3")
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


if __name__ == "__main__":
    test_call_tool_parses_structured_content()
    test_call_tool_parses_text_content_fallback()
    test_call_tool_raises_vuio_error_on_jsonrpc_error()
    test_call_tool_raises_vuio_error_on_malformed_content()
    test_create_playlist_creates_then_adds_resolved_file_ids()
    test_find_file_id_raises_when_path_not_found()
    print("All vuio_client tests passed.")
