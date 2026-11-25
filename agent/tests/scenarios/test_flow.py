"""Fluxo ponta a ponta do grafo com FakeLLM + FakeGateway (base do golden set do Dia 3)."""

import re

from autoseguro_agent.pii import contains_pii
from tests.fakes import FakeGateway, make_agent

MONEY = re.compile(r"R\$")


def joined(replies: list[str]) -> str:
    return "\n".join(replies)


async def test_happy_path_one_slot_per_turn() -> None:
    agent, gw, _, events = make_agent()
    r1 = await agent.handle("c1", "Oi, quero fazer um seguro")
    assert "AutoSeguro" in joined(r1)
    assert "ano do seu carro" in joined(r1)

    r2 = await agent.handle("c1", "um Onix 2022")
    assert "idade" in joined(r2).lower()
    r3 = await agent.handle("c1", "35")
    assert "CEP" in joined(r3)
    r4 = await agent.handle("c1", "01310-100")
    assert "planos" in joined(r4).lower()
    r5 = await agent.handle("c1", "o completo")
    text = joined(r5)
    assert "R$ 209,90" in text
    assert "01/12/2026" in text  # data padrão: 1º do mês seguinte
    assert len(gw.requests) == 1
    assert gw.requests[0].cep == "01310-100"  # CEP real só no gateway
    assert agent.state("c1")["status"] == "quoted"
    assert any(
        e.event_type == "quote_request.finished" and e.status == "success" for e in events.all
    )


async def test_everything_in_one_message() -> None:
    agent, gw, _, _ = make_agent()
    r = await agent.handle("c2", "tenho 35 anos, Onix 2022, cep 01310-100, quero o premium")
    assert "Premium" in joined(r)
    assert gw.requests[0].plano_id == "premium"


async def test_policy_refusal_never_calls_api() -> None:
    agent, gw, _, events = make_agent()
    await agent.handle("c3", "Oi, tenho um Gol 2022")
    r = await agent.handle("c3", "tenho 80 anos")
    assert "consultor" in joined(r).lower()
    assert not MONEY.search(joined(r))
    assert gw.requests == []
    handoffs = [e for e in events.all if e.event_type == "handoff.opened"]
    assert handoffs[0].payload["rule_id"] == "out_of_policy"


async def test_old_car_refused() -> None:
    agent, gw, _, _events = make_agent()
    r = await agent.handle("c4", "quero cotar meu Corolla 2003")
    assert "20 anos" in joined(r)
    assert gw.requests == []


async def test_api_failure_becomes_honest_handoff_without_price() -> None:
    agent, _gw, _, events = make_agent(gateway=FakeGateway(script=["failed"]))
    r = await agent.handle("c5", "35 anos, Onix 2022, cep 01310-100, completo")
    text = joined(r)
    assert "instável" in text
    assert not MONEY.search(text)
    assert agent.state("c5")["status"] == "handed_off"
    rule = next(e for e in events.all if e.event_type == "handoff.opened").payload["rule_id"]
    assert rule == "infra_unavailable"


async def test_wants_human_mid_conversation() -> None:
    agent, _, _, _ = make_agent()
    await agent.handle("c6", "Oi, tenho um Onix 2022")
    r = await agent.handle("c6", "prefiro falar com um atendente")
    assert "consultor" in joined(r).lower()
    r2 = await agent.handle("c6", "tenho 35 anos")
    assert "consultor já está" in joined(r2)


async def test_after_handoff_no_more_quotes() -> None:
    agent, gw, _, _ = make_agent()
    await agent.handle("c7", "quero falar com um humano")
    await agent.handle("c7", "35 anos, Onix 2022, cep 01310-100, completo")
    assert gw.requests == []


async def test_first_media_only_acknowledged_second_hands_off() -> None:
    agent, _, _, events = make_agent()
    await agent.handle("c8", "Oi, tenho um Onix 2022")
    r1 = await agent.handle("c8", "[imagem]", message_type="image")
    assert "Não preciso desse arquivo" in joined(r1)
    assert agent.state("c8")["status"] == "active"
    await agent.handle("c8", "[audio]", message_type="audio")
    assert agent.state("c8")["status"] == "handed_off"
    rule = next(e for e in events.all if e.event_type == "handoff.opened").payload["rule_id"]
    assert rule == "media_unsupported"


