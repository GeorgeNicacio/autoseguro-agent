"""Validação local antes do /quote (REQ-10, REQ-11).

Dois tipos de problema, tratados de formas diferentes:

- `SlotError`: dado mal formatado ou implausível (CEP com 7 dígitos, ano no futuro).
  O agente pede correção UMA vez; repetiu, handoff `stuck` (REQ-12).
- `PolicyRefusal`: dado válido, mas fora da política (condutor > 75, carro > 20 anos).
  O agente NÃO chama a API: explica o motivo e faz handoff `out_of_policy`.

Validar aqui importa porque a API sorteia a falha ANTES da regra de negócio: um 503
não diz se o payload seria recusado, e cada retry gasto nisso é tempo do lead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from autoseguro_agent.domain.models import LeadProfile
from autoseguro_agent.domain.rules import PlanRules

MIN_PLAUSIBLE_AGE = 1
MAX_PLAUSIBLE_AGE = 120
MIN_VEHICLE_YEAR = 1950  # limite do schema da API (abaixo disso: 422 de schema)

_NON_DIGIT = re.compile(r"\D")


@dataclass(frozen=True)
class SlotError:
    slot: str
    code: str
    message: str


@dataclass(frozen=True)
class PolicyRefusal:
    code: str
    motivo: str


def normalize_cep(raw: str) -> str | None:
    """Aceita '01310-100', '01310100', '01.310-100'; exige exatamente 8 dígitos."""
    digits = _NON_DIGIT.sub("", raw)
    if len(digits) != 8:
        return None
    return f"{digits[:5]}-{digits[5:]}"


def validate_idade(idade: int) -> SlotError | None:
    if not MIN_PLAUSIBLE_AGE <= idade <= MAX_PLAUSIBLE_AGE:
        return SlotError("idade", "idade_invalida", "Idade fora de um valor plausível.")
    return None


def validate_veiculo_ano(ano: int, today: date) -> SlotError | None:
    if ano > today.year:
        return SlotError("veiculo_ano", "veiculo_ano_futuro", "Ano do veículo no futuro.")
    if ano < MIN_VEHICLE_YEAR:
        return SlotError("veiculo_ano", "veiculo_ano_invalido", "Ano do veículo inválido.")
    return None


def validate_data_inicio(inicio: date, today: date) -> SlotError | None:
    if inicio < today:
        return SlotError("data_inicio", "data_inicio_passada", "Data de início no passado.")
    return None


def validate_plano(plano_id: str, rules: PlanRules) -> SlotError | None:
    if rules.plan(plano_id) is None:
        return SlotError("plano_id", "plano_invalido", "Plano inexistente.")
    return None


def default_start_date(today: date) -> date:
    """1º dia do mês seguinte: sem pro-rata, a 1ª cotação mostra um valor só."""
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


def policy_refusal(profile: LeadProfile, rules: PlanRules, today: date) -> PolicyRefusal | None:
    """Avalia o que já se sabe do perfil; funciona com perfil parcial."""
    if profile.idade is not None:
        band = rules.driver_band(profile.idade)
        if band is None:
            return PolicyRefusal(
                "condutor_abaixo_minimo",
                "Idade abaixo da mínima de aceitação (18 anos).",
            )
        if band.refuse:
            return PolicyRefusal("condutor_acima_limite", band.motivo or "Idade fora da política.")

    if profile.veiculo_ano is not None:
        anos = today.year - profile.veiculo_ano
        vband = rules.vehicle_band(anos)
        if vband is not None and vband.refuse:
            return PolicyRefusal(
                "veiculo_acima_limite", vband.motivo or "Veículo fora da política."
            )
    return None
