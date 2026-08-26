"""Central allowlist and immutable metadata for executable action types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.errors import CloudWardError
from app.rbac import Permission


class ActionType(StrEnum):
    DELETE_UNHEALTHY_POD = "DELETE_UNHEALTHY_POD"
    SCALE_STAGING_DEPLOYMENT = "SCALE_STAGING_DEPLOYMENT"
    REVERT_IMAGE = "REVERT_IMAGE"
    APPLY_QUARANTINE = "APPLY_QUARANTINE"
    REMOVE_QUARANTINE = "REMOVE_QUARANTINE"
    CREATE_GITOPS_PR = "CREATE_GITOPS_PR"
    CREATE_TERRAFORM_PR = "CREATE_TERRAFORM_PR"
    CREATE_GITHUB_ISSUE = "CREATE_GITHUB_ISSUE"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    NO_ACTION = "NO_ACTION"


class VerificationStrategy(StrEnum):
    NONE = "none"
    KUBERNETES_AND_HTTP = "kubernetes_and_http"
    DEPLOYMENT_ROLLOUT = "deployment_rollout"
    POLICY_STATE = "policy_state"
    EXTERNAL_RECORD = "external_record"


@dataclass(frozen=True, slots=True)
class ActionMetadata:
    action_type: ActionType
    reversible: bool
    persistent: bool
    allowed_environments: frozenset[str]
    required_permission: Permission
    verification_strategy: VerificationStrategy
    rollback_capable: bool
    implemented: bool = False


ACTION_REGISTRY: dict[ActionType, ActionMetadata] = {
    ActionType.DELETE_UNHEALTHY_POD: ActionMetadata(
        ActionType.DELETE_UNHEALTHY_POD,
        reversible=True,
        persistent=False,
        allowed_environments=frozenset({"local", "staging"}),
        required_permission=Permission.DEMO_TRIGGER,
        verification_strategy=VerificationStrategy.KUBERNETES_AND_HTTP,
        rollback_capable=False,
        implemented=True,
    ),
    ActionType.SCALE_STAGING_DEPLOYMENT: ActionMetadata(
        ActionType.SCALE_STAGING_DEPLOYMENT,
        reversible=True,
        persistent=False,
        allowed_environments=frozenset({"local", "staging"}),
        required_permission=Permission.ACTION_APPROVE_STANDARD,
        verification_strategy=VerificationStrategy.DEPLOYMENT_ROLLOUT,
        rollback_capable=True,
        implemented=True,
    ),
    ActionType.REVERT_IMAGE: ActionMetadata(
        ActionType.REVERT_IMAGE,
        reversible=True,
        persistent=True,
        allowed_environments=frozenset({"local", "staging", "production"}),
        required_permission=Permission.ACTION_APPROVE_HIGHER_RISK,
        verification_strategy=VerificationStrategy.DEPLOYMENT_ROLLOUT,
        rollback_capable=True,
        implemented=True,
    ),
    ActionType.APPLY_QUARANTINE: ActionMetadata(
        ActionType.APPLY_QUARANTINE,
        reversible=True,
        persistent=False,
        allowed_environments=frozenset({"local", "staging", "production"}),
        required_permission=Permission.ACTION_APPROVE_HIGHER_RISK,
        verification_strategy=VerificationStrategy.POLICY_STATE,
        rollback_capable=True,
        implemented=True,
    ),
    ActionType.REMOVE_QUARANTINE: ActionMetadata(
        ActionType.REMOVE_QUARANTINE,
        reversible=True,
        persistent=False,
        allowed_environments=frozenset({"local", "staging", "production"}),
        required_permission=Permission.ACTION_APPROVE_HIGHER_RISK,
        verification_strategy=VerificationStrategy.POLICY_STATE,
        rollback_capable=True,
        implemented=True,
    ),
    ActionType.CREATE_GITOPS_PR: ActionMetadata(
        ActionType.CREATE_GITOPS_PR,
        reversible=True,
        persistent=True,
        allowed_environments=frozenset({"local", "staging", "production"}),
        required_permission=Permission.ACTION_APPROVE_STANDARD,
        verification_strategy=VerificationStrategy.EXTERNAL_RECORD,
        rollback_capable=True,
    ),
    ActionType.CREATE_TERRAFORM_PR: ActionMetadata(
        ActionType.CREATE_TERRAFORM_PR,
        reversible=True,
        persistent=True,
        allowed_environments=frozenset({"local", "staging", "production"}),
        required_permission=Permission.ACTION_APPROVE_HIGHER_RISK,
        verification_strategy=VerificationStrategy.EXTERNAL_RECORD,
        rollback_capable=True,
    ),
    ActionType.CREATE_GITHUB_ISSUE: ActionMetadata(
        ActionType.CREATE_GITHUB_ISSUE,
        reversible=True,
        persistent=True,
        allowed_environments=frozenset({"local", "staging", "production"}),
        required_permission=Permission.ACTION_APPROVE_STANDARD,
        verification_strategy=VerificationStrategy.EXTERNAL_RECORD,
        rollback_capable=True,
    ),
    ActionType.REQUEST_APPROVAL: ActionMetadata(
        ActionType.REQUEST_APPROVAL,
        reversible=True,
        persistent=False,
        allowed_environments=frozenset({"local", "staging", "production"}),
        required_permission=Permission.ACTION_APPROVE_STANDARD,
        verification_strategy=VerificationStrategy.NONE,
        rollback_capable=False,
    ),
    ActionType.NO_ACTION: ActionMetadata(
        ActionType.NO_ACTION,
        reversible=True,
        persistent=False,
        allowed_environments=frozenset({"local", "staging", "production"}),
        required_permission=Permission.PLATFORM_READ,
        verification_strategy=VerificationStrategy.NONE,
        rollback_capable=False,
        implemented=True,
    ),
}


def get_action_metadata(action: ActionType | str) -> ActionMetadata:
    try:
        action_type = action if isinstance(action, ActionType) else ActionType(action)
        return ACTION_REGISTRY[action_type]
    except (ValueError, KeyError) as exc:
        raise CloudWardError(
            "UNKNOWN_ACTION", f"Action {action!s} is not registered", status_code=422
        ) from exc


def require_executable_action(action: ActionType | str, environment: str) -> ActionMetadata:
    metadata = get_action_metadata(action)
    if environment not in metadata.allowed_environments:
        raise CloudWardError(
            "ACTION_ENVIRONMENT_DENIED",
            f"{metadata.action_type.value} is not allowed in {environment}",
            status_code=403,
        )
    if not metadata.implemented:
        raise CloudWardError(
            "ACTION_NOT_IMPLEMENTED",
            f"{metadata.action_type.value} is registered but not executable in Part 1",
            status_code=501,
        )
    return metadata
