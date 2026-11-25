"""Recomendação de plano por regra em código, nunca pelo LLM (REQ-06).

Usada só quando o lead não escolhe plano: cotamos UM plano (uma chamada ao /quote,
menos exposição à instabilidade) e oferecemos os outros sem preço.
"""

from __future__ import annotations

from datetime import date

from autoseguro_agent.domain.models import PlanId

OLDER_VEHICLE_FROM_YEARS = 11  # faixa ×1,45 do /planos


def recommend_plan(veiculo_ano: int | None, today: date) -> PlanId:
    """Completo por padrão; essencial para carros de 11 a 20 anos.

    Trade-off: para carro mais velho, o agravo de ×1,45 pesa mais sobre um
    plano caro, e franquia/cobertura extra valem menos frente ao valor do carro.
    """
    if veiculo_ano is not None and today.year - veiculo_ano >= OLDER_VEHICLE_FROM_YEARS:
        return "essencial"
    return "completo"
