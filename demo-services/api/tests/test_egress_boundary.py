import io
from urllib.error import HTTPError
from urllib.request import Request, build_opener

import pytest

from app.security_scenarios import EXPECTED_C2_HOST, NoRedirect, _c2_url


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_probe_cannot_follow_redirects(status):
    opener = build_opener(NoRedirect())
    request = Request(f"http://{EXPECTED_C2_HOST}:8080/observe")
    with pytest.raises(HTTPError) as error:
        opener.error(
            "http",
            request,
            io.BytesIO(),
            status,
            "Redirect",
            {"location": "https://untrusted.example"},
        )
    assert error.value.code == status


def test_probe_rejects_embedded_credentials(monkeypatch):
    monkeypatch.setenv(
        "CLOUDWARD_C2_URL", f"http://user:pass@{EXPECTED_C2_HOST}:8080/observe"
    )
    with pytest.raises(RuntimeError, match="fixed internal simulator"):
        _c2_url()