async def test_unsolicited_cpf_is_masked_and_acknowledged() -> None:
    agent, _, llm, events = make_agent()
    r = await agent.handle("c9", "Oi! meu cpf é 529.982.247-25, tenho um Onix 2022")
    assert "não preciso de CPF" in joined(r)
    assert all("529" not in req.masked_text for req in llm.requests)
    assert not any(contains_pii(str(e.payload)) for e in events.all)


async def test_recommends_one_plan_when_lead_does_not_choose() -> None:
    agent, gw, _, _ = make_agent()
    await agent.handle("c10", "tenho 40 anos, um Gol 2012, cep 01310-100")
    r = await agent.handle("c10", "não sei, me indica")
    text = joined(r)
    assert gw.requests[0].plano_id == "essencial"
    assert "recomendo" in text
    assert "Completo" in text  # ofertado sem preço
    assert text.count("R$") == 2  # mensalidade + franquia do essencial


async def test_invalid_cep_twice_is_stuck() -> None:
    agent, gw, _, _events = make_agent()
    await agent.handle("c11", "tenho 35 anos e um Onix 2022")
    r1 = await agent.handle("c11", "<CEP_9>")  # token que não existe no cofre
    assert "8 números" in joined(r1)
    await agent.handle("c11", "<CEP_7>")
    assert agent.state("c11")["status"] == "handed_off"
    assert gw.requests == []


async def test_two_answers_without_the_data_is_stuck() -> None:
    """CEP com 7 dígitos não vira token nem é extraído: conta como resposta sem o dado."""
    agent, gw, _, events = make_agent()
    await agent.handle("c16", "tenho 35 anos e um Onix 2022")
    r1 = await agent.handle("c16", "1310-100")
    assert "8 números" in joined(r1)
    await agent.handle("c16", "sei la")
    rule = next(e for e in events.all if e.event_type == "handoff.opened").payload["rule_id"]
    assert rule == "stuck"
    assert gw.requests == []


async def test_change_plan_after_quote_requotes() -> None:
    agent, gw, _, _ = make_agent()
    await agent.handle("c12", "35 anos, Onix 2022, cep 01310-100, completo")
    r = await agent.handle("c12", "e o premium?")
    assert "Premium" in joined(r)
    assert [q.plano_id for q in gw.requests] == ["completo", "premium"]


async def test_ready_to_close() -> None:
    agent, _, _, events = make_agent()
    await agent.handle("c13", "35 anos, Onix 2022, cep 01310-100, completo")
    r = await agent.handle("c13", "fechado, quero contratar")
    assert "contratar" in joined(r)
    rule = next(e for e in events.all if e.event_type == "handoff.opened").payload["rule_id"]
    assert rule == "ready_to_close"


async def test_discount_goes_to_human() -> None:
    agent, _, _, events = make_agent()
    await agent.handle("c14", "35 anos, Onix 2022, cep 01310-100, completo")
    await agent.handle("c14", "tem desconto à vista?")
    rule = next(e for e in events.all if e.event_type == "handoff.opened").payload["rule_id"]
    assert rule == "price_negotiation"


async def test_every_event_is_traceable_and_masked() -> None:
    agent, _, _, events = make_agent(gateway=FakeGateway(script=["failed"]))
    await agent.handle("c15", "cpf 529.982.247-25 email ana@x.com, tenho 35 anos")
    await agent.handle("c15", "Onix 2022, cep 01310-100, completo")
    for e in events.all:
        assert e.conversation_id == "c15"
        assert e.status
        assert not contains_pii(str(e.payload))
    attempts = [e for e in events.all if e.event_type == "quote_attempt"]
    assert attempts
    assert all(e.quote_request_id and e.quote_attempt_id for e in attempts)


async def test_slow_quote_sends_waiting_message_first() -> None:
    """REQ-23: cotação demorou mais que o limite -> 'estou calculando' antes do resultado."""
    agent, _, _, events = make_agent(gateway=FakeGateway(delay_s=0.2), wait_after_s=0.05)
    r = await agent.handle("c17", "35 anos, Onix 2022, cep 01310-100, completo")
    assert r[0] == "Estou calculando sua cotação, só um instante."
    assert "R$ 209,90" in joined(r[1:])
    waiting = [e for e in events.all if e.payload.get("kind") == "waiting"]
    assert len(waiting) == 1


async def test_fast_quote_has_no_waiting_message() -> None:
    agent, _, _, _ = make_agent(wait_after_s=1.0)
    r = await agent.handle("c18", "35 anos, Onix 2022, cep 01310-100, completo")
    assert "calculando" not in joined(r)
