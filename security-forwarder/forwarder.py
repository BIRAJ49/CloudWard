"""Bounded Tetragon JSONL forwarder with strict normalization and HMAC delivery."""

from __future__ import annotations

import collections
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

POLICIES = {
    "cloudward-s1-unexpected-shell": ("SUSPICIOUS_PROCESS", "high"),
    "cloudward-s2-unexpected-egress": ("UNEXPECTED_EGRESS", "high"),
    "cloudward-s3-privilege-attempt": ("PRIVILEGE_BEHAVIOR", "critical"),
}
ALLOWED_LABELS = {
    "cloudward.io/demo-target",
    "cloudward.io/environment",
    "cloudward.io/criticality",
    "app.kubernetes.io/name",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(?:password|token|secret|api[_-]?key)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?)://[^\s]+"),
)
MAX_LINE_BYTES = 1_048_576


class ConfigurationError(RuntimeError):
    pass


def log(event: str, **fields: object) -> None:
    print(
        json.dumps(
            {"timestamp": datetime.now(UTC).isoformat(), "event": event, **fields},
            separators=(",", ":"),
            default=str,
        ),
        flush=True,
    )


def _redact(value: str) -> str:
    output = value[:512]
    for pattern in SECRET_PATTERNS:
        output = pattern.sub("[REDACTED]", output)
    return output


def _labels(raw: object) -> dict[str, str]:
    if isinstance(raw, dict):
        source = {str(key): str(value) for key, value in raw.items()}
    elif isinstance(raw, list):
        source = {}
        for item in raw:
            if isinstance(item, str) and "=" in item:
                key, value = item.split("=", 1)
                source[key] = value
    else:
        source = {}
    return {
        key: _redact(value[:128])
        for key, value in source.items()
        if key in ALLOWED_LABELS
    }


