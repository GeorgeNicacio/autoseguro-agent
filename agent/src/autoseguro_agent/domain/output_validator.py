"""Validador de saída: nenhuma mensagem sai com valor que não veio da fonte oficial (REQ-13).

Fontes permitidas:
- a ÚLTIMA cotação com status `success` (prêmio, franquia, pro-rata);
- as franquias de GET /planos (dado fixo do plano, não preço calculado).

Sem cotação de sucesso, qualquer outro valor monetário bloqueia a mensagem.
Percentuais também bloqueiam: multiplicador e desconto nunca saem para o lead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from autoseguro_agent.domain.models import QuoteResult
from autoseguro_agent.domain.rules import PlanRules

_MONEY = re.compile(
    r"R\$\s*\d{1,3}(?:\.\d{3})+(?:,\d{2})?"  # R$ 3.000,00
    r"|R\$\s*\d+(?:,\d{2})?"  # R$ 209,90 / R$3000
    r"|(?<![\d.,])\d{1,3}(?:\.\d{3})*,\d{2}(?![\d,])"  # 209,90 sem símbolo
)
_PERCENT = re.compile(r"\d+(?:,\d+)?\s?%")


@dataclass(frozen=True)
class OutputCheck:
    ok: bool
    offending: tuple[str, ...] = ()


def _parse(raw: str) -> Decimal:
    number = raw.replace("R$", "").strip().replace(".", "").replace(",", ".")
    return Decimal(number)


def extract_money(text: str) -> list[Decimal]:
    return [_parse(m.group(0)) for m in _MONEY.finditer(text)]


def validate_output(text: str, last_success: QuoteResult | None, rules: PlanRules) -> OutputCheck:
    allowed = {Decimal(p.franquia) for p in rules.plans}
    if last_success is not None:
        allowed |= last_success.money_values()

    offending = [m.group(0) for m in _MONEY.finditer(text) if _parse(m.group(0)) not in allowed]
    offending += [m.group(0) for m in _PERCENT.finditer(text)]
    return OutputCheck(ok=not offending, offending=tuple(offending))
