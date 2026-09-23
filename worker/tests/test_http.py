import io
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.request import Request, build_opener

import pytest
from worker.http import _NoRedirect, internal_url, post_json


@pytest.mark.parametrize(
    "base",
    [
        "http://evil.example/api/v1/internal",
        "file:///api/v1/internal",
        "http://api:8000/other",
        "http://api:8000/api/v1/internal?redirect=evil",
        "http://user:pass@api:8000/api/v1/internal",
        "http://api:8000/api/v1/internal#fragment",
    ],
)
def test_rejects_untrusted_base(base):
    with pytest.raises(RuntimeError, match="allowed boundary"):
        internal_url(base, "/security/events/process")


@pytest.mark.parametrize(
    "path", ["/../admin", "/%2e%2e/admin", "//evil.example", "/a?x=1", "/a#x"]
)
def test_rejects_path_injection(path):
    with pytest.raises(RuntimeError, match="allowed boundary"):
        internal_url("http://api:8000/api/v1/internal", path)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_cannot_forward_credentials(status):
    handler = _NoRedirect()
    opener = build_opener(handler)
    request = Request(
        "http://api:8000/api/v1/internal/test",
        data=b"{}",
        headers={"Authorization": "Bearer private"},
    )
    with pytest.raises(HTTPError) as error:
        opener.error(
            "http",
            request,
            io.BytesIO(),
            status,
            "Redirect",
            {"location": "https://evil.example"},
        )
    assert error.value.code == status


@pytest.mark.parametrize(
    "body,valid", [(b'{"ok":true}', True), (b"[]", False), (b"x" * 101, False)]
)
def test_response_is_bounded_and_object_only(monkeypatch, body, valid):
    response = MagicMock()
    response.read.return_value = body
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    monkeypatch.setattr("worker.http.build_opener", lambda *args: opener)
    monkeypatch.setattr("worker.http.MAX_RESPONSE_BYTES", 100)
    if valid:
        assert post_json(
            "http://api:8000/api/v1/internal/test", "private", {}, timeout=1
        ) == {"ok": True}
    else:
        with pytest.raises(RuntimeError):
            post_json("http://api:8000/api/v1/internal/test", "private", {}, timeout=1)
    response.read.assert_called_once_with(101)


def test_post_revalidates_url_before_open(monkeypatch):
    opener = MagicMock()
    monkeypatch.setattr("worker.http.build_opener", opener)
    with pytest.raises(RuntimeError):
        post_json("http://evil.example/api/v1/internal/test", "private", {}, timeout=1)
    opener.assert_not_called()
