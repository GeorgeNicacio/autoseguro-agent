"""Teste de caos (make chaos): API real com 60% de falha e 20% de lentidão, seed fixa.

Asserts do plano: nenhuma trava, nenhum preço sem cotação válida, toda falha
esgotada vira handoff.
"""

import os

import httpx
import pytest

from autoseguro_agent.evaluation.chaos import run_chaos

pytestmark = pytest.mark.chaos

URL = os.getenv("QUOTE_CHAOS_URL", "http://localhost:8001")


@pytest.fixture(scope="module", autouse=True)
def chaos_service_up() -> None:
    try:
        httpx.get(f"{URL}/health", timeout=2).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(
            f"quote-service de caos fora do ar em {URL} (docker compose --profile chaos up)"
        )


async def test_fifty_conversations_under_chaos() -> None:
    report = await run_chaos(URL, n=50, concurrency=10)
    s = report.summary()
    assert s["hangs"] == 0
    assert s["money_without_success"] == 0
    assert s["failed_without_handoff"] == 0
    assert sum(s["conversation_status"].values()) == 50
    assert s["turn_seconds"]["max"] < 15
