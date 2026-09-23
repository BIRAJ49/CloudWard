"""Run as python -m app.cluster_agent.runtime inside a least-privileged Kubernetes pod."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import ssl
import time
from pathlib import Path

import httpx

from app.cluster_agent.collector import AgentCollector, KubernetesReader
from app.cluster_agent.config import AgentSettings
from app.cluster_agent.schemas import AgentReceipt, AgentReport
from app.logging import JsonFormatter

logger = logging.getLogger(__name__)
SERVICE_ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class ReportPublisher:
    def __init__(self, settings: AgentSettings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    async def publish(self, report: AgentReport) -> bool:
        body = report.model_dump_json().encode()
        if len(body) > 524_288:
            logger.error("agent_report_exceeds_limit")
            return False
        for attempt in range(3):
            try:
                async with (
                    asyncio.timeout(10),
                    self.client.stream(
                        "POST",
                        self.settings.control_plane_url.rstrip("/") + "/api/v1/agent/reports",
                        content=body,
                        headers={
                            "Authorization": f"Bearer {self.settings.token.get_secret_value()}",
                            "Content-Type": "application/json",
                        },
                        follow_redirects=False,
                    ) as response,
                ):
                    if response.status_code == 202:
                        receipt_body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(receipt_body) + len(chunk) > 4096:
                                raise ValueError("oversized receipt")
                            receipt_body.extend(chunk)
                        receipt = AgentReceipt.model_validate_json(receipt_body)
                        return receipt.report_id == report.report_id
                    logger.warning(
                        "agent_delivery_rejected",
                        extra={"fields": {"status": response.status_code, "attempt": attempt + 1}},
                    )
                    if response.status_code < 500 and response.status_code not in {408, 429}:
                        return False
            except (httpx.HTTPError, TimeoutError, ValueError):
                logger.warning(
                    "agent_delivery_unavailable", extra={"fields": {"attempt": attempt + 1}}
                )
            if attempt < 2:
                await asyncio.sleep(2**attempt)
        return False


async def run() -> None:
    settings = AgentSettings()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service="cloudward-agent", environment=settings.environment))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    # In-cluster CA and rotating service-account token, never administrator kubeconfig.
    tls = ssl.create_default_context(cafile=str(SERVICE_ACCOUNT / "ca.crt"))
    settings.state_directory.mkdir(parents=True, exist_ok=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async with (
        httpx.AsyncClient(
            base_url="https://kubernetes.default.svc",
            verify=tls,
            trust_env=False,
            timeout=settings.timeout_seconds,
        ) as kube_client,
        httpx.AsyncClient(trust_env=False, timeout=10) as publisher_client,
    ):
        reader = KubernetesReader(
            kube_client, lambda: (SERVICE_ACCOUNT / "token").read_text(), settings.timeout_seconds
        )
        collector = AgentCollector(settings, reader)
        publisher = ReportPublisher(settings, publisher_client)
        delivered_at: float | None = None
        while not stop.is_set():
            started = time.monotonic()
            try:
                async with asyncio.timeout(90):
                    report = await collector.collect()
                    if await publisher.publish(report):
                        delivered_at = time.time()
                        logger.info(
                            "agent_report_delivered",
                            extra={
                                "fields": {
                                    "report_id": str(report.report_id),
                                    "workloads": len(report.workloads),
                                }
                            },
                        )
            except Exception as exc:
                # Exception messages/tracebacks may contain provider credentials.
                logger.error(
                    "agent_cycle_failed", extra={"fields": {"error_type": type(exc).__name__}}
                )
            temporary = settings.state_directory / "status.tmp"
            temporary.write_text(
                json.dumps({"cycle_at": time.time(), "delivered_at": delivered_at})
            )
            temporary.replace(settings.state_directory / "status.json")
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=max(1, settings.interval_seconds - (time.monotonic() - started)),
                )
            except TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(run())
