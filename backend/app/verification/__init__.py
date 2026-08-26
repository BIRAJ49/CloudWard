"""Multi-signal verification foundation."""

from app.verification.engine import VerificationEngine, VerificationResult
from app.verification.multisignal import (
    MultiSignalResult,
    MultiSignalVerificationEngine,
    SignalCheck,
    SignalType,
    VerificationPlan,
    persist_verification,
)

__all__ = [
    "MultiSignalResult",
    "MultiSignalVerificationEngine",
    "SignalCheck",
    "SignalType",
    "VerificationEngine",
    "VerificationPlan",
    "VerificationResult",
    "persist_verification",
]
