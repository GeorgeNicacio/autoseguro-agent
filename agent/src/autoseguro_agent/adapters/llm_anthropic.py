"""Adaptador Claude (porta LLMClient) via SDK oficial `anthropic` (ADR-001).

- `messages.parse(output_format=ExtractionResult)`: a saída já volta validada.
- Sem `temperature`: os modelos atuais não aceitam parâmetros de amostragem.
  O determinismo que importa vem do schema + validação em código + golden set.
- `effort: low`: extração é tarefa simples; reduz latência e custo.
- System prompt fixo e sem nada volátil: elegível a prompt caching.
- Qualquer falha (rede, 429, 5xx, recusa do modelo, saída vazia) vira
  `LLMUnavailableError`, e o grafo responde por template.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Literal

import anthropic
from anthropic.types import OutputConfigParam

from autoseguro_agent.domain.extraction import ExtractionRequest, ExtractionResult
from autoseguro_agent.ports import LLMUnavailableError

PROMPT_VERSION = "extract_v1"


def load_prompt(name: str = PROMPT_VERSION) -> str:
    return files("autoseguro_agent.prompts").joinpath(f"{name}.md").read_text("utf-8")


def render_user_message(req: ExtractionRequest) -> str:
    return (
        f"<data_de_hoje>{req.today_iso}</data_de_hoje>\n"
        f"<dado_esperado>{req.pending_slot or 'nenhum'}</dado_esperado>\n"
        f"<dados_ja_coletados>{json.dumps(req.known_slots, ensure_ascii=False)}"
        "</dados_ja_coletados>\n"
        f"<mensagem_do_lead>{req.masked_text}</mensagem_do_lead>"
    )


class AnthropicLLM:
    def __init__(
        self,
        model: str = "claude-opus-5-5",
        effort: Literal["low", "medium", "high"] = "low",
        timeout_s: float = 10.0,
        client: Any | None = None,
        api_key: str | None = None,
    ) -> None:
        self._client = client or anthropic.Anthropic(
            api_key=api_key, timeout=timeout_s, max_retries=2
        )
        self._model = model
        self._effort = effort
        self._system = load_prompt()

    def extract(self, req: ExtractionRequest) -> ExtractionResult:
        output_config: OutputConfigParam = {"effort": self._effort}
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=4096,
                system=self._system,
                messages=[{"role": "user", "content": render_user_message(req)}],
                output_format=ExtractionResult,
                output_config=output_config,
            )
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError("conexão com o provedor") from exc
        except anthropic.RateLimitError as exc:
            raise LLMUnavailableError("limite de taxa") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailableError(f"status {exc.status_code}") from exc

        if response.stop_reason == "refusal":
            raise LLMUnavailableError("recusa do modelo")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMUnavailableError(f"saída vazia ({response.stop_reason})")
        return ExtractionResult.model_validate(parsed)
