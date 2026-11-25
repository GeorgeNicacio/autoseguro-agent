"""Porta de cache e adaptadores (Redis e no-op).

Redis fora do ar NÃO derruba o agente (REQ-77): os métodos levantam `CacheError`,
que os decorators tratam como "sem cache" e registram `cache=error` no evento.
"""

from __future__ import annotations

from typing import Any, Protocol

import redis

HOT_PREFIX = "hot:"


class CacheError(Exception):
    """Cache indisponível. Quem usa segue sem cache."""


class CacheStore(Protocol):
    enabled: bool

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_s: int) -> None: ...
    def expire(self, key: str, ttl_s: int) -> None: ...
    def ttl(self, key: str) -> int: ...
    def hit(self, namespace: str, label: str) -> int: ...
    def top_hot(self, namespace: str, n: int) -> list[tuple[str, int]]: ...
    def set_once(self, key: str, ttl_s: int) -> bool: ...
    def stats(self) -> dict[str, Any]: ...


class RedisCache:
    enabled = True

    def __init__(self, client: redis.Redis) -> None:
        self._r = client

    @classmethod
    def from_url(cls, url: str) -> RedisCache:
        return cls(
            redis.Redis.from_url(
                url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5
            )
        )

    def _call(self, fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except redis.RedisError as exc:
            raise CacheError(str(exc)) from exc

    def get(self, key: str) -> str | None:
        value = self._call(self._r.get, key)
        return None if value is None else str(value)

    def set(self, key: str, value: str, ttl_s: int) -> None:
        self._call(self._r.set, key, value, ttl_s)

    def expire(self, key: str, ttl_s: int) -> None:
        self._call(self._r.expire, key, ttl_s)

    def ttl(self, key: str) -> int:
        return int(self._call(self._r.ttl, key))

    def hit(self, namespace: str, label: str) -> int:
        """Conta um hit para o ranking de consultas quentes; devolve o total."""
        return int(self._call(self._r.zincrby, f"{HOT_PREFIX}{namespace}", 1, label))

    def top_hot(self, namespace: str, n: int) -> list[tuple[str, int]]:
        rows = self._call(self._r.zrevrange, f"{HOT_PREFIX}{namespace}", 0, n - 1, True)
        return [(str(label), int(score)) for label, score in rows]

    def set_once(self, key: str, ttl_s: int) -> bool:
        """SET NX: idempotência (ex.: reentrega do webhook). True se foi a 1ª vez."""
        return bool(self._call(self._r.set, key, "1", ttl_s, None, True))

    def stats(self) -> dict[str, Any]:
        info = self._call(self._r.info, "stats")
        mem = self._call(self._r.info, "memory")
        return {
            "keyspace_hits": info.get("keyspace_hits"),
            "keyspace_misses": info.get("keyspace_misses"),
            "used_memory_human": mem.get("used_memory_human"),
        }


class NullCache:
    """Sem Redis configurado: tudo é miss e nada é guardado."""

    enabled = False

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, ttl_s: int) -> None:
        return None

    def expire(self, key: str, ttl_s: int) -> None:
        return None

    def ttl(self, key: str) -> int:
        return -2

    def hit(self, namespace: str, label: str) -> int:
        return 0

    def top_hot(self, namespace: str, n: int) -> list[tuple[str, int]]:
        return []

    def set_once(self, key: str, ttl_s: int) -> bool:
        return True

    def stats(self) -> dict[str, Any]:
        return {}
