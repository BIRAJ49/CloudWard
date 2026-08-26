"""Role-based authorization."""

from app.rbac.policy import Permission, Role, has_permission, require_permission

__all__ = ["Permission", "Role", "has_permission", "require_permission"]
