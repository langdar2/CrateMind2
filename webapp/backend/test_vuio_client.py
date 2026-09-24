import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx

import vuio_client
from vuio_client import VuioError


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_list_renderers_parses_structured_content():
    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse({"result": {"structuredContent": {"renderers": [{"id": "r1"}, {"id": "r2"}]}}})

    original = httpx.post
    httpx.post = fake_post
    try:
        renderers = vuio_client.list_renderers()
    finally:
        httpx.post = original

    assert renderers == [{"id": "r1"}, {"id": "r2"}]


def test_find_file_id_parses_text_content_only_response():
    def fake_post(url, headers=None, json=None, timeout=None):
        payload = {"result": {"content": [{"type": "text", "text": '{"results": [{"id": 42}]}'}]}}
        return _FakeResponse(payload)

    original = httpx.post
    httpx.post = fake_post
    try:
        file_id = vuio_client.find_file_id("some track")
    finally:
        httpx.post = original

    assert file_id == 42


def test_find_file_id_returns_none_when_no_results():
    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse({"result": {"structuredContent": {"results": []}}})

    original = httpx.post
    httpx.post = fake_post
    try:
        file_id = vuio_client.find_file_id("nonexistent track")
    finally:
        httpx.post = original

    assert file_id is None


def test_error_response_raises_vuio_error():
    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse({"error": {"message": "tool not found"}})

    original = httpx.post
    httpx.post = fake_post
    try:
        raised = False
        try:
            vuio_client.list_renderers()
        except VuioError as exc:
            raised = True
            assert "tool not found" in str(exc)
        assert raised
    finally:
        httpx.post = original


def test_http_failure_raises_vuio_error():
    def fake_post(url, headers=None, json=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    original = httpx.post
    httpx.post = fake_post
    try:
        raised = False
        try:
            vuio_client.list_renderers()
        except VuioError:
            raised = True
        assert raised
    finally:
        httpx.post = original


if __name__ == "__main__":
    test_list_renderers_parses_structured_content()
    test_find_file_id_parses_text_content_only_response()
    test_find_file_id_returns_none_when_no_results()
    test_error_response_raises_vuio_error()
    test_http_failure_raises_vuio_error()
    print("All vuio_client tests passed.")
