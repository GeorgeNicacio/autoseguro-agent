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

    # --- fase 4: cache, fila e custos ---
    redis_url: str | None = None  # sem Redis: cache desligado e fila executada na hora
    golden_quote_url: str = "http://localhost:8002"
    quote_cache_ttl_s: int = 3600
    rules_cache_ttl_s: int = 600
    llm_cache_ttl_s: int = 86_400
    hot_threshold: int = 3  # hits a partir dos quais a chave vira "quente"
    hot_ttl_s: int = 7 * 86_400  # TTL estendido das chaves quentes
    quote_retry_delays_s: str = "60,300,900"  # retry da cotação depois do handoff

    db_path: str = "autoseguro.db"  # tabela events (append-only)
    checkpoint_db_path: str = "checkpoints.db"  # estado do LangGraph (mascarado)

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    @property
    def retry_delays(self) -> list[int]:
        return [int(x) for x in self.quote_retry_delays_s.split(",") if x.strip()]
