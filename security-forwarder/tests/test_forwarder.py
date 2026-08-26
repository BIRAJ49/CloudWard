from forwarder import normalize


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
