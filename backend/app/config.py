"""Centralized, typed application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PUBLIC_PLACEHOLDER = "replace-me"


class Settings(BaseSettings):
    """CloudWard settings loaded from environment variables.

    Defaults are deliberately suitable only for a local Compose network. Production
    environments must provide secrets and cannot enable the development identity path.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    app_env: Literal["development", "test", "staging", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    app_name: str = Field(default="CloudWard API", alias="APP_NAME")
    app_version: str = Field(default="0.5.0", alias="APP_VERSION")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(
        default="postgresql+asyncpg://cloudward:cloudward@postgres:5432/cloudward",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    opa_url: AnyHttpUrl = Field(default=AnyHttpUrl("http://opa:8181"), alias="OPA_URL")
    opa_decision_path: str = Field(
        default="/v1/data/cloudward/remediation/decision", alias="OPA_DECISION_PATH"
    )
    opa_chaos_decision_path: str = Field(
        default="/v1/data/cloudward/chaos/decision", alias="OPA_CHAOS_DECISION_PATH"
    )
    github_client_id: str | None = Field(default=None, alias="GITHUB_CLIENT_ID")
    github_client_secret: SecretStr | None = Field(default=None, alias="GITHUB_CLIENT_SECRET")
    github_redirect_uri: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://localhost:8000/api/v1/auth/github/callback"),
        alias="GITHUB_REDIRECT_URI",
    )
    frontend_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://localhost:5173"), alias="FRONTEND_URL"
    )
    session_secret: SecretStr = Field(
        default=SecretStr("local-development-session-secret-change-me"),
        alias="SESSION_SECRET",
    )
    aws_region: str = Field(default="eu-north-1", alias="AWS_REGION")
    teams_webhook_url: str | None = Field(default=None, alias="TEAMS_WEBHOOK_URL")
    session_cookie_name: str = Field(default="cloudward_session", alias="SESSION_COOKIE_NAME")
    session_max_age_seconds: int = Field(
        default=28_800, alias="SESSION_MAX_AGE_SECONDS", ge=300, le=86_400
    )
    dev_auth_enabled: bool = Field(default=False, alias="DEV_AUTH_ENABLED")
    cors_origins: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")
    runbooks_path: Path = Field(default=Path("/app/runbooks"), alias="RUNBOOKS_PATH")
    kubernetes_context: str | None = Field(default=None, alias="KUBERNETES_CONTEXT")
    kubernetes_allowed_namespaces: str = Field(
        default="cloudward-staging", alias="KUBERNETES_ALLOWED_NAMESPACES"
    )
    inventory_bootstrap_enabled: bool = Field(default=False, alias="INVENTORY_BOOTSTRAP_ENABLED")
    cluster_agent_enabled: bool = Field(default=False, alias="CLUSTER_AGENT_ENABLED")
    cluster_agent_cluster_id: UUID | None = Field(default=None, alias="CLUSTER_AGENT_CLUSTER_ID")
    cluster_agent_token: SecretStr = Field(default=SecretStr(""), alias="CLUSTER_AGENT_TOKEN")
    cluster_agent_freshness_seconds: int = Field(
        default=180, ge=60, le=600, alias="CLUSTER_AGENT_FRESHNESS_SECONDS"
    )
    inventory_cluster_name: str = Field(
        default="cloudward-aws", alias="INVENTORY_CLUSTER_NAME", min_length=3, max_length=255
    )
    inventory_cluster_context: str = Field(
        default="cloudward-eks", alias="INVENTORY_CLUSTER_CONTEXT", min_length=1, max_length=255
    )
    inventory_cluster_environment: Literal["staging", "production"] = Field(
        default="production", alias="INVENTORY_CLUSTER_ENVIRONMENT"
    )
    inventory_aws_region: str = Field(
        default="eu-north-1", alias="INVENTORY_AWS_REGION", min_length=9, max_length=32
    )
    verification_timeout_seconds: float = Field(
        default=120.0, alias="VERIFICATION_TIMEOUT_SECONDS", ge=1, le=600
    )
    verification_poll_seconds: float = Field(
        default=2.0, alias="VERIFICATION_POLL_SECONDS", ge=0.05, le=30
    )
    max_remediation_attempts: int = Field(default=3, alias="MAX_REMEDIATION_ATTEMPTS", ge=1, le=3)
    alertmanager_webhook_token: SecretStr = Field(
        default=SecretStr("local-alertmanager-token-change-me"),
        alias="ALERTMANAGER_WEBHOOK_TOKEN",
    )
    worker_internal_token: SecretStr = Field(
        default=SecretStr("local-worker-token-change-me"), alias="WORKER_INTERNAL_TOKEN"
    )
    prometheus_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://prometheus.observability.svc.cluster.local:9090"),
        alias="PROMETHEUS_URL",
    )
    loki_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://loki.observability.svc.cluster.local:3100"),
        alias="LOKI_URL",
    )
    tempo_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://tempo.observability.svc.cluster.local:3200"),
        alias="TEMPO_URL",
    )
    telemetry_timeout_seconds: float = Field(
        default=8.0, alias="TELEMETRY_TIMEOUT_SECONDS", ge=0.5, le=30
    )
    telemetry_max_samples: int = Field(default=50, alias="TELEMETRY_MAX_SAMPLES", ge=1, le=200)
    evidence_before_seconds: int = Field(
        default=300, alias="EVIDENCE_BEFORE_SECONDS", ge=60, le=1800
    )
    evidence_after_seconds: int = Field(default=180, alias="EVIDENCE_AFTER_SECONDS", ge=60, le=600)
    alert_replay_tolerance_seconds: int = Field(
        default=300, alias="ALERT_REPLAY_TOLERANCE_SECONDS", ge=30, le=900
    )
    incident_lab_namespace: str = Field(default="cloudward-staging", alias="INCIDENT_LAB_NAMESPACE")
    incident_lab_required_label: str = Field(
        default="cloudward.io/demo-target=true", alias="INCIDENT_LAB_REQUIRED_LABEL"
    )
    chaos_max_runtime_seconds: int = Field(
        default=300, alias="CHAOS_MAX_RUNTIME_SECONDS", ge=30, le=600
    )
    max_temporary_replicas: int = Field(default=5, alias="MAX_TEMPORARY_REPLICAS", ge=2, le=20)
    automatic_rollback_max_risk: int = Field(
        default=30, alias="AUTOMATIC_ROLLBACK_MAX_RISK", ge=0, le=30
    )
    local_gitops_write_enabled: bool = Field(default=False, alias="LOCAL_GITOPS_WRITE_ENABLED")
    local_gitops_repo_url: str = Field(
        default="git://host.docker.internal:19418/cloudward-gitops.git",
        alias="LOCAL_GITOPS_REPO_URL",
    )
    local_gitops_timeout_seconds: float = Field(
        default=20.0, alias="LOCAL_GITOPS_TIMEOUT_SECONDS", ge=5, le=60
    )
    tetragon_webhook_secret: SecretStr = Field(
        default=SecretStr("local-tetragon-webhook-secret-change-me"),
        alias="TETRAGON_WEBHOOK_SECRET",
    )
    tetragon_webhook_max_body_bytes: int = Field(
        default=131_072, alias="TETRAGON_WEBHOOK_MAX_BODY_BYTES", ge=1024, le=1_048_576
    )
    tetragon_webhook_max_events_per_minute: int = Field(
        default=120, alias="TETRAGON_WEBHOOK_MAX_EVENTS_PER_MINUTE", ge=1, le=10_000
    )
    tetragon_webhook_max_clock_skew_seconds: int = Field(
        default=300, alias="TETRAGON_WEBHOOK_MAX_CLOCK_SKEW_SECONDS", ge=30, le=900
    )
    security_dedup_window_seconds: int = Field(
        default=60, alias="SECURITY_DEDUP_WINDOW_SECONDS", ge=10, le=3600
    )
    security_quarantine_verify_timeout_seconds: float = Field(
        default=30.0,
        alias="SECURITY_QUARANTINE_VERIFY_TIMEOUT_SECONDS",
        ge=1,
        le=120,
    )
    security_quarantine_verify_poll_seconds: float = Field(
        default=1.0,
        alias="SECURITY_QUARANTINE_VERIFY_POLL_SECONDS",
        ge=0.1,
        le=10,
    )
    opencost_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://opencost.opencost.svc.cluster.local:9003"),
        alias="OPENCOST_URL",
    )
    finops_provider_timeout_seconds: float = Field(
        default=8.0, alias="FINOPS_PROVIDER_TIMEOUT_SECONDS", ge=1, le=30
    )
    finops_max_response_bytes: int = Field(
        default=1_048_576, alias="FINOPS_MAX_RESPONSE_BYTES", ge=65_536, le=8_388_608
    )
    finops_max_samples: int = Field(default=1000, alias="FINOPS_MAX_SAMPLES", ge=10, le=5000)
    finops_demo_observation_window_seconds: int = Field(
        default=1800, alias="FINOPS_DEMO_OBSERVATION_WINDOW_SECONDS", ge=900, le=86_400
    )
    finops_demo_minimum_window_seconds: int = Field(
        default=900, alias="FINOPS_DEMO_MINIMUM_WINDOW_SECONDS", ge=300, le=86_400
    )
    finops_production_minimum_window_seconds: int = Field(
        default=604_800,
        alias="FINOPS_PRODUCTION_MINIMUM_WINDOW_SECONDS",
        ge=86_400,
        le=2_592_000,
    )
    finops_query_step_seconds: int = Field(
        default=60, alias="FINOPS_QUERY_STEP_SECONDS", ge=15, le=3600
    )
    finops_minimum_samples: int = Field(default=5, alias="FINOPS_MINIMUM_SAMPLES", ge=5, le=100)
    finops_minimum_window_coverage: float = Field(
        default=0.8, alias="FINOPS_MINIMUM_WINDOW_COVERAGE", ge=0.5, le=1.0
    )
    finops_cpu_headroom_factor: float = Field(
        default=1.5, alias="FINOPS_CPU_HEADROOM_FACTOR", ge=1.1, le=3.0
    )
    finops_memory_headroom_factor: float = Field(
        default=1.35, alias="FINOPS_MEMORY_HEADROOM_FACTOR", ge=1.1, le=3.0
    )
    finops_minimum_cpu_millicores: int = Field(
        default=50, alias="FINOPS_MINIMUM_CPU_MILLICORES", ge=10, le=1000
    )
    finops_minimum_memory_mib: int = Field(
        default=64, alias="FINOPS_MINIMUM_MEMORY_MIB", ge=16, le=4096
    )
    finops_minimum_reduction_percent: int = Field(
        default=20, alias="FINOPS_MINIMUM_REDUCTION_PERCENT", ge=5, le=60
    )
    finops_node_request_threshold: float = Field(
        default=0.45, alias="FINOPS_NODE_REQUEST_THRESHOLD", ge=0.1, le=0.9
    )
    finops_node_usage_threshold: float = Field(
        default=0.35, alias="FINOPS_NODE_USAGE_THRESHOLD", ge=0.05, le=0.9
    )
    finops_recommendation_ttl_seconds: int = Field(
        default=86_400, alias="FINOPS_RECOMMENDATION_TTL_SECONDS", ge=900, le=2_592_000
    )
    finops_demo_namespace: str = Field(default="cloudward-staging", alias="FINOPS_DEMO_NAMESPACE")
    finops_demo_deployment: str = Field(default="cloudward-demo", alias="FINOPS_DEMO_DEPLOYMENT")
    finops_demo_pod_pattern: str = Field(
        default="cloudward-demo-.*", alias="FINOPS_DEMO_POD_PATTERN"
    )
    finops_gitops_repository: str = Field(
        default="biraj49/cloudward-gitops", alias="FINOPS_GITOPS_REPOSITORY"
    )
    finops_gitops_values_path: str = Field(
        default="cloudward-gitops/environments/staging/values.yaml",
        alias="FINOPS_GITOPS_VALUES_PATH",
    )
    approval_ttl_seconds: int = Field(default=1800, alias="APPROVAL_TTL_SECONDS", ge=60, le=86_400)
    teams_workflow_webhook_url: SecretStr | None = Field(
        default=None, alias="TEAMS_WORKFLOW_WEBHOOK_URL"
    )
    teams_dashboard_url: AnyHttpUrl | None = Field(default=None, alias="TEAMS_DASHBOARD_URL")
    notification_timeout_seconds: float = Field(
        default=8.0, alias="NOTIFICATION_TIMEOUT_SECONDS", ge=1, le=30
    )
    notification_max_attempts: int = Field(
        default=5, alias="NOTIFICATION_MAX_ATTEMPTS", ge=1, le=10
    )
    notification_events: str = Field(
        default=(
            "critical_incident_detected,approval_required,security_containment_executed,"
            "remediation_failed,incident_escalated,incident_resolved"
        ),
        alias="NOTIFICATION_EVENTS",
    )
    ai_diagnosis_enabled: bool = Field(default=False, alias="CLOUDWARD_AI_DIAGNOSIS_ENABLED")
    cloudward_llm_primary_model: str = Field(
        default="openai/gpt-5.6-terra",
        alias="CLOUDWARD_LLM_PRIMARY_MODEL",
        min_length=3,
        max_length=255,
    )
    cloudward_llm_fallback_model: str = Field(
        default="google/gemini-3.5-flash-lite",
        alias="CLOUDWARD_LLM_FALLBACK_MODEL",
        min_length=3,
        max_length=255,
    )
    cloudward_llm_escalation_model: str = Field(
        default="openai/gpt-5.6-sol",
        alias="CLOUDWARD_LLM_ESCALATION_MODEL",
        min_length=3,
        max_length=255,
    )
    openrouter_api_key: SecretStr | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_primary_model: str = Field(
        default="anthropic/claude-3.7-sonnet",
        alias="OPENROUTER_PRIMARY_MODEL",
        min_length=3,
        max_length=255,
    )
    openrouter_fallback_model: str = Field(
        default="openai/gpt-4o",
        alias="OPENROUTER_FALLBACK_MODEL",
        min_length=3,
        max_length=255,
    )
    openrouter_timeout_seconds: float = Field(
        default=30.0, alias="OPENROUTER_TIMEOUT_SECONDS", ge=1, le=120
    )
    openrouter_max_retries: int = Field(default=2, alias="OPENROUTER_MAX_RETRIES", ge=0, le=3)
    openrouter_max_context_tokens: int = Field(
        default=16_000,
        alias="OPENROUTER_MAX_CONTEXT_TOKENS",
        ge=512,
        le=131_072,
    )
    ai_max_evidence_chars: int = Field(
        default=60_000, alias="AI_MAX_EVIDENCE_CHARS", ge=5_000, le=60_000
    )
    ai_max_model_calls_per_incident: int = Field(
        default=3, alias="AI_MAX_MODEL_CALLS_PER_INCIDENT", ge=1, le=3
    )
    ai_circuit_breaker_failure_threshold: int = Field(
        default=5, alias="AI_CIRCUIT_BREAKER_FAILURE_THRESHOLD", ge=2, le=20
    )
    ai_circuit_breaker_window_seconds: int = Field(
        default=300, alias="AI_CIRCUIT_BREAKER_WINDOW_SECONDS", ge=30, le=3600
    )
    github_app_id: int | None = Field(default=None, alias="GITHUB_APP_ID", ge=1)
    github_app_installation_id: int | None = Field(
        default=None, alias="GITHUB_APP_INSTALLATION_ID", ge=1
    )
    github_app_private_key: SecretStr | None = Field(default=None, alias="GITHUB_APP_PRIVATE_KEY")
    github_app_read_repositories: str = Field(
        default="", alias="GITHUB_APP_READ_REPOSITORIES", max_length=10_000
    )
    github_app_issue_repositories: str = Field(
        default="", alias="GITHUB_APP_ISSUE_REPOSITORIES", max_length=10_000
    )
    github_app_write_allowlist: str = Field(
        default="{}", alias="GITHUB_APP_WRITE_ALLOWLIST", max_length=50_000
    )

    @field_validator("cluster_agent_cluster_id", mode="before")
    @classmethod
    def empty_agent_cluster_id(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("opa_decision_path", "opa_chaos_decision_path")
    @classmethod
    def validate_opa_path(cls, value: str) -> str:
        if not value.startswith("/v1/data/"):
            raise ValueError("OPA_DECISION_PATH must be an OPA data API path")
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("unsupported log level")
        return normalized

    @field_validator("teams_workflow_webhook_url", mode="before")
    @classmethod
    def normalize_optional_teams_webhook(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("github_app_id", "github_app_installation_id", mode="before")
    @classmethod
    def normalize_optional_github_app_ids(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator(
        "cloudward_llm_primary_model",
        "cloudward_llm_fallback_model",
        "cloudward_llm_escalation_model",
    )
    @classmethod
    def validate_model_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if "/" not in normalized or any(character.isspace() for character in normalized):
            raise ValueError("LLM model identifiers must use provider/model form")
        return normalized

    @model_validator(mode="after")
    def validate_environment_safety(self) -> Settings:
        if self.app_env in {"staging", "production"}:
            if self.dev_auth_enabled:
                raise ValueError("development authentication cannot be enabled outside local/test")
            if not self.github_client_id or not self.github_client_secret:
                raise ValueError("GitHub OAuth credentials are required outside local development")
            oauth_secret = self.github_client_secret.get_secret_value()
            if self.github_client_id == PUBLIC_PLACEHOLDER or oauth_secret == PUBLIC_PLACEHOLDER:
                raise ValueError("placeholder GitHub OAuth credentials are forbidden")
            if "cloudward:cloudward@postgres" in self.database_url:
                raise ValueError("the local default DATABASE_URL is forbidden outside development")
            protected = {
                "SESSION_SECRET": self.session_secret,
                "ALERTMANAGER_WEBHOOK_TOKEN": self.alertmanager_webhook_token,
                "WORKER_INTERNAL_TOKEN": self.worker_internal_token,
                "TETRAGON_WEBHOOK_SECRET": self.tetragon_webhook_secret,
            }
            if self.cluster_agent_enabled:
                protected["CLUSTER_AGENT_TOKEN"] = self.cluster_agent_token
            values = [secret.get_secret_value() for secret in protected.values()]
            for name, protected_secret in protected.items():
                value = protected_secret.get_secret_value()
                if len(value) < 32 or any(
                    marker in value.lower()
                    for marker in ("change-me", "replace-me", "local-", "development")
                ):
                    raise ValueError(f"a unique, non-placeholder {name} is required")
            if len(set(values)) != len(values):
                raise ValueError("authentication and ingestion secrets must be distinct")
            if self.ai_diagnosis_enabled:
                if self.openrouter_api_key is None:
                    raise ValueError("OPENROUTER_API_KEY is required when AI diagnosis is enabled")
                ai_key = self.openrouter_api_key.get_secret_value()
                if not ai_key or "replace-me" in ai_key:
                    raise ValueError("placeholder OPENROUTER_API_KEY is forbidden")
        if self.cluster_agent_enabled:
            token = self.cluster_agent_token.get_secret_value()
            if (
                self.cluster_agent_cluster_id is None
                or len(token) < 32
                or "replace-me" in token
                or "change-me" in token
            ):
                raise ValueError(
                    "cluster agent intake requires a registered cluster ID and a strong dedicated token"
                )
            if token in {
                self.worker_internal_token.get_secret_value(),
                self.alertmanager_webhook_token.get_secret_value(),
            }:
                raise ValueError("cluster agent must not share a worker or webhook token")
        if self.incident_lab_namespace != "cloudward-staging":
            raise ValueError("Incident Lab may target only cloudward-staging")
        if self.incident_lab_required_label != "cloudward.io/demo-target=true":
            raise ValueError("Incident Lab requires the immutable demo-target label selector")
        if self.finops_demo_namespace != "cloudward-staging":
            raise ValueError("FinOps demo analysis may target only cloudward-staging")
        if self.inventory_bootstrap_enabled and self.inventory_aws_region != "eu-north-1":
            raise ValueError("Part 4 configured inventory must target eu-north-1")
        if self.finops_gitops_values_path != "cloudward-gitops/environments/staging/values.yaml":
            raise ValueError("FINOPS_GITOPS_VALUES_PATH must be the fixed staging values file")
        if self.local_gitops_write_enabled:
            if self.app_env not in {"development", "test"}:
                raise ValueError("the writable local GitOps source is forbidden outside local/test")
            if self.local_gitops_repo_url != (
                "git://host.docker.internal:19418/cloudward-gitops.git"
            ):
                raise ValueError("LOCAL_GITOPS_REPO_URL must be the fixed loopback k3d demo source")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_namespaces(self) -> frozenset[str]:
        return frozenset(
            namespace.strip()
            for namespace in self.kubernetes_allowed_namespaces.split(",")
            if namespace.strip()
        )

    @property
    def secure_cookies(self) -> bool:
        return self.app_env in {"staging", "production"}

    @property
    def denied_chaos_namespaces(self) -> frozenset[str]:
        return frozenset(
            {
                "cloudward-production",
                "kube-system",
                "argocd",
                "observability",
                "kyverno",
                "tetragon",
                "chaos-mesh",
            }
        )

    @property
    def enabled_notification_events(self) -> frozenset[str]:
        return frozenset(
            event.strip() for event in self.notification_events.split(",") if event.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
