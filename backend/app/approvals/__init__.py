"""Transactional approval queue and stale-action protection."""

from app.approvals.service import ApprovalService, ensure_runtime_approval

__all__ = ["ApprovalService", "ensure_runtime_approval"]
