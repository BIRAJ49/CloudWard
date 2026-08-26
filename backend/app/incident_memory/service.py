"""Store and rank structured historical incidents deterministically."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.redaction import redact_untrusted
from app.audit import record_audit
from app.incident_memory.fingerprint import FingerprintInput, incident_fingerprint
from app.incident_memory.models import IncidentMemoryRecord
from app.incident_memory.schemas import MemoryWrite, SimilarIncidentResponse
from app.remediation.actions import ActionType


@dataclass(frozen=True, slots=True)
class RankedMemory:
    record: IncidentMemoryRecord
    score: int
    reasons: tuple[str, ...]


class IncidentMemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def remember(self, value: MemoryWrite, *, correlation_id: str) -> IncidentMemoryRecord:
        fingerprint_input = FingerprintInput(
            service=value.service,
            incident_type=value.incident_type,
            alert_name=value.alert_name,
            namespace=value.namespace,
            root_cause_category=value.root_cause_category,
            labels=value.labels,
        )
        canonical = fingerprint_input.canonical()
        existing = (
            await self._session.execute(
                select(IncidentMemoryRecord).where(
                    IncidentMemoryRecord.incident_id == value.incident_id
                )
            )
        ).scalar_one_or_none()
        record = existing or IncidentMemoryRecord(incident_id=value.incident_id)
        record.fingerprint = incident_fingerprint(fingerprint_input)
        record.service_key = str(canonical["service"])
        record.environment = value.environment
        record.incident_type = str(canonical["incident_type"])
        record.alert_name = str(canonical["alert_name"])
        record.namespace = value.namespace
        record.root_cause_category = value.root_cause_category
        labels = canonical["labels"]
        record.stable_labels = labels if isinstance(labels, dict) else {}
        record.runbook_id = value.runbook_id
        record.action = value.action.value if value.action else None
        record.result = value.result
        record.verification_success = value.verification_success
        record.duration_seconds = value.duration_seconds
        record.model = value.model
        record.confidence = value.confidence
        record.successful = bool(
            value.verification_success is True and value.result.upper() in {"RESOLVED", "SUCCEEDED"}
        )
        record.resolved_at = value.resolved_at
        redacted = redact_untrusted(value.evidence_summary)
        record.evidence_summary = redacted if isinstance(redacted, dict) else {}
        summary = redact_untrusted(value.operator_summary)
        record.operator_summary = summary if isinstance(summary, str) else None
        self._session.add(record)
        await self._session.flush()
        await record_audit(
            self._session,
            event_type="INCIDENT_MEMORY_STORED",
            correlation_id=correlation_id,
            incident_id=value.incident_id,
            result="SUCCEEDED",
            metadata={
                "fingerprint": record.fingerprint,
                "successful": record.successful,
                "result": record.result,
            },
        )
        return record

    async def find_similar(
        self,
        query: FingerprintInput,
        *,
        exclude_incident_id: uuid.UUID | None = None,
        limit: int = 5,
        correlation_id: str | None = None,
    ) -> list[SimilarIncidentResponse]:
        bounded_limit = min(max(limit, 1), 20)
        statement = (
            select(IncidentMemoryRecord)
            .order_by(IncidentMemoryRecord.resolved_at.desc())
            .limit(500)
        )
        if exclude_incident_id is not None:
            statement = statement.where(IncidentMemoryRecord.incident_id != exclude_incident_id)
        records = list((await self._session.execute(statement)).scalars())
        ranked = [item for record in records if (item := _rank(record, query)).score >= 40]
        ranked.sort(
            key=lambda item: (
                item.score,
                item.record.successful,
                item.record.resolved_at,
            ),
            reverse=True,
        )
        selected = ranked[:bounded_limit]
        if correlation_id is not None:
            await record_audit(
                self._session,
                event_type="INCIDENT_MEMORY_MATCHED",
                correlation_id=correlation_id,
                incident_id=exclude_incident_id,
                result="SUCCEEDED",
                metadata={
                    "matches": len(selected),
                    "fingerprints": [item.record.fingerprint for item in selected],
                },
            )
        return [_response(item) for item in selected]


def _rank(record: IncidentMemoryRecord, query: FingerprintInput) -> RankedMemory:
    canonical = query.canonical()
    query_fingerprint = incident_fingerprint(query)
    score = 0
    reasons: list[str] = []
    if record.service_key != canonical["service"]:
        return RankedMemory(record=record, score=0, reasons=())
    if record.fingerprint == query_fingerprint:
        score += 65
        reasons.append("same fingerprint")
    if record.service_key == canonical["service"]:
        score += 30
        reasons.append("same service")
    if record.incident_type == canonical["incident_type"]:
        score += 20
        reasons.append("same incident type")
    if record.alert_name == canonical["alert_name"]:
        score += 12
        reasons.append("same alert")
    if record.namespace and record.namespace == query.namespace:
        score += 6
        reasons.append("same namespace")
    if record.root_cause_category and record.root_cause_category == query.root_cause_category:
        score += 15
        reasons.append("same root cause")
    if record.successful:
        score += 4
        reasons.append("verified successful outcome")
    return RankedMemory(record=record, score=min(score, 100), reasons=tuple(reasons))


def _response(value: RankedMemory) -> SimilarIncidentResponse:
    record = value.record
    action = ActionType(record.action) if record.action else None
    evidence = redact_untrusted(record.evidence_summary)
    return SimilarIncidentResponse(
        incident_id=record.incident_id,
        fingerprint=record.fingerprint,
        match_score=value.score,
        match_reasons=list(value.reasons),
        service=record.service_key,
        environment=record.environment,
        incident_type=record.incident_type,
        alert_name=record.alert_name,
        root_cause_category=record.root_cause_category,
        runbook_id=record.runbook_id,
        action=action,
        result=record.result,
        verification_success=record.verification_success,
        duration_seconds=record.duration_seconds,
        model=record.model,
        confidence=record.confidence,
        successful=record.successful,
        resolved_at=record.resolved_at,
        evidence_summary=evidence if isinstance(evidence, dict) else {},
        operator_summary=record.operator_summary,
    )
