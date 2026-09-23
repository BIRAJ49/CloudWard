"""Build bounded, factual incident context for provider-neutral AI diagnosis."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context import IncidentContext, IncidentContextBuilder
from app.db.models import EvidenceSnapshot, Incident, Service
from app.incident_memory.fingerprint import FingerprintInput, select_stable_labels
from app.incident_memory.service import IncidentMemoryService
from app.runbooks import RunbookLoader


async def build_incident_context(
    session: AsyncSession,
    incident: Incident,
    runbooks: RunbookLoader,
    *,
    evidence_limit: int = 80,
    history_limit: int = 5,
) -> IncidentContext:
    evidence = list(
        (
            await session.execute(
                select(EvidenceSnapshot)
                .where(EvidenceSnapshot.incident_id == incident.id)
                .order_by(EvidenceSnapshot.created_at.desc())
                .limit(min(max(evidence_limit, 1), 100))
            )
        ).scalars()
    )
    service = None
    if incident.service_id:
        service = (
            await session.execute(select(Service).where(Service.id == incident.service_id))
        ).scalar_one_or_none()
    service_key = service.name if service else str(incident.service_id or "unassigned")
    historical = await IncidentMemoryService(session).find_similar(
        FingerprintInput(
            service=service_key,
            incident_type=incident.incident_type,
            alert_name=incident.title,
            namespace=service.namespace if service else None,
            labels=select_stable_labels(service.labels if service else {}),
        ),
        exclude_incident_id=incident.id,
        limit=min(max(history_limit, 1), 10),
        correlation_id=incident.correlation_id,
    )
    raw = {
        "incident": {
            "incident_id": str(incident.id),
            "service": service_key,
            "environment": incident.environment.value,
            "severity": incident.severity,
            "category": incident.incident_type,
            "alert": incident.title,
            "namespace": service.namespace if service else None,
        },
        "untrusted_evidence": _evidence_payload(evidence, historical),
        "available_runbooks": [
            {
                "id": item.id,
                "version": item.version,
                "actions": [item.action.type.value],
            }
            for item in runbooks.runbooks
        ],
        "complexity_score": min(
            100,
            15
            + len(evidence) * 4
            + (25 if incident.environment.value == "production" else 0)
            + (20 if incident.incident_type.startswith("security") else 0),
        ),
    }
    return IncidentContextBuilder().build(raw)


def _evidence_payload(evidence: list[EvidenceSnapshot], historical: list[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "handling": "UNTRUSTED_DATA",
        "kubernetes_summary": {},
        "metrics": [],
        "logs": [],
        "traces": [],
        "deployment": {},
        "git_changes": [],
        "historical_incidents": [],
    }
    for item in evidence:
        kind = item.evidence_type.value
        ref = f"evidence:{item.id}"
        payload = item.payload if isinstance(item.payload, dict) else {}
        if kind in {"KUBERNETES_STATE", "KUBERNETES_EVENT"}:
            current = result["kubernetes_summary"]
            summaries = current.get("summaries", []) if isinstance(current, dict) else []
            result["kubernetes_summary"] = {
                "summaries": [*summaries, {"ref": ref, "summary": item.summary}][:10],
                "latest": _bounded_object(payload, 6000),
            }
        elif kind in {"METRIC", "METRIC_SUMMARY"}:
            points = _metric_points(payload.get("samples"))
            result["metrics"].append(
                {
                    "ref": ref,
                    "name": str(payload.get("metric", payload.get("name", "metric")))[:255],
                    "before": points[0] if points else _number(payload.get("before")),
                    "during": points[-1] if points else _number(payload.get("during")),
                    "window": _window(item),
                    "summary": item.summary,
                }
            )
        elif kind in {"LOG", "LOG_SUMMARY"}:
            raw_samples = payload.get("samples", payload.get("lines", []))
            lines = _log_lines(raw_samples)
            result["logs"].append(
                {
                    "ref": ref,
                    "count": len(raw_samples) if isinstance(raw_samples, list) else len(lines),
                    "representative_lines": lines[:20],
                    "fingerprints": [
                        hashlib.sha256(line.strip().lower().encode()).hexdigest()[:16]
                        for line in lines[:20]
                    ],
                }
            )
        elif kind in {"TRACE", "TRACE_SUMMARY"}:
            samples = payload.get("samples", [])
            traces = samples[:20] if isinstance(samples, list) else []
            result["traces"].append(
                {
                    "ref": ref,
                    "critical_path": [_trace_label(value) for value in traces[:10]],
                    "slow_spans": [
                        _trace_label(value)
                        for value in sorted(
                            traces,
                            key=lambda entry: _trace_duration(entry),
                            reverse=True,
                        )[:5]
                    ],
                    "error_spans": [
                        _trace_label(value)
                        for value in traces
                        if isinstance(value, dict) and value.get("error") is True
                    ][:5],
                    "service_graph_summary": item.summary,
                }
            )
        elif kind in {"DEPLOYMENT", "DEPLOYMENT_STATE"}:
            result["deployment"] = {
                "ref": ref,
                "summary": item.summary,
                "data": _bounded_object(payload, 6000),
            }
        elif kind == "GIT_CHANGE":
            files = payload.get("files", [])
            for file in files[:20] if isinstance(files, list) else []:
                if not isinstance(file, dict):
                    continue
                result["git_changes"].append(
                    {
                        "ref": ref,
                        "repository": str(payload.get("repository", "unknown/unknown"))[:255],
                        "commit_sha": str(payload.get("commit", "0000000"))[:64],
                        "previous_commit_sha": str(payload.get("previous_commit", "0000000"))[:64],
                        "file": str(file.get("path", "unknown"))[:500],
                        "status": str(file.get("status", "unknown"))[:32],
                        "patch": str(file.get("patch", ""))[:4000],
                    }
                )
    result["historical_incidents"] = [
        {
            "ref": f"history:{item.incident_id}",
            "incident_id": str(item.incident_id),
            "match_reasons": item.match_reasons,
            "root_cause_category": item.root_cause_category,
            "action": item.action.value if item.action else None,
            "result": item.result,
            "verification_success": item.verification_success,
            "duration_seconds": item.duration_seconds,
            "summary": item.operator_summary,
        }
        for item in historical[:10]
    ]
    return result


def _metric_points(value: Any) -> list[float]:
    points: list[float] = []
    if not isinstance(value, list):
        return points
    for series in value[:20]:
        if not isinstance(series, dict):
            continue
        candidates = series.get("values", [])
        if not isinstance(candidates, list):
            candidates = []
        scalar = series.get("value")
        if isinstance(scalar, list):
            candidates = [*candidates, scalar]
        for point in candidates[:200]:
            if not isinstance(point, list) or len(point) != 2:
                continue
            try:
                points.append(float(point[1]))
            except (TypeError, ValueError):
                continue
    return points


def _log_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for sample in value[:50]:
        line = sample.get("line", sample.get("message")) if isinstance(sample, dict) else sample
        if line is not None:
            lines.append(str(line)[:500])
    return lines


def _trace_label(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)[:500]
    parts = [
        value.get("rootServiceName", value.get("serviceName", "unknown-service")),
        value.get("rootTraceName", value.get("name", "unknown-trace")),
        value.get("traceID", value.get("traceId", "unknown-id")),
        f"duration={_trace_duration(value)}ms",
    ]
    return " | ".join(str(part)[:160] for part in parts)[:500]


def _trace_duration(value: Any) -> float:
    if not isinstance(value, dict):
        return 0.0
    raw = value.get("durationMs", value.get("duration", 0))
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return 0.0
    try:
        duration = float(raw)
    except (OverflowError, ValueError):
        return 0.0
    return max(0.0, duration) if math.isfinite(duration) else 0.0


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _window(item: EvidenceSnapshot) -> str:
    if item.window_start and item.window_end:
        seconds = max(0, int((item.window_end - item.window_start).total_seconds()))
        return f"{seconds}s"
    return "bounded"


def _bounded_object(value: Any, max_chars: int) -> Any:
    serialized = json.dumps(value, default=str, separators=(",", ":"))
    if len(serialized) <= max_chars:
        return value
    return {"summary": serialized[:max_chars], "truncated": True}
