"""Golden set contra o quote-service estável (make golden). Pula se ele não estiver no ar."""

import os

import httpx
import pytest

from autoseguro_agent.adapters.llm_fake import FakeLLM
from autoseguro_agent.evaluation.golden import SCENARIOS, Scenario, run_scenario

pytestmark = pytest.mark.golden

URL = os.getenv("QUOTE_STABLE_URL", "http://localhost:8002")


@pytest.fixture(scope="module", autouse=True)
def stable_service_up() -> None:
    try:
        httpx.get(f"{URL}/health", timeout=2).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(
            f"quote-service estável fora do ar em {URL} (docker compose --profile golden up)"
        )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
async def test_golden(scenario: Scenario) -> None:
    result = await run_scenario(scenario, URL, FakeLLM())
    assert result.ok, result.problems
