import io
from urllib.error import HTTPError
from urllib.request import Request, build_opener

import pytest

from forwarder import NoRedirect, normalize


def test_normalizes_only_allowlisted_demo_policy() -> None:
    raw = {
        "time": "2026-08-22T00:00:00Z",
        "process_kprobe": {
            "policy_name": "cloudward-s1-unexpected-shell",
            "process": {
                "binary": "/usr/local/bin/python",
                "pod": {
                    "namespace": "cloudward-staging",
                    "name": "cloudward-demo-abcde-12345",
                    "pod_labels": [
                        "cloudward.io/demo-target=true",
                        "authorization=must-not-forward",
                    ],
                    "container": {"name": "api"},
                },
            },
        },
    }
    event = normalize(raw, node_name="node-1", sequence=1)
    assert event is not None
    assert event["event_type"] == "SUSPICIOUS_PROCESS"
    assert event["process"]["binary"] == "/bin/sh"
    assert "authorization" not in event["workload_labels"]


def test_ignores_unrelated_policy() -> None:
    raw = {"process_kprobe": {"policy_name": "unrelated", "process": {}}}
    assert normalize(raw, node_name="node-1", sequence=1) is None


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_signed_event_redirects_are_rejected(status):
    opener = build_opener(NoRedirect())
    request = Request("https://cloudward.example/webhook", data=b"{}")
    with pytest.raises(HTTPError) as error:
        opener.error(
            "http",
            request,
            io.BytesIO(),
            status,
            "Redirect",
            {"location": "https://untrusted.example/webhook"},
        )
    assert error.value.code == status
