import pytest

from app.errors import CloudWardError
from app.rbac import Permission, Role, has_permission
from app.remediation.actions import ActionType, get_action_metadata, require_executable_action


def test_registry_has_metadata_for_every_action() -> None:
    for action in ActionType:
        metadata = get_action_metadata(action)
        assert metadata.action_type == action
        assert metadata.allowed_environments
        assert metadata.verification_strategy


def test_unknown_action_is_rejected() -> None:
    with pytest.raises(CloudWardError) as caught:
        get_action_metadata("SHELL_COMMAND")
    assert caught.value.code == "UNKNOWN_ACTION"


def test_production_pod_deletion_is_rejected() -> None:
    with pytest.raises(CloudWardError) as caught:
        require_executable_action(ActionType.DELETE_UNHEALTHY_POD, "production")
    assert caught.value.code == "ACTION_ENVIRONMENT_DENIED"


def test_registered_but_unimplemented_action_is_not_executable() -> None:
    with pytest.raises(CloudWardError) as caught:
        require_executable_action(ActionType.CREATE_TERRAFORM_PR, "staging")
    assert caught.value.code == "ACTION_NOT_IMPLEMENTED"


def test_rbac_role_matrix() -> None:
    assert has_permission(Role.VIEWER, Permission.INCIDENT_READ)
    assert not has_permission(Role.VIEWER, Permission.ACTION_APPROVE_STANDARD)
    assert has_permission(Role.OPERATOR, Permission.ACTION_APPROVE_STANDARD)
    assert not has_permission(Role.OPERATOR, Permission.ROLE_MANAGE)
    assert all(has_permission(Role.ADMIN, permission) for permission in Permission)
