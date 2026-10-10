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


def test_call_tool_raises_vuio_error_on_plain_text_content():
    """VUIO answers some failures with prose in a successful envelope; that
    must become a clean error, not a JSONDecodeError escaping as a 500."""
    payload = {"jsonrpc": "2.0", "id": 1,
               "result": {"content": [{"text": "Playlist 3 not found"}]}}
    with patch("vuio_client.httpx.post", return_value=FakeResponse(payload)):
        try:
            vuio_client._call_tool("add_to_playlist", {})
            assert False, "expected VuioError"
        except vuio_client.VuioError as e:
            assert "Playlist 3 not found" in str(e), str(e)


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


def test_call_tool_raises_vuio_error_on_http_failure():
    with patch("vuio_client.httpx.post", return_value=FakeResponse({}, status_code=500)):
        try:
            vuio_client._call_tool("list_renderers", {})
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


def test_call_tool_raises_vuio_error_on_non_json_response():
    class NonJsonResponse(FakeResponse):
        def json(self):
            raise json.JSONDecodeError("Expecting value", "", 0)

    with patch("vuio_client.httpx.post", return_value=NonJsonResponse({})):
        try:
            vuio_client._call_tool("list_renderers", {})
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


def test_list_renderers_raises_vuio_error_on_malformed_response():
    with patch("vuio_client._call_tool", return_value={}):
        try:
            vuio_client.list_renderers()
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


def test_find_file_id_raises_vuio_error_on_malformed_response():
    with patch("vuio_client._call_tool", return_value={}):
        try:
            vuio_client.find_file_id("/music/a.mp3")
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


def test_all_playback_status_asks_every_renderer():
    """Bulk get_playback_status only reports casts this server started, so
    anything begun from another app is invisible without the fan-out."""
    def fake(name, arguments, timeout=10.0):
        if name == "list_renderers":
            return {"renderers": [{"id": "r1"}, {"id": "r2"}]}
        if arguments["renderer_id"] == "r2":
            return {"renderers": [{"renderer_id": "r2", "state": "playing",
                                   "current_url": "http://h/media/9.m4a"}]}
        return {"renderers": [{"renderer_id": "r1", "state": "unknown", "current_url": None}]}

    with patch("vuio_client._call_tool", side_effect=fake):
        status = vuio_client.all_playback_status()

    assert len(status["renderers"]) == 2
    assert any(r["state"] == "playing" for r in status["renderers"])


def test_all_playback_status_skips_renderers_that_fail():
    """An unreachable renderer must not take the whole poll down."""
    def fake(name, arguments, timeout=10.0):
        if name == "list_renderers":
            return {"renderers": [{"id": "dead"}, {"id": "alive"}]}
        if arguments["renderer_id"] == "dead":
            raise vuio_client.VuioError("timeout")
        return {"renderers": [{"renderer_id": "alive", "state": "playing",
                               "current_url": "http://h/media/3.m4a"}]}

    with patch("vuio_client._call_tool", side_effect=fake):
        status = vuio_client.all_playback_status()

    assert [r["renderer_id"] for r in status["renderers"]] == ["alive"]


def test_replace_playlist_tracks_removes_old_then_adds_new():
    calls = []

    def fake(name, arguments):
        calls.append((name, arguments))
        if name == "search_media":
            return {"files": [{"id": 99, "path": "/music/new.mp3"}]}
        if name == "get_playlist_tracks":
            return {"tracks": [{"id": 1}, {"id": 2}]}
        return {}

    with patch("vuio_client._call_tool", side_effect=fake):
        count = vuio_client.replace_playlist_tracks(7, ["/music/new.mp3"])

    assert count == 1
    names = [n for n, _ in calls]
    assert names.count("remove_from_playlist") == 2
    assert names.index("add_to_playlist") > names.index("remove_from_playlist")
    assert calls[-1] == ("add_to_playlist", {"playlist_id": 7, "media_file_ids": [99]})


def test_replace_playlist_tracks_keeps_old_contents_if_a_track_is_missing():
    """Resolution happens first, so a bad path cannot leave the playlist empty."""
    calls = []

    def fake(name, arguments):
        calls.append(name)
        if name == "search_media":
            return {"files": []}
        return {"tracks": [{"id": 1}]}

    with patch("vuio_client._call_tool", side_effect=fake):
        try:
            vuio_client.replace_playlist_tracks(7, ["/music/gone.mp3"])
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass
    assert "remove_from_playlist" not in calls


def test_create_playlist_raises_vuio_error_on_malformed_response():
    with patch("vuio_client._call_tool", return_value={}):
        try:
            vuio_client.create_playlist("My Playlist", [])
            assert False, "expected VuioError"
        except vuio_client.VuioError:
            pass


if __name__ == "__main__":
    test_call_tool_parses_structured_content()
    test_call_tool_parses_text_content_fallback()
    test_call_tool_raises_vuio_error_on_jsonrpc_error()
    test_call_tool_raises_vuio_error_on_malformed_content()
    test_call_tool_raises_vuio_error_on_plain_text_content()
    test_create_playlist_creates_then_adds_resolved_file_ids()
    test_find_file_id_raises_when_path_not_found()
    test_call_tool_raises_vuio_error_on_http_failure()
    test_call_tool_raises_vuio_error_on_non_json_response()
    test_list_renderers_raises_vuio_error_on_malformed_response()
    test_find_file_id_raises_vuio_error_on_malformed_response()
    test_all_playback_status_asks_every_renderer()
    test_all_playback_status_skips_renderers_that_fail()
    test_replace_playlist_tracks_removes_old_then_adds_new()
    test_replace_playlist_tracks_keeps_old_contents_if_a_track_is_missing()
    test_create_playlist_raises_vuio_error_on_malformed_response()
    print("All vuio_client tests passed.")