def _event_body(raw: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("process_kprobe", "process_tracepoint", "process_exec"):
        value = raw.get(key)
        if isinstance(value, dict):
            return value
    return None


def normalize(raw: dict[str, Any], *, node_name: str, sequence: int) -> dict[str, Any] | None:
    body = _event_body(raw)
    if body is None:
        return None
    policy = str(body.get("policy_name") or body.get("policy") or "")
    classification = POLICIES.get(policy)
    if classification is None:
        return None
    process = body.get("process")
    if not isinstance(process, dict):
        return None
    pod = process.get("pod")
    if not isinstance(pod, dict):
        return None
    namespace = str(pod.get("namespace") or "")
    pod_name = str(pod.get("name") or "")
    container = pod.get("container") if isinstance(pod.get("container"), dict) else {}
    labels = _labels(pod.get("pod_labels") or pod.get("labels"))
    if (
        namespace != "cloudward-staging"
        or not pod_name
        or labels.get("cloudward.io/demo-target") != "true"
    ):
        return None
    event_type, severity = classification
    normalized: dict[str, Any] = {
        "source": "tetragon",
        "event_type": event_type,
        "severity": severity,
        "environment": "staging",
        "namespace": namespace,
        "pod": pod_name[:253],
        "workload": str(pod.get("workload") or pod_name.rsplit("-", 2)[0])[:253],
        "container": str(container.get("name") or "api")[:253],
        "policy": policy,
        "timestamp": str(raw.get("time") or datetime.now(UTC).isoformat()),
        "evidence_ref": f"tetragon:{node_name[:100]}:{sequence}",
        "workload_labels": labels,
        "secrets_or_data_exposure": False,
    }
    binary = _redact(str(process.get("binary") or "/usr/local/bin/python"))
    parent = body.get("parent")
    parent_binary = (
        _redact(str(parent.get("binary"))) if isinstance(parent, dict) and parent.get("binary") else None
    )
    if event_type == "UNEXPECTED_EGRESS":
        normalized["network"] = {
            "destination_host": "cloudward-c2-simulator.cloudward-staging.svc.cluster.local",
            "destination_port": 8080,
            "protocol": "tcp",
        }
    elif event_type == "SUSPICIOUS_PROCESS":
        normalized["process"] = {
            "binary": "/bin/sh",
            "parent_binary": parent_binary or binary,
        }
    else:
        normalized["process"] = {"binary": binary, "parent_binary": parent_binary}
    return normalized


class Forwarder:
    def __init__(self) -> None:
        self.event_file = Path(
            os.getenv("TETRAGON_EVENT_FILE", "/var/run/cilium/tetragon/tetragon.log")
        )
        self.api_url = os.environ.get("CLOUDWARD_SECURITY_API_URL", "")
        self.secret = os.environ.get("TETRAGON_WEBHOOK_SECRET", "")
        self.node_name = os.getenv("NODE_NAME", "unknown-node")
        self.rate = int(os.getenv("FORWARDER_MAX_EVENTS_PER_MINUTE", "60"))
        self.dedup_ttl = int(os.getenv("FORWARDER_DEDUP_TTL_SECONDS", "300"))
        self.events: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=int(os.getenv("FORWARDER_QUEUE_SIZE", "256"))
        )
        self._seen: dict[str, float] = {}
        self._sent: collections.deque[float] = collections.deque()
        self._validate()

    def _validate(self) -> None:
        parsed = urllib.parse.urlparse(self.api_url)
        local_http_hosts = {"host.k3d.internal", "host.docker.internal", "127.0.0.1"}
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in local_http_hosts
        ):
            raise ConfigurationError("security API must use HTTPS (local host bridge excepted)")
        if not parsed.path.endswith("/api/v1/webhooks/security/tetragon"):
            raise ConfigurationError("security API URL has an unexpected path")
        if len(self.secret) < 32:
            raise ConfigurationError("TETRAGON_WEBHOOK_SECRET must contain at least 32 characters")
        if not 1 <= self.rate <= 10_000 or not 10 <= self.dedup_ttl <= 3600:
            raise ConfigurationError("forwarder bounds are invalid")

    def run(self) -> None:
        threading.Thread(target=self._tail, name="tetragon-tail", daemon=True).start()
        sequence = 0
        while True:
            raw = self.events.get()
            sequence += 1
            normalized = normalize(raw, node_name=self.node_name, sequence=sequence)
            if normalized is None or self._duplicate(normalized) or not self._within_rate():
                continue
            self._deliver(normalized)

    def _tail(self) -> None:
        position = 0
        while True:
            try:
                size = self.event_file.stat().st_size
                if size < position:
                    position = 0
                with self.event_file.open("rb") as stream:
                    stream.seek(position)
                    while line := stream.readline(MAX_LINE_BYTES + 1):
                        position = stream.tell()
                        if len(line) > MAX_LINE_BYTES:
                            log("event_dropped", reason="line_too_large")
                            continue
                        try:
                            event = json.loads(line)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            log("event_dropped", reason="invalid_json")
                            continue
                        if isinstance(event, dict):
                            try:
                                self.events.put(event, timeout=0.1)
                            except queue.Full:
                                log("event_dropped", reason="backpressure")
            except FileNotFoundError:
                pass
            except OSError as exc:
                log("tail_error", error_type=type(exc).__name__)
            time.sleep(0.5)

    def _duplicate(self, event: dict[str, Any]) -> bool:
        now = time.monotonic()
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        for key in [key for key, expiry in self._seen.items() if expiry <= now]:
            self._seen.pop(key, None)
        if fingerprint in self._seen:
            return True
        self._seen[fingerprint] = now + self.dedup_ttl
        return False

    def _within_rate(self) -> bool:
        now = time.monotonic()
        while self._sent and self._sent[0] <= now - 60:
            self._sent.popleft()
        if len(self._sent) >= self.rate:
            log("event_dropped", reason="rate_limited")
            return False
        self._sent.append(now)
        return True

    def _deliver(self, event: dict[str, Any]) -> None:
        body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
        for attempt in range(1, 4):
            timestamp = str(int(time.time()))
            nonce = secrets.token_hex(16)
            signed = timestamp.encode() + b"." + nonce.encode() + b"." + body
            signature = hmac.new(self.secret.encode(), signed, hashlib.sha256).hexdigest()
            request = urllib.request.Request(
                self.api_url,
                method="POST",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-CloudWard-Timestamp": timestamp,
                    "X-CloudWard-Nonce": nonce,
                    "X-CloudWard-Signature": f"sha256={signature}",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                    if 200 <= response.status < 300:
                        log("event_forwarded", event_type=event["event_type"], attempt=attempt)
                        return
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                log("delivery_failed", attempt=attempt, error_type=type(exc).__name__)
            time.sleep(2 ** (attempt - 1))
        log("event_dropped", reason="delivery_retries_exhausted", event_type=event["event_type"])


if __name__ == "__main__":
    try:
        Forwarder().run()
    except (ConfigurationError, ValueError) as error:
        log("configuration_error", error_type=type(error).__name__)
        sys.exit(2)

