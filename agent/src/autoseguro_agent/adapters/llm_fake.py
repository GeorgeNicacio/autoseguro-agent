"""FakeLLM: cumpre o mesmo contrato do LLM real (SOLID · L) sem rede.

Dois modos:
- `script`: fila de `ExtractionResult` pré-definidos (cenários exatos de teste);
- heurística de regex quando a fila acaba (golden set, demo offline sem chave).

Também guarda todas as requisições recebidas, para os testes provarem que nenhum
dado pessoal cru chega ao "modelo".
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Iterable

from autoseguro_agent.domain.extraction import (
    ExtractionRequest,
    ExtractionResult,
    Intent,
    PlanTopic,
    SlotInt,
    SlotStr,
)
from autoseguro_agent.domain.models import PlanId
from autoseguro_agent.telemetry import LLMCallStats

_INTENT_PATTERNS: tuple[tuple[Intent, str], ...] = (
    ("wants_human", r"atendente|humano|pessoa de verdade|falar com algu[eé]m|consultor"),
    ("legal_threat", r"procon|processar|advogado|reclame ?aqui"),
    ("complaint", r"reclama|absurdo|p[eé]ssimo|descaso"),
    ("strong_anger", r"rid[ií]culo|palha[cç]ada|vergonha"),
    ("claim", r"\bbati\b|batida|sinistro|acionar|roubaram|furtaram|aciono"),
    ("cancel", r"cancelar|cancelamento"),
    ("endorsement", r"endosso|trocar (o )?carro da ap[oó]lice|alterar (a )?ap[oó]lice"),
    ("second_copy", r"segunda via|2[ªa] via|boleto atrasado"),
    ("fleet", r"\bfrota\b|carros da empresa|\b\d+ carros\b"),
    ("commercial_use", r"\buber\b|\b99 ?pop\b|aplicativo|entregas?\b|ifood|t[aá]xi"),
    ("discount", r"desconto|abaixa|baixar o pre[cç]o|mais barato|[aà] vista"),
    ("competitor_match", r"porto seguro|azul seguros|bradesco|sulam[eé]rica|ita[uú]|concorrente"),
    ("special_installments", r"parcelar|parcelamento|em \d+x"),
    ("wants_to_buy", r"contratar|fechado|fechar|pode emitir|vamos nessa"),
    ("will_think", r"vou pensar|preciso pensar|ver com (minha|meu)"),
    (
        "wants_recommendation",
        r"recomend|me indica|indica um|qual (voc[eê] )?(sugere|indica)|n[aã]o sei qual",
    ),
    ("compare_plans", r"comparar|diferen[cç]a entre|e o (essencial|completo|premium)\??"),
    ("plan_question", r"franquia|cobre|cobertura|car[eê]ncia|o que inclui"),
    ("greeting", r"^\s*(oi|ol[aá]|bom dia|boa tarde|boa noite|eae)\b"),
)
_TOPICS: tuple[tuple[PlanTopic, str], ...] = (
    ("franquia", r"franquia"),
    ("carencia", r"car[eê]ncia"),
    ("diferenca", r"diferen[cç]a|comparar"),
    ("coberturas", r"cobre|cobertura|inclui"),
)
# Resposta afirmativa CURTA e completa: "quero começar dia 15" não é aceite.
_AFFIRMATIVE = re.compile(
    r"\s*(sim|s|ss|isso|quero|quero sim|sim quero|pode ser|pode ser esse|pode|ok|beleza|"
    r"bora|vamos|esse mesmo|seguir com esse|pode seguir|fechado)[\s!.,]*"
)
_PLAN = re.compile(r"\b(essencial|completo|premium)\b", re.IGNORECASE)
_AGE = re.compile(r"\b(\d{1,3})\s*anos\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(19[5-9]\d|20\d{2})\b")
_CEP_TOKEN = re.compile(r"<CEP_\d+>")
_BARE_INT = re.compile(r"^\s*(\d{1,4})\s*$")
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MODEL = re.compile(
    r"\b(onix|gol|polo|virtus|t-cross|nivus|tracker|spin|argo|mobi|cronos|pulse|toro|hb20|"
    r"creta|corolla|yaris|civic|city|hr-v|renegade|compass|kwid|sandero|duster)\b",
    re.IGNORECASE,
)


class FakeLLM:
    def __init__(self, script: Iterable[ExtractionResult] = ()) -> None:
        self._script: deque[ExtractionResult] = deque(script)
        self.requests: list[ExtractionRequest] = []
        self.last_stats: LLMCallStats | None = None

    def extract(self, req: ExtractionRequest) -> ExtractionResult:
        t0 = time.perf_counter()
        self.requests.append(req)
        result = self._script.popleft() if self._script else self._heuristic(req)
        # Sem tokens nem custo: deixa o dashboard e os testes de métricas funcionarem offline.
        self.last_stats = LLMCallStats(
            model="fake",
            prompt_version="heuristic",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        return result

    @staticmethod
    def _heuristic(req: ExtractionRequest) -> ExtractionResult:
        text = req.masked_text
        low = text.lower()

        idade = None
        if m := _AGE.search(text):
            idade = SlotInt(value=int(m.group(1)), confidence="high")
        ano = None
        if m := _YEAR.search(text):
            ano = SlotInt(value=int(m.group(1)), confidence="high")

        bare = _BARE_INT.match(text)
        if bare and req.pending_slot == "idade" and idade is None:
            idade = SlotInt(value=int(bare.group(1)), confidence="high")
        if bare and req.pending_slot == "veiculo_ano" and ano is None:
            ano = SlotInt(value=int(bare.group(1)), confidence="high")

        cep = None
        if m := _CEP_TOKEN.search(text):
            cep = SlotStr(value=m.group(0), confidence="high")
        plano: PlanId | None = None
        if m := _PLAN.search(text):
            plano = m.group(1).lower()  # type: ignore[assignment]
        modelo = None
        if m := _MODEL.search(text):
            modelo = SlotStr(value=m.group(1), confidence="high")
        data = None
        if m := _DATE.search(text):
            d, mo, y = (int(g) for g in m.groups())
            data = SlotStr(value=f"{y:04d}-{mo:02d}-{d:02d}", confidence="high")

        intents: list[Intent] = [i for i, rx in _INTENT_PATTERNS if re.search(rx, low)]
        if (
            req.awaiting == "accept_quote"
            and _AFFIRMATIVE.fullmatch(low)
            and "accepts_quote" not in intents
        ):
            intents.append("accepts_quote")
        topic = next((t for t, rx in _TOPICS if re.search(rx, low)), None)

        if not intents and idade is None and req.pending_slot == "idade" and re.search(r"\d", low):
            idade = SlotInt(value=int(re.findall(r"\d+", low)[0]), confidence="low")
        if not any((idade, ano, cep, plano, intents, data)):
            intents = ["other"]

        return ExtractionResult(
            idade=idade,
            veiculo_ano=ano,
            veiculo_modelo=modelo,
            cep_token=cep,
            plano_id=plano,
            data_inicio=data,
            intents=intents,
            plan_question_topic=topic if "plan_question" in intents else None,
        )
