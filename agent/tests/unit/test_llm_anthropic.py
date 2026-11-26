"""Adaptador Claude testado sem rede: chamada correta e falhas viram LLMUnavailableError."""

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from autoseguro_agent.adapters.llm_anthropic import AnthropicLLM, load_prompt, render_user_message
from autoseguro_agent.domain.extraction import ExtractionRequest, ExtractionResult, SlotInt
from autoseguro_agent.ports import LLMUnavailableError

REQ = ExtractionRequest(
    masked_text="tenho 35 anos, cep <CEP_1>", pending_slot="idade", today_iso="2026-11-25"
)


class FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def client(messages: FakeMessages) -> Any:
    return SimpleNamespace(messages=messages)


def ok_response(parsed: ExtractionResult | None, stop: str = "end_turn") -> Any:
    usage = SimpleNamespace(
        input_tokens=1200,
        output_tokens=300,
        cache_read_input_tokens=1000,
        cache_creation_input_tokens=0,
    )
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop, usage=usage)


def test_usage_becomes_cost_stats() -> None:
    """REQ-80: tokens e custo pela tabela de preços (opus 5.5: 4 / 20 / 0,20 por MTok)."""
    msgs = FakeMessages(ok_response(ExtractionResult()))
    llm = AnthropicLLM(model="claude-opus-5-5", client=client(msgs))
    llm.extract(REQ)
    stats = llm.last_stats
    assert stats is not None
    assert stats.input_tokens == 1200
    assert stats.cache_read_tokens == 1000
    assert stats.cost_usd == round((1200 * 4 + 300 * 20 + 1000 * 0.20) / 1_000_000, 6)


def test_calls_parse_with_schema_effort_and_no_temperature() -> None:
    expected = ExtractionResult(idade=SlotInt(value=35, confidence="high"))
    msgs = FakeMessages(ok_response(expected))
    llm = AnthropicLLM(client=client(msgs))
    assert llm.extract(REQ) == expected
    call = msgs.calls[0]
    assert call["model"] == "claude-haiku-5-5"  # padrão (ADR-017)
    assert call["output_format"] is ExtractionResult
    assert call["output_config"] == {"effort": "low"}
    assert "temperature" not in call
    assert call["system"][0]["text"] == load_prompt()
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}  # prompt caching
    assert "<CEP_1>" in call["messages"][0]["content"]


def test_refusal_is_unavailable() -> None:
    llm = AnthropicLLM(client=client(FakeMessages(ok_response(None, stop="refusal"))))
    with pytest.raises(LLMUnavailableError):
        llm.extract(REQ)


def test_empty_output_is_unavailable() -> None:
    llm = AnthropicLLM(client=client(FakeMessages(ok_response(None, stop="max_tokens"))))
    with pytest.raises(LLMUnavailableError):
        llm.extract(REQ)


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")),
        anthropic.InternalServerError(
            "boom",
            response=httpx.Response(500, request=httpx.Request("POST", "https://x")),
            body=None,
        ),
    ],
)
def test_sdk_errors_are_unavailable(error: Exception) -> None:
    llm = AnthropicLLM(client=client(FakeMessages(error=error)))
    with pytest.raises(LLMUnavailableError):
        llm.extract(REQ)


def test_prompt_is_spark_and_forbids_money() -> None:
    prompt = load_prompt()
    for section in ("## S", "## P", "## A", "## R", "## K"):
        assert section in prompt
    assert "Nunca escreva valores em reais" in prompt


def test_user_message_has_no_volatile_data_in_system() -> None:
    """Data de hoje vai na mensagem do usuário, não no system (prompt caching)."""
    assert "2026-11-25" in render_user_message(REQ)
    assert "2026" not in load_prompt()
