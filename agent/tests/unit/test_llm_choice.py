"""Escolha de modelo do Claude no dashboard (chat e golden), para comparar custo e acerto."""

from pydantic import SecretStr

from autoseguro_agent.adapters.llm_anthropic import AnthropicLLM
from autoseguro_agent.adapters.llm_fake import FakeLLM
from autoseguro_agent.bootstrap import llm_options, make_named_llm, resolve_llm_choice
from autoseguro_agent.settings import Settings


def settings(key: bool = True) -> Settings:
    return Settings(anthropic_api_key=SecretStr("k") if key else None, llm_model="claude-opus-5-5")


def test_options_list_every_claude_model_only_with_key() -> None:
    assert llm_options(settings()) == [
        "fake",
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ]
    assert llm_options(settings(key=False)) == ["fake"]


def test_anthropic_alias_resolves_to_default_model() -> None:
    assert resolve_llm_choice(settings(), "anthropic") == "claude-opus-5-5"
    assert resolve_llm_choice(settings(), "claude-haiku-5-5") == "claude-haiku-5-5"


def test_named_llm_uses_the_chosen_model() -> None:
    assert isinstance(make_named_llm(settings(), "fake"), FakeLLM)
    haiku = make_named_llm(settings(), "claude-haiku-5-5")
    assert isinstance(haiku, AnthropicLLM)
    assert haiku._model == "claude-haiku-5-5"
