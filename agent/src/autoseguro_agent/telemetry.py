"""Telemetria do LLM: tokens, custo e latência por chamada (REQ-80).

Preços em US$ por milhão de tokens (entrada, saída, leitura de cache, escrita de cache).
Fonte: tabela de modelos da Anthropic consultada em 2026-11 (skill claude-api).
Ajuste aqui se o preço mudar; o custo de cada chamada fica gravado no evento.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

LLMCacheStatus = Literal["hit", "miss", "error", "disabled", "none"]

# modelo: (entrada, saída, leitura de cache, escrita de cache) — US$ por 1M tokens
PRICES_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


def cost_usd(
    model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
) -> float:
    p_in, p_out, p_read, p_write = PRICES_PER_MTOK.get(model, (0.0, 0.0, 0.0, 0.0))
    total = (
        input_tokens * p_in + output_tokens * p_out + cache_read * p_read + cache_write * p_write
    )
    return round(total / 1_000_000, 6)


@dataclass(frozen=True)
class LLMCallStats:
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    cache: LLMCacheStatus = "none"
    saved_cost_usd: float = 0.0  # custo da chamada original, evitado num hit
    saved_latency_ms: int = 0

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)
