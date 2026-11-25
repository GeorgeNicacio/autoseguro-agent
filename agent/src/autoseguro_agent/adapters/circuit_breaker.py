"""Circuit breaker próprio e pequeno (REQ-24).

closed --N falhas seguidas--> open --cooldown--> half_open --sonda ok--> closed
                                ^                    |
                                +----sonda falha-----+

Só falha de infraestrutura conta (5xx, timeout). Recusa de negócio (422) e payload
inválido (400) mostram que o legado está respondendo, então contam como sucesso.
Por que próprio e não uma lib: ~40 linhas, testável com relógio fake e sem dependência.
"""

from __future__ import annotations

from typing import Literal

from autoseguro_agent.ports import Clock

BreakerState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    def __init__(self, clock: Clock, failure_threshold: int = 5, open_seconds: float = 30) -> None:
        self._clock = clock
        self._threshold = failure_threshold
        self._open_seconds = open_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self.state: BreakerState = "closed"

    def allow(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            assert self._opened_at is not None
            if self._clock.monotonic() - self._opened_at < self._open_seconds:
                return False
            self.state = "half_open"
            self._probe_in_flight = False
        if self._probe_in_flight:
            return False
        self._probe_in_flight = True
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._probe_in_flight = False
        self.state = "closed"

    def record_failure(self) -> None:
        self._failures += 1
        if self.state == "half_open" or self._failures >= self._threshold:
            self.state = "open"
            self._opened_at = self._clock.monotonic()
            self._probe_in_flight = False
