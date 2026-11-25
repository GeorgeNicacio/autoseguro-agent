"""Relógio injetável: nada de date.today() no domínio (a idade do veículo depende dele)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return date.today()

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass
class FixedClock:
    """Para testes: data fixa e tempo monotônico que só anda quando mandamos."""

    current: datetime = field(default_factory=lambda: datetime(2026, 11, 25, 12, 0, tzinfo=UTC))
    _mono: float = 0.0

    def now(self) -> datetime:
        return self.current

    def today(self) -> date:
        return self.current.date()

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._mono += seconds
        self.current += timedelta(seconds=seconds)
