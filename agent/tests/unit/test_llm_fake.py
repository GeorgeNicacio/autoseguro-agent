"""FakeLLM: extrator determinístico para testes, golden set e demo offline (NFR-2)."""

import pytest

from autoseguro_agent.adapters.llm_fake import FakeLLM
from autoseguro_agent.domain.extraction import ExtractionRequest, ExtractionResult, SlotInt


def req(text: str, pending: str | None = None) -> ExtractionRequest:
    return ExtractionRequest(
        masked_text=text,
        pending_slot=pending,  # type: ignore[arg-type]
        today_iso="2026-11-25",
    )


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


def test_extracts_full_profile_from_one_message(llm: FakeLLM) -> None:
    r = llm.extract(req("tenho 35 anos, um Onix 2022, cep <CEP_1>, quero o completo"))
    assert r.idade is not None
    assert r.idade.value == 35
    assert r.veiculo_ano is not None
    assert r.veiculo_ano.value == 2022
    assert r.cep_token is not None
    assert r.cep_token.value == "<CEP_1>"
    assert r.plano_id == "completo"


def test_bare_number_fills_the_pending_slot(llm: FakeLLM) -> None:
    assert llm.extract(req("35", pending="idade")).idade == SlotInt(value=35, confidence="high")
    r = llm.extract(req("2019", pending="veiculo_ano"))
    assert r.veiculo_ano is not None
    assert r.veiculo_ano.value == 2019


def test_vague_answer_is_low_confidence(llm: FakeLLM) -> None:
    r = llm.extract(req("sei lá, uns 30 e poucos", pending="idade"))
    assert r.idade is None or r.idade.confidence == "low"


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("quero falar com um atendente", "wants_human"),
        ("me passa pra um humano", "wants_human"),
        ("vou reclamar no procon", "legal_threat"),
        ("bati o carro ontem, como aciono?", "claim"),
        ("quero cancelar meu seguro", "cancel"),
        ("é pra rodar de uber", "commercial_use"),
        ("tem desconto à vista?", "discount"),
        ("a porto seguro me ofereceu menos", "competitor_match"),
        ("fechado, quero contratar", "wants_to_buy"),
        ("vou pensar", "will_think"),
        ("a franquia tá alta", "plan_question"),
        ("tenho 3 carros da empresa", "fleet"),
    ],
)
def test_intents(llm: FakeLLM, text: str, intent: str) -> None:
    assert intent in llm.extract(req(text)).intents


def test_script_overrides_heuristics_and_records_requests() -> None:
    scripted = ExtractionResult(intents=["wants_human"])
    llm = FakeLLM(script=[scripted])
    assert llm.extract(req("oi")) == scripted
    assert llm.extract(req("oi")).intents == ["greeting"]  # script acabou: volta à heurística
    assert [r.masked_text for r in llm.requests] == ["oi", "oi"]
