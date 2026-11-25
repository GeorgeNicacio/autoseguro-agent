"""Contratos do domínio (Pydantic v2): slots do lead e request/response do /quote."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PlanId = Literal["essencial", "completo", "premium"]
SlotName = Literal["veiculo_ano", "idade", "cep", "plano_id"]

# Ordem fixa em que o agente pergunta (REQ-02). Data de início é opcional:
# default 1º do mês seguinte (eligibility.default_start_date).
SLOT_ORDER: tuple[SlotName, ...] = ("veiculo_ano", "idade", "cep", "plano_id")

_CEP_TOKEN = re.compile(r"^<CEP_\d+>$")
_CEP_NORMALIZED = re.compile(r"^\d{5}-\d{3}$")


def _to_money(value: Any) -> Decimal:
    """Float da API -> Decimal exato pela representação em texto (209.9 -> 209.90)."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


class LeadProfile(BaseModel):
    """Slots coletados na conversa. Só guarda dados mascarados (REQ-50)."""

    model_config = ConfigDict(frozen=True)

    idade: int | None = None
    veiculo_ano: int | None = None
    veiculo_modelo: str | None = None
    cep_token: str | None = None
    plano_id: PlanId | None = None
    data_inicio: date | None = None

    @field_validator("cep_token")
    @classmethod
    def _only_tokens(cls, v: str | None) -> str | None:
        if v is not None and not _CEP_TOKEN.match(v):
            raise ValueError("cep_token deve ser um token do cofre, ex.: <CEP_1>")
        return v

    def missing_slots(self) -> list[SlotName]:
        filled = {
            "veiculo_ano": self.veiculo_ano,
            "idade": self.idade,
            "cep": self.cep_token,
            "plano_id": self.plano_id,
        }
        return [s for s in SLOT_ORDER if filled[s] is None]


class QuoteRequest(BaseModel):
    """Payload do POST /quote, já validado localmente. Único lugar com o CEP real."""

    model_config = ConfigDict(frozen=True)

    plano_id: PlanId
    idade: int = Field(ge=0, le=200)
    veiculo_ano: int = Field(ge=1950, le=2100)
    cep: str
    data_inicio: date | None = None

    @field_validator("cep")
    @classmethod
    def _normalized_cep(cls, v: str) -> str:
        if not _CEP_NORMALIZED.match(v):
            raise ValueError("cep deve estar normalizado como 00000-000")
        return v

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "plano_id": self.plano_id,
            "idade": self.idade,
            "veiculo_ano": self.veiculo_ano,
            "cep": self.cep,
        }
        if self.data_inicio is not None:
            payload["data_inicio"] = self.data_inicio.isoformat()
        return payload


class Carencia(BaseModel):
    model_config = ConfigDict(frozen=True)

    coberturas: tuple[str, ...]
    dias: int
    observacao: str


class ProRata(BaseModel):
    model_config = ConfigDict(frozen=True)

    dias_no_mes: int
    dias_cobrados: int
    valor_primeiro_pagamento: Decimal

    @field_validator("valor_primeiro_pagamento", mode="before")
    @classmethod
    def _money(cls, v: Any) -> Decimal:
        return _to_money(v)


class QuoteResult(BaseModel):
    """Resposta 200 do /quote. É a ÚNICA fonte de valores em R$ para o lead (REQ-13)."""

    model_config = ConfigDict(frozen=True)

    plano_id: PlanId
    plano_nome: str
    premio_mensal: Decimal
    franquia: Decimal
    coberturas: tuple[str, ...]
    multiplicadores: dict[str, float]
    carencia: Carencia
    moeda: str
    primeiro_pagamento_pro_rata: ProRata | None = None

    @field_validator("premio_mensal", mode="before")
    @classmethod
    def _premio(cls, v: Any) -> Decimal:
        return _to_money(v)

    @field_validator("franquia", mode="before")
    @classmethod
    def _franquia(cls, v: Any) -> Decimal:
        return Decimal(str(v))

    def money_values(self) -> set[Decimal]:
        """Valores que o validador de saída aceita numa mensagem com R$."""
        values = {self.premio_mensal, self.franquia}
        if self.primeiro_pagamento_pro_rata is not None:
            values.add(self.primeiro_pagamento_pro_rata.valor_primeiro_pagamento)
        return values
