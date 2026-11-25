"""Contrato do único nó de LLM: entrada mascarada, saída estruturada (SPARK §K).

O LLM não tem campo de texto livre para o lead com valores: ele só devolve slots,
intenções e confiança. Quem escreve mensagens é `templates.py`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autoseguro_agent.domain.models import PlanId, SlotName

Intent = Literal[
    "wants_human",
    "complaint",
    "legal_threat",
    "strong_anger",
    "claim",
    "cancel",
    "endorsement",
    "second_copy",
    "fleet",
    "commercial_use",
    "discount",
    "competitor_match",
    "special_installments",
    "wants_to_buy",
    "accepts_quote",
    "will_think",
    "compare_plans",
    "wants_recommendation",
    "plan_question",
    "greeting",
    "other",
]

PlanTopic = Literal["coberturas", "franquia", "carencia", "diferenca"]
Confidence = Literal["high", "low"]


class SlotInt(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: int
    confidence: Confidence


class SlotStr(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: str
    confidence: Confidence


class ExtractionRequest(BaseModel):
    """O que o LLM recebe. `masked_text` já passou pelo PiiMasker."""

    model_config = ConfigDict(frozen=True)

    masked_text: str
    pending_slot: SlotName | None
    known_slots: dict[str, str] = Field(default_factory=dict)
    today_iso: str


class ExtractionResult(BaseModel):
    """O que o LLM devolve. Validado por Pydantic antes de tocar no estado."""

    model_config = ConfigDict(frozen=True)

    idade: SlotInt | None = None
    veiculo_ano: SlotInt | None = None
    veiculo_modelo: SlotStr | None = None
    cep_token: SlotStr | None = Field(
        default=None, description="Token do CEP exatamente como veio, ex.: <CEP_1>"
    )
    plano_id: PlanId | None = None
    data_inicio: SlotStr | None = Field(default=None, description="Data ISO YYYY-MM-DD")
    intents: list[Intent] = Field(default_factory=list)
    plan_question_topic: PlanTopic | None = None
