"""Backend-enforced RBAC policy."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import Depends

from app.errors import CloudWardError


class Role(StrEnum):
    VIEWER = "Viewer"
    OPERATOR = "Operator"
    ADMIN = "Admin"


class Permission(StrEnum):
    PLATFORM_READ = "platform:read"
    INCIDENT_READ = "incident:read"
    AUDIT_READ = "audit:read"
    INCIDENT_CREATE = "incident:create"
    ACTION_APPROVE_STANDARD = "action:approve-standard"
    ACTION_REJECT = "action:reject"
    DEMO_TRIGGER = "demo:trigger"
    ROLE_MANAGE = "role:manage"
    SETTINGS_MANAGE = "settings:manage"
    POLICY_MANAGE = "policy:manage"
    ACTION_APPROVE_HIGHER_RISK = "action:approve-higher-risk"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(
        {Permission.PLATFORM_READ, Permission.INCIDENT_READ, Permission.AUDIT_READ}
    ),
    Role.OPERATOR: frozenset(
        {
            Permission.PLATFORM_READ,
            Permission.INCIDENT_READ,
            Permission.AUDIT_READ,
            Permission.INCIDENT_CREATE,
            Permission.ACTION_APPROVE_STANDARD,
            Permission.ACTION_REJECT,
            Permission.DEMO_TRIGGER,
        }
    ),
    Role.ADMIN: frozenset(Permission),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def require_permission(permission: Permission):  # type: ignore[no-untyped-def]
    """Return a FastAPI dependency that checks the resolved authenticated principal."""

    from app.auth.dependencies import get_current_principal

    async def dependency(
        principal: Any = Depends(get_current_principal),
    ) -> Any:
        if not has_permission(principal.role, permission):
            raise CloudWardError(
                "FORBIDDEN",
                f"Role {principal.role.value} lacks permission {permission.value}",
                status_code=403,
            )
        return principal

    return dependency
