"""Configuração por ambiente (prefixo AGENT_), lida de variáveis ou do arquivo .env.

`.env` nunca é versionado; `.env.example` mostra as chaves.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_", env_file=(".env", "../.env"), extra="ignore"
    )

    quote_base_url: str = "http://localhost:8000"
    quote_timeout_s: float = 3.0
    quote_max_attempts: int = 3
    quote_budget_s: float = 12.0
    wait_message_after_s: float = 4.0
    breaker_failures: int = 5
    breaker_open_s: float = 30.0

    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    llm_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high"] = "low"
    llm_timeout_s: float = 10.0
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "AGENT_ANTHROPIC_API_KEY")
    )

    db_path: str = "autoseguro.db"  # tabela events (append-only)
    checkpoint_db_path: str = "checkpoints.db"  # estado do LangGraph (mascarado)

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return None if v in ("", None) else v
