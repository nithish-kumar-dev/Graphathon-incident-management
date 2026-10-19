"""Runtime settings, read from the environment or .env. No secrets have defaults."""

from __future__ import annotations

import re
from functools import lru_cache

from psycopg.conninfo import conninfo_to_dict
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.graph.schema import ENV_VALUES, TENANT_PATTERN

# The only Postgres database this project may touch. The host's Postgres.app on :5432
# holds unrelated databases (docs/current-state-audit.md §5.1).
REQUIRED_PG_DATABASE = "graphathon"
GRAPH_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


class Settings(BaseSettings):
    # hide_input_in_errors: a rejected POSTGRES_DSN must not echo its password into logs.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      hide_input_in_errors=True)

    falkordb_url: str = "redis://127.0.0.1:56379"
    graph_name: str = "graphathon"
    graph_query_timeout_ms: int = Field(default=2000, ge=100, le=30_000)
    alert_dedup_window_s: int = Field(default=900, ge=60, le=86_400)
    alert_max_age_s: int = Field(default=7 * 86_400, ge=3600, le=90 * 86_400)
    alert_max_future_skew_s: int = Field(default=300, ge=0, le=3600)
    max_request_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    log_level: str = "INFO"
    postgres_dsn: SecretStr
    tenant_allowlist: str = "nova"
    default_tenant: str = "nova"
    default_env: str = "prod"

    # Phase 3 hybrid retrieval. "none" = graph + keyword only (also the automatic fallback).
    embedding_provider: str = "none"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = Field(default=768, ge=8, le=4096)
    embedding_timeout_s: float = Field(default=5.0, gt=0, le=60)
    retrieval_allowed_classifications: str = "public,internal"

    llm_provider: str = "stub"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"
    ollama_base_url: str = "http://127.0.0.1:11434"                # still used by the Ollama embedder
    # ollama_model: str = ""                                       # Ollama investigator disabled
    llm_timeout_s: float = Field(default=90.0, gt=0, le=600)
    llm_fallback_to_stub: bool = True                              # labelled "stub-fallback(...)" when used

    # Phase 4 orchestration
    orchestrator_enabled: bool = False                             # in-process worker; .env turns it on
    orchestrator_poll_s: float = Field(default=2.0, gt=0, le=60)
    max_investigation_revisions: int = Field(default=2, ge=0, le=5)
    branch_timeout_s: float = Field(default=20.0, gt=0, le=300)

    # Phase 6: demo-only endpoints that flip two graph edges. Off unless a demo environment asks for it.
    demo_controls_enabled: bool = False

    # Graph data prepared when the API starts (app/seeds/startup.py): "none", "seed" or "reset".
    startup_data: str = "none"

    @field_validator("graph_name")
    @classmethod
    def _graph_name(cls, v: str) -> str:
        if not GRAPH_NAME_PATTERN.match(v):
            raise ValueError("graph_name must match ^[a-z][a-z0-9_]{2,40}$")
        return v

    @field_validator("postgres_dsn")
    @classmethod
    def _dsn_guard(cls, v: SecretStr) -> SecretStr:
        check_postgres_dsn(v.get_secret_value())
        return v

    @field_validator("default_env")
    @classmethod
    def _env(cls, v: str) -> str:
        if v not in ENV_VALUES:
            raise ValueError(f"default_env must be one of {sorted(ENV_VALUES)}")
        return v

    @field_validator("llm_provider")
    @classmethod
    def _llm(cls, v: str) -> str:
        if v not in {"stub", "gemini"}:
            raise ValueError("llm_provider must be 'stub' or 'gemini'")
        return v

    @field_validator("startup_data")
    @classmethod
    def _startup_data(cls, v: str) -> str:
        if v not in {"none", "seed", "reset"}:
            raise ValueError("startup_data must be 'none', 'seed' or 'reset'")
        return v

    @field_validator("embedding_provider")
    @classmethod
    def _emb(cls, v: str) -> str:
        if v not in {"none", "ollama"}:
            raise ValueError("embedding_provider must be 'none' or 'ollama'")
        return v

    @property
    def allowed_classifications(self) -> frozenset[str]:
        return frozenset(c.strip() for c in self.retrieval_allowed_classifications.split(",") if c.strip())

    @property
    def tenants(self) -> frozenset[str]:
        tenants = frozenset(t.strip() for t in self.tenant_allowlist.split(",") if t.strip())
        bad = [t for t in tenants if not TENANT_PATTERN.match(t)]
        if bad:
            raise ValueError(f"invalid tenant ids in TENANT_ALLOWLIST: {bad}")
        return tenants


def check_postgres_dsn(dsn: str) -> None:
    """Refuse any DSN that does not target the project's own database."""
    try:
        params = conninfo_to_dict(dsn)
    except Exception as exc:
        raise ValueError("POSTGRES_DSN is not a valid libpq connection string") from exc
    if params.get("dbname") != REQUIRED_PG_DATABASE:
        raise ValueError(f"POSTGRES_DSN must target database {REQUIRED_PG_DATABASE!r}")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
