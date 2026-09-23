import json
import logging

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.logging import JsonFormatter, redact


def test_recursive_redaction() -> None:
    value = redact(
        {
            "authorization": "Bearer secret",
            "nested": {"client_secret": "bad", "safe": "kept"},
            "items": [{"api-key": "bad"}],
        }
    )
    assert value["authorization"] == "[REDACTED]"
    assert value["nested"] == {"client_secret": "[REDACTED]", "safe": "kept"}
    assert value["items"][0]["api-key"] == "[REDACTED]"


def test_json_formatter_emits_required_fields() -> None:
    formatter = JsonFormatter(service="cloudward", environment="test")
    record = logging.LogRecord("module", logging.INFO, __file__, 1, "hello", (), None)
    data = json.loads(formatter.format(record))
    assert {
        "timestamp",
        "level",
        "service",
        "environment",
        "module",
        "message",
        "request_id",
        "correlation_id",
    }.issubset(data)


def test_production_cannot_enable_dev_auth() -> None:
    with pytest.raises(ValidationError, match="development authentication"):
        Settings(
            app_env="production",
            dev_auth_enabled=True,
            session_secret="a" * 40,
            github_client_id="id",
            github_client_secret="secret",
        )


def test_production_requires_oauth_and_strong_session_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", dev_auth_enabled=False)


def test_production_rejects_default_database_credentials() -> None:
    with pytest.raises(ValidationError, match="default DATABASE_URL"):
        Settings(
            app_env="production",
            dev_auth_enabled=False,
            session_secret="a" * 40,
            database_url="postgresql+asyncpg://cloudward:cloudward@postgres:5432/cloudward",
            github_client_id="real-client-id",
            github_client_secret="real-client-secret",
        )


def test_production_rejects_placeholder_oauth_credentials() -> None:
    with pytest.raises(ValidationError, match="placeholder GitHub"):
        Settings(
            app_env="production",
            dev_auth_enabled=False,
            session_secret="a" * 40,
            database_url="postgresql+asyncpg://cloudward:strong@postgres:5432/cloudward",
            github_client_id="replace-me",
            github_client_secret="replace-me",
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("session_secret", "replace-me-with-at-least-32-random-characters"),
        ("alertmanager_webhook_token", "local-" + "b" * 40),
        ("worker_internal_token", "local-" + "c" * 40),
        ("tetragon_webhook_secret", "local-" + "d" * 40),
    ],
)
def test_production_rejects_placeholder_machine_secrets(name: str, value: str) -> None:
    values = {
        "app_env": "production",
        "dev_auth_enabled": False,
        "database_url": "postgresql+asyncpg://cloudward:strong@postgres:5432/cloudward",
        "github_client_id": "real-client-id",
        "github_client_secret": "real-client-secret",
        "session_secret": "a" * 40,
        "alertmanager_webhook_token": "b" * 40,
        "worker_internal_token": "c" * 40,
        "tetragon_webhook_secret": "d" * 40,
    }
    values[name] = value
    with pytest.raises(ValidationError, match=name.upper()):
        Settings(**values)


def test_production_requires_distinct_machine_secrets() -> None:
    with pytest.raises(ValidationError, match="must be distinct"):
        Settings(
            app_env="production",
            dev_auth_enabled=False,
            database_url="postgresql+asyncpg://cloudward:strong@postgres:5432/cloudward",
            github_client_id="real-client-id",
            github_client_secret="real-client-secret",
            session_secret="a" * 40,
            alertmanager_webhook_token="b" * 40,
            worker_internal_token="b" * 40,
            tetragon_webhook_secret="d" * 40,
        )


def test_production_accepts_distinct_configured_machine_secrets() -> None:
    settings = Settings(
        app_env="production",
        dev_auth_enabled=False,
        database_url="postgresql+asyncpg://cloudward:strong@postgres:5432/cloudward",
        github_client_id="real-client-id",
        github_client_secret="real-client-secret",
        session_secret="a" * 40,
        alertmanager_webhook_token="b" * 40,
        worker_internal_token="c" * 40,
        tetragon_webhook_secret="d" * 40,
        local_gitops_write_enabled=False,
    )
    assert settings.app_env == "production"


def test_session_lifetime_cannot_exceed_one_day() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 86400"):
        Settings(app_env="test", session_max_age_seconds=86_401)
