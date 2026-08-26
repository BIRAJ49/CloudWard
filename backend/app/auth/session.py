"""Signed session and OAuth state tokens; no provider tokens are stored in cookies."""

from __future__ import annotations

from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth.schemas import Principal
from app.config import Settings
from app.errors import CloudWardError


class SessionSigner:
    def __init__(self, settings: Settings) -> None:
        secret = settings.session_secret.get_secret_value()
        self.max_age = settings.session_max_age_seconds
        self._session = URLSafeTimedSerializer(secret, salt="cloudward-session-v1")
        self._oauth_state = URLSafeTimedSerializer(secret, salt="cloudward-github-state-v1")

    def sign_principal(self, principal: Principal) -> str:
        return self._session.dumps(principal.model_dump(mode="json"))

    def read_principal(self, value: str) -> Principal:
        try:
            payload = self._session.loads(value, max_age=self.max_age)
            return Principal.model_validate(payload)
        except (BadSignature, SignatureExpired, ValueError) as exc:
            raise CloudWardError(
                "INVALID_SESSION", "Authentication session is invalid or expired", status_code=401
            ) from exc

    def sign_oauth_state(self, payload: dict[str, Any]) -> str:
        return self._oauth_state.dumps(payload)

    def read_oauth_state(self, state: str) -> dict[str, Any]:
        try:
            payload = self._oauth_state.loads(state, max_age=600)
        except (BadSignature, SignatureExpired) as exc:
            raise CloudWardError(
                "INVALID_OAUTH_STATE", "OAuth state is invalid or expired", status_code=401
            ) from exc
        if not isinstance(payload, dict):
            raise CloudWardError("INVALID_OAUTH_STATE", "OAuth state payload is invalid")
        return payload
