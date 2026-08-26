import pytest

from app.errors import CloudWardError
from app.incidents.state_machine import ALLOWED_TRANSITIONS, IncidentState, transition_incident


@pytest.mark.parametrize(
    ("current", "targets"),
    [(state, targets) for state, targets in ALLOWED_TRANSITIONS.items()],
)
def test_every_declared_transition_is_allowed(
    current: IncidentState, targets: frozenset[IncidentState]
) -> None:
    for target in targets:
        assert transition_incident(current, target) == target


def test_all_undeclared_transitions_are_rejected() -> None:
    for current in IncidentState:
        for target in IncidentState:
            if target not in ALLOWED_TRANSITIONS[current]:
                with pytest.raises(CloudWardError) as caught:
                    transition_incident(current, target)
                assert caught.value.code == "INVALID_INCIDENT_TRANSITION"


def test_resolved_cannot_execute() -> None:
    with pytest.raises(CloudWardError, match="RESOLVED to EXECUTING"):
        transition_incident(IncidentState.RESOLVED, IncidentState.EXECUTING)
