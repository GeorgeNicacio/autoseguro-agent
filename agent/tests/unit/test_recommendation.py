"""recommend_plan: um plano por regra em código quando o lead não escolhe (REQ-06)."""

from datetime import date

import pytest

from autoseguro_agent.domain.recommendation import recommend_plan


@pytest.mark.parametrize(
    ("ano", "esperado"),
    [
        (2026, "completo"),  # 0 anos
        (2016, "completo"),  # 10 anos
        (2015, "essencial"),  # 11 anos
        (2012, "essencial"),  # cenário G16
        (2006, "essencial"),  # 20 anos
        (None, "completo"),  # ano ainda desconhecido
    ],
)
def test_recommend_plan(ano: int | None, esperado: str, today: date) -> None:
    assert recommend_plan(ano, today) == esperado
