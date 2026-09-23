"""Standalone agent settings: no database, worker, OAuth, or cloud credentials."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.cluster_agent.schemas import AgentTarget


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore", populate_by_name=True)

    environment: Literal["development", "test", "staging", "production"] = "production"
    cluster_id: UUID
    control_plane_url: str
    token: SecretStr
    targets: list[AgentTarget] = Field(min_length=1, max_length=4)
    interval_seconds: int = Field(default=30, ge=15, le=120)
    timeout_seconds: float = Field(default=8, ge=1, le=15)
    prometheus_url: str = "http://prometheus.observability.svc.cluster.local:9090"
    loki_url: str = "http://loki.observability.svc.cluster.local:3100"
    tempo_url: str = "http://tempo.observability.svc.cluster.local:3200"
    opencost_url: str = "http://opencost.opencost.svc.cluster.local:9003"
    state_directory: Path = Path("/var/run/cloudward-agent")

    @model_validator(mode="after")
    def boundaries(self) -> "AgentSettings":
        token = self.token.get_secret_value()
        if len(token) < 32 or "replace-me" in token or "change-me" in token:
            raise ValueError("a strong, dedicated agent token is required")
        origin = urlsplit(self.control_plane_url)
        local = self.environment in {"development", "test"}
        if (
            not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.query
            or origin.fragment
            or origin.path not in {"", "/"}
            or (
                origin.scheme != "https"
                and not (
                    local
                    and origin.scheme == "http"
                    and origin.hostname
                    in {
                        "api",
                        "localhost",
                        "127.0.0.1",
                        "host.k3d.internal",
                        "host.docker.internal",
                    }
                )
            )
        ):
            raise ValueError(
                "control plane must be an HTTPS origin; local HTTP is development-only"
            )
        for endpoint in (self.prometheus_url, self.loki_url, self.tempo_url, self.opencost_url):
            url = urlsplit(endpoint)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or url.path not in {"", "/"}
                or not (
                    url.hostname.endswith(".svc.cluster.local")
                    or (local and url.hostname in {"localhost", "127.0.0.1"})
                )
            ):
                raise ValueError("telemetry endpoints must be cluster-local HTTP origins")
        targets = [(item.namespace, item.service) for item in self.targets]
        if len(targets) != len(set(targets)):
            raise ValueError("duplicate agent targets")
        return self
