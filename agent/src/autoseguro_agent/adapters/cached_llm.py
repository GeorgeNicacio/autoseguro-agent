"""Cache de extração em volta do LLMClient (decorator · REQ-74, 75, 77).

Muitas mensagens de lead se repetem quase iguais entre conversas ("oi", "35",
"completo", "quero falar com um atendente"). Como o texto chega MASCARADO, a mesma
resposta curta gera a mesma chave em conversas diferentes, sem dado pessoal na chave
nem no valor. Um hit custa zero token e responde em milissegundos.

Chave: versão do prompt + modelo + texto mascarado normalizado + dado esperado + data.
Fora da chave, de propósito: os dados já coletados (mais hits; a extração da mensagem
quase não depende deles). Trade-off registrado no SDD 04.

Consultas quentes: cada hit soma no ranking; a partir de N hits a chave ganha TTL longo.
"""

from __future__ import annotations

import hashlib
import json
import re
import time

from autoseguro_agent.adapters.cache import CacheError, CacheStore
from autoseguro_agent.domain.extraction import ExtractionRequest, ExtractionResult
from autoseguro_agent.ports import LLMClient
from autoseguro_agent.telemetry import LLMCallStats

_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _SPACES.sub(" ", text.strip().lower())


class CachedLLM:
    def __init__(
        self,
        inner: LLMClient,
        cache: CacheStore,
        model: str,
        prompt_version: str,
        ttl_s: int = 86_400,
        hot_threshold: int = 3,
        hot_ttl_s: int = 7 * 86_400,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._model = model
        self._prompt_version = prompt_version
        self._ttl_s = ttl_s
        self._hot_threshold = hot_threshold
        self._hot_ttl_s = hot_ttl_s
        self.last_stats: LLMCallStats | None = None

    def key_for(self, req: ExtractionRequest) -> str:
        material = "|".join(
            [
                self._prompt_version,
                self._model,
                normalize(req.masked_text),
                req.pending_slot or "-",
                req.awaiting or "-",  # "sim" só reaproveita no mesmo contexto
                req.today_iso,
            ]
        )
        return "llm:" + hashlib.sha256(material.encode()).hexdigest()[:32]

    def extract(self, req: ExtractionRequest) -> ExtractionResult:
        if not self._cache.enabled:
            return self._call_inner(req, "disabled")
        key = self.key_for(req)
        t0 = time.perf_counter()
        try:
            cached = self._cache.get(key)
        except CacheError:
            return self._call_inner(req, "error")
        if cached:
            data = json.loads(cached)
            self._count_hot(key, req)
            orig = data.get("stats", {})
            self.last_stats = LLMCallStats(
                model=self._model,
                prompt_version=self._prompt_version,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                cache="hit",
                saved_cost_usd=float(orig.get("cost_usd", 0.0)),
                saved_latency_ms=int(orig.get("latency_ms", 0)),
            )
            return ExtractionResult.model_validate(data["result"])

        result = self._call_inner(req, "miss")
        stats = self.last_stats
        payload = {
            "result": result.model_dump(mode="json"),
            "stats": stats.as_payload() if stats else {},
        }
        try:
            self._cache.set(key, json.dumps(payload), self._ttl_s)
            self._count_hot(key, req)
        except CacheError:
            if stats:
                self.last_stats = LLMCallStats(**{**stats.as_payload(), "cache": "error"})
        return result

    def _call_inner(self, req: ExtractionRequest, cache: str) -> ExtractionResult:
        t0 = time.perf_counter()
        result = self._inner.extract(req)
        inner_stats: LLMCallStats | None = getattr(self._inner, "last_stats", None)
        latency = int((time.perf_counter() - t0) * 1000)
        if inner_stats is None:
            inner_stats = LLMCallStats(
                model=self._model, prompt_version=self._prompt_version, latency_ms=latency
            )
        self.last_stats = LLMCallStats(**{**inner_stats.as_payload(), "cache": cache})
        return result

    def _count_hot(self, key: str, req: ExtractionRequest) -> None:
        label = normalize(req.masked_text)[:80]
        try:
            hits = self._cache.hit("llm", label)
            if hits >= self._hot_threshold:
                self._cache.expire(key, self._hot_ttl_s)
        except CacheError:
            pass
