"""Circuit breaker: protege o legado e responde rápido quando ele está fora (REQ-24)."""

from autoseguro_agent.adapters.circuit_breaker import CircuitBreaker
from autoseguro_agent.adapters.clock import FixedClock


def make() -> tuple[CircuitBreaker, FixedClock]:
    clock = FixedClock()
    return CircuitBreaker(clock, failure_threshold=5, open_seconds=30), clock


def test_starts_closed_and_allows() -> None:
    breaker, _ = make()
    assert breaker.state == "closed"
    assert breaker.allow()


def test_opens_after_threshold_consecutive_failures() -> None:
    breaker, _ = make()
    for _ in range(4):
        breaker.record_failure()
    assert breaker.state == "closed"
    breaker.record_failure()
    assert breaker.state == "open"
    assert not breaker.allow()


def test_success_resets_the_count() -> None:
    breaker, _ = make()
    for _ in range(4):
        breaker.record_failure()
    breaker.record_success()
    for _ in range(4):
        breaker.record_failure()
    assert breaker.state == "closed"


def test_half_open_after_cooldown_allows_one_probe() -> None:
    breaker, clock = make()
    for _ in range(5):
        breaker.record_failure()
    clock.advance(29.9)
    assert not breaker.allow()
    clock.advance(0.2)
    assert breaker.allow()  # sonda
    assert breaker.state == "half_open"
    assert not breaker.allow()  # só uma sonda por vez


def test_probe_success_closes() -> None:
    breaker, clock = make()
    for _ in range(5):
        breaker.record_failure()
    clock.advance(31)
    breaker.allow()
    breaker.record_success()
    assert breaker.state == "closed"
    assert breaker.allow()


def test_probe_failure_reopens_for_another_cooldown() -> None:
    breaker, clock = make()
    for _ in range(5):
        breaker.record_failure()
    clock.advance(31)
    breaker.allow()
    breaker.record_failure()
    assert breaker.state == "open"
    clock.advance(10)
    assert not breaker.allow()
