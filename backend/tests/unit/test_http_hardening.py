from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.ai.incident_context import _trace_duration
from app.api import health
from app.api.events import event_stream
from app.db.models import StreamEvent
from app.errors import CloudWardError
from app.finops.providers import PrometheusFinOpsClient, _BoundedJSONClient
from app.finops.schemas import CostAllocation
from app.logging import JsonFormatter, redact
from app.observability.evidence import IncidentEvidenceService, TelemetryTarget
from app.observability.providers import (
    LokiLogsProvider,
    PrometheusMetricsProvider,
    TelemetryResult,
    TelemetryWindow,
    TempoTracesProvider,
)
from app.security.webhook_auth import read_bounded_body


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "null", "http://localhost:5173.evil.example"]
)
async def test_csrf_rejects_untrusted_origins(api_client, origin):
    response = await api_client.post(
        "/api/v1/auth/dev", headers={"Origin": origin}, json={"login": "tester", "role": "Viewer"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_ORIGIN_DENIED"
    assert not response.cookies


async def test_cookie_mutations_require_trusted_origin(api_client):
    response = await api_client.post("/api/v1/auth/dev", json={"login": "tester", "role": "Viewer"})
    assert response.status_code == 200
    denied = await api_client.post("/api/v1/auth/logout")
    assert denied.status_code == 403
    assert (await api_client.get("/api/v1/auth/me")).status_code == 200
    allowed = await api_client.post(
        "/api/v1/auth/logout", headers={"Origin": "http://localhost:5173"}
    )
    assert allowed.status_code == 204


@pytest.mark.parametrize("declared_length", [None, "1", "-1", "invalid", "20"])
async def test_bounded_body_rejects_chunks_and_invalid_lengths(declared_length):
    receive = AsyncMock(
        side_effect=[
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"678901", "more_body": False},
        ]
    )
    headers = [] if declared_length is None else [(b"content-length", declared_length.encode())]
    request = Request({"type": "http", "headers": headers}, receive)
    with pytest.raises(CloudWardError) as error:
        await read_bounded_body(request, 10)
    assert error.value.status_code in {400, 413}
    if declared_length in {"-1", "invalid", "20"}:
        receive.assert_not_called()


async def test_alertmanager_rejects_chunked_oversized_body(api_client, settings):
    async def chunks():
        yield b"x" * 600_000
        yield b"x" * 600_000

    response = await api_client.post(
        "/api/v1/webhooks/alertmanager",
        content=chunks(),
        headers={
            "Authorization": f"Bearer {settings.alertmanager_webhook_token.get_secret_value()}"
        },
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "WEBHOOK_PAYLOAD_TOO_LARGE"


def test_redaction_covers_messages_exceptions_and_cycles():
    secret = "ghp_abcdefgh12345678"
    try:
        raise ValueError(f"failed with {secret}")
    except ValueError as exc:
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "password=hunter42",
            (),
            (type(exc), exc, exc.__traceback__),
        )
    output = JsonFormatter(service="test", environment="test").format(record)
    assert secret not in output
    assert "hunter42" not in output
    assert "[REDACTED]" in output
    cycle = {}
    cycle["nested"] = cycle
    assert "[TRUNCATED_DEPTH]" in json.dumps(redact(cycle))


def window():
    now = datetime.now(UTC)
    return TelemetryWindow(start=now - timedelta(minutes=1), end=now)


async def test_telemetry_response_is_bounded_before_json_parse(monkeypatch):
    client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 101))
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs)
    )
    provider = PrometheusMetricsProvider("http://prometheus", timeout_seconds=1, max_samples=5)
    provider.MAX_RESPONSE_BYTES = 100
    with pytest.raises(CloudWardError, match="bounded evidence query"):
        await provider.query_range("up", window())


async def test_loki_caps_samples_and_redacts_embedded_secrets(monkeypatch):
    provider = LokiLogsProvider("http://loki", timeout_seconds=1, max_samples=2)
    monkeypatch.setattr(
        provider,
        "_get",
        AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "result": [
                        {
                            "stream": {},
                            "values": [
                                ["1", "password=private"],
                                ["2", "ok"],
                                ["3", "not copied"],
                            ],
                        }
                    ]
                },
            }
        ),
    )
    result = await provider.query_range("{}", window())
    assert len(result.samples) == 2
    assert result.truncated
    assert "private" not in result.model_dump_json()
    monkeypatch.setattr(
        provider, "_get", AsyncMock(return_value={"status": "success", "data": None})
    )
    with pytest.raises(CloudWardError, match="not a list"):
        await provider.query_range("{}", window())


