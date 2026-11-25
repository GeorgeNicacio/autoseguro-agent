from datetime import date

import pytest

from autoseguro_agent.domain.rules import PlanRules, load_snapshot

# Data fixa: a idade do veículo depende de "hoje" (armadilha do quote-service).
TODAY = date(2026, 11, 25)


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture
def rules() -> PlanRules:
    return load_snapshot()
