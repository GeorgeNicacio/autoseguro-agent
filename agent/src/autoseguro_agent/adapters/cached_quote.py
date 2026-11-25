"""Cache de cotação e de regras em volta do QuoteGateway (decorator · REQ-70..73, 77).

Por que é seguro cachear o /quote: é cálculo puro. A chave usa exatamente o que entra
no cálculo segundo `/planos` (plano, idade, ano do veículo, região do CEP pelos 2
primeiros dígitos, data de início), mais a versão das regras e a data do dia (a API
calcula a idade do veículo com date.today()). Só resposta 200 é guardada.

Ganho: um hit não passa pelo legado instável (sem retry, sem timeout, sem espera) e
responde em milissegundos. O preço continua sendo uma resposta 200 real da API.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
from datetime import date
from typing import Any, Literal

from autoseguro_agent.adapters.cache import CacheError, CacheStore
from autoseguro_agent.adapters.quote_http import new_id
from autoseguro_agent.domain.models import QuoteRequest, QuoteResult
from autoseguro_agent.domain.quote import QuoteOutcome, TraceContext
from autoseguro_agent.domain.rules import PlanRules
from autoseguro_agent.ports import Clock, QuoteGateway

RULES_KEY = "rules:planos"


def quote_cache_key(req: QuoteRequest, rules_version: str, today: date) -> str:
    material = {
        "rules": rules_version,
        "day": today.isoformat(),
        "plano": req.plano_id,
        "idade": req.idade,
        "ano": req.veiculo_ano,
        "regiao": req.cep.replace("-", "")[:2],  # a regra de /planos só olha 2 dígitos
        "inicio": req.data_inicio.isoformat() if req.data_inicio else None,
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return f"quote:{digest[:32]}"


class CachedQuoteGateway:
    def __init__(
        self,
        inner: QuoteGateway,
        cache: CacheStore,
        clock: Clock,
        ttl_s: int = 3600,
        rules_ttl_s: int = 600,
        hot_threshold: int = 3,
        hot_ttl_s: int = 6 * 3600,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._clock = clock
        self._ttl_s = ttl_s
        self._rules_ttl_s = rules_ttl_s
        self._hot_threshold = hot_threshold
        self._hot_ttl_s = hot_ttl_s
        self._rules: PlanRules | None = None
        self.rules_source: Literal["api", "snapshot", "cache"] = "snapshot"

    # --- regras -------------------------------------------------------------
    def rules(self) -> PlanRules:
        return self._rules or self._inner.rules()

    @property
    def breaker_state(self) -> str:
        return str(getattr(self._inner, "breaker_state", "disabled"))

    async def load_rules(self) -> None:
        """Regras do Redis (compartilhadas entre processos) ou da API, com TTL."""
        try:
            cached = self._cache.get(RULES_KEY)
        except CacheError:
            cached = None
        if cached:
            self._rules = PlanRules.from_planos(json.loads(cached))
            self.rules_source = "cache"
            return
        loader = getattr(self._inner, "load_rules", None)
        if loader is not None:
            await loader()
        self.rules_source = getattr(self._inner, "rules_source", "snapshot")
        raw = getattr(self._inner, "raw_planos", None)
        if raw and self.rules_source == "api":
            with contextlib.suppress(CacheError):
                self._cache.set(RULES_KEY, json.dumps(raw), self._rules_ttl_s)

    # --- cotação ------------------------------------------------------------
    async def quote(self, req: QuoteRequest, ctx: TraceContext) -> QuoteOutcome:
        if not self._cache.enabled:
            out = await self._inner.quote(req, ctx)
            return out.model_copy(update={"cache": "disabled"})

        key = quote_cache_key(req, self.rules().version, self._clock.today())
        try:
            cached = self._cache.get(key)
        except CacheError:
            out = await self._inner.quote(req, ctx)
            return out.model_copy(update={"cache": "error"})

        if cached:
            data: dict[str, Any] = json.loads(cached)
            self._promote_if_hot(key, req)
            return QuoteOutcome(
                quote_request_id=new_id("qr"),
                status="success",
                result=QuoteResult.model_validate(data["result"]),
                cache="hit",
                saved_ms=int(data.get("latency_ms", 0)),
            )

        t1 = time.perf_counter()
        out = await self._inner.quote(req, ctx)
        latency_ms = int((time.perf_counter() - t1) * 1000)
        if out.status == "success" and out.result is not None:
            payload = {"result": out.result.model_dump(mode="json"), "latency_ms": latency_ms}
            try:
                self._cache.set(key, json.dumps(payload), self._ttl_s)
            except CacheError:
                return out.model_copy(update={"cache": "error"})
        return out.model_copy(update={"cache": "miss"})

    def _promote_if_hot(self, key: str, req: QuoteRequest) -> None:
        label = f"{req.plano_id} · {req.idade} anos · {req.veiculo_ano} · região {req.cep[:2]}"
        try:
            hits = self._cache.hit("quote", label)
            if hits >= self._hot_threshold:
                self._cache.expire(key, self._hot_ttl_s)
        except CacheError:
            pass