@pytest.mark.parametrize("fail", [False, True])
async def test_evidence_queries_run_concurrently_before_persistence(fail):
    started = 0
    all_started = asyncio.Event()

    async def query(query, query_window, *, namespace=None):
        nonlocal started
        if query == "demo":
            assert namespace == "staging"
        elif "cloudward_demo_http" in query:
            assert 'namespace="staging"' in query
        started += 1
        if started == 5:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1)
        if fail:
            raise CloudWardError("TEST_UNAVAILABLE", "provider failed")
        return TelemetryResult(provider="test", query=query, window=query_window, samples=[])

    provider = SimpleNamespace(query_range=query, search=query)
    service = IncidentEvidenceService(
        metrics=provider, logs=provider, traces=provider, before_seconds=60
    )
    session = MagicMock()
    session.flush = AsyncMock()
    collect = service.collect(
        session,
        incident_id=uuid.uuid4(),
        correlation_id="test",
        target=TelemetryTarget(service="demo", namespace="staging"),
        incident_started_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    if fail:
        with pytest.raises(CloudWardError, match="provider failed"):
            await collect
        session.add_all.assert_not_called()
        session.flush.assert_not_called()
    else:
        snapshots = await collect
        assert len(snapshots) == 5
        assert [snapshot.payload.get("metric") for snapshot in snapshots[:3]] == [
            "http_error_rate",
            "p95_latency",
            "restart_count",
        ]
        session.flush.assert_awaited_once()
    assert started == 5


async def test_trace_query_requires_and_escapes_namespace(monkeypatch):
    provider = TempoTracesProvider("http://tempo", timeout_seconds=1, max_samples=5)
    request = AsyncMock(return_value={"traces": []})
    monkeypatch.setattr(provider, "_get", request)
    await provider.search('demo"', window(), namespace="cloudward-production")
    query = request.call_args.args[1]["q"]
    assert 'resource.k8s.namespace.name = "cloudward-production"' in query
    assert 'resource.service.name = "demo\\""' in query


@pytest.mark.parametrize("provider_kind", ["telemetry", "finops"])
async def test_internal_telemetry_disables_environment_proxies(monkeypatch, provider_kind):
    original = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs)
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    if provider_kind == "telemetry":
        provider = PrometheusMetricsProvider("http://prometheus", timeout_seconds=1, max_samples=5)
        await provider._get("/api/v1/query", {})
    else:
        bounded = _BoundedJSONClient(
            "http://opencost", provider="opencost", timeout_seconds=1, max_response_bytes=1024
        )
        await bounded.get("/allocation", params={})
    assert options[0]["trust_env"] is False


async def test_idle_event_stream_releases_database_transaction(session, monkeypatch):
    await session.execute(select(1))
    assert session.in_transaction()
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    response = await event_stream(request, None, session)
    assert not session.in_transaction()

    async def idle_wait(_):
        assert not session.in_transaction()
        return False

    monkeypatch.setattr("app.api.events.wait_for_stream_event", idle_wait)
    iterator = response.body_iterator
    assert await anext(iterator) == "retry: 3000\n\n"
    assert await anext(iterator) == ": keepalive\n\n"
    await iterator.aclose()


async def test_stream_replay_releases_connection_before_slow_reader(session):
    session.add_all(
        [
            StreamEvent(event_type="incident.created", payload={"order": 1}),
            StreamEvent(event_type="incident.created", payload={"order": 2}),
            StreamEvent(event_type="incident.created", payload={"order": 3}),
        ]
    )
    await session.commit()
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    response = await event_stream(request, None, session, header_event_id="1")
    iterator = response.body_iterator
    await anext(iterator)
    assert "id: 2\n" in await anext(iterator)
    assert not session.in_transaction()
    assert "id: 3\n" in await anext(iterator)
    assert not session.in_transaction()
    await iterator.aclose()


@pytest.mark.parametrize("cursor", ["-1", str(2**31), str(2**53), "nan"])
async def test_event_stream_rejects_out_of_range_header_cursor(session, cursor):
    with pytest.raises(CloudWardError, match="non-negative integer"):
        await event_stream(None, None, session, header_event_id=cursor)


@pytest.mark.parametrize(
    "value,expected",
    [("12.5", 12.5), (12, 12), (-1, 0), ("nan", 0), ("inf", 0), (True, 0), (None, 0)],
)
def test_trace_duration_preserves_numeric_strings_and_rejects_nonfinite(value, expected):
    assert _trace_duration({"durationMs": value}) == expected


async def test_finops_bounds_chunked_response():
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"123456"
            yield b"78901"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks()))
    ) as client:
        provider = _BoundedJSONClient(
            "http://opencost",
            provider="OpenCost",
            timeout_seconds=1,
            max_response_bytes=10,
            client=client,
        )
        with pytest.raises(CloudWardError) as error:
            await provider.get("/allocation", params={})
        assert error.value.code == "FINOPS_PROVIDER_RESPONSE_TOO_LARGE"


async def test_readiness_deadline_includes_connection_acquisition(monkeypatch):
    class ExhaustedPool:
        async def __aenter__(self):
            await asyncio.Event().wait()

        async def __aexit__(self, *args):
            pass

    timeout = asyncio.timeout
    monkeypatch.setattr(health.asyncio, "timeout", lambda _: timeout(0.01))
    monkeypatch.setattr(health, "engine", SimpleNamespace(connect=ExhaustedPool))
    assert await health._database_check() == {"status": "down", "error": "TimeoutError"}


@pytest.mark.parametrize("kind,expected", [("workload", 7), ("nodes", 8)])
@pytest.mark.parametrize("fail", [False, True])
async def test_finops_queries_are_concurrent_and_finish_before_return(kind, expected, fail):
    started = 0
    finished = 0
    ready = asyncio.Event()

    async def handler(request):
        nonlocal started, finished
        started += 1
        if started == expected:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=1)
        finished += 1
        if fail:
            return httpx.Response(503)
        is_range = request.url.path.endswith("query_range")
        timestamp = datetime.now(UTC).timestamp()
        result = (
            {"values": [[timestamp - 60, "1"], [timestamp, "2"]]}
            if is_range
            else {"value": [timestamp, "2"]}
        )
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix" if is_range else "vector",
                    "result": [result],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = PrometheusFinOpsClient("http://prometheus", client=client)
        common = {
            "environment": "staging",
            "window_seconds": 60,
            "step_seconds": 15,
            "allocation": CostAllocation(),
        }
        operation = (
            provider.collect_workload(
                namespace="staging", deployment="demo", pod_pattern="demo-.*", **common
            )
            if kind == "workload"
            else provider.collect_nodes(**common)
        )
        if fail:
            with pytest.raises(CloudWardError):
                await operation
        else:
            observation = await operation
            assert observation.cpu_usage_cores.values == (1.0, 2.0)
        assert started == finished == expected
