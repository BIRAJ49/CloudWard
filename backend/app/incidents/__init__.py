"""Incident management domain."""

from app.incidents.state_machine import IncidentState, transition_incident

__all__ = ["IncidentState", "transition_incident"]
