"""PlanRules: parse de GET /planos e snapshot versionado (REQ-10)."""

import json
from pathlib import Path

from autoseguro_agent.domain.rules import PlanRules

SERVICE_PLANS = Path(__file__).parents[3] / "quote-service" / "data" / "plans.json"


def test_snapshot_has_three_plans(rules: PlanRules) -> None:
    assert [p.id for p in rules.plans] == ["essencial", "completo", "premium"]


def test_snapshot_matches_service_source() -> None:
    """Se o quote-service mudar as regras, este teste avisa que o snapshot envelheceu."""
    service = PlanRules.from_planos(json.loads(SERVICE_PLANS.read_text(encoding="utf-8")))
    from autoseguro_agent.domain.rules import load_snapshot

    assert service == load_snapshot()


def test_plan_lookup(rules: PlanRules) -> None:
    premium = rules.plan("premium")
    assert premium is not None
    assert premium.franquia == 1500
    assert "assistencia_24h" in premium.coberturas
    assert rules.plan("ouro") is None


def test_driver_age_bands(rules: PlanRules) -> None:
    assert rules.driver_band(18) is not None
    assert rules.driver_band(75) is not None
    band_76 = rules.driver_band(76)
    assert band_76 is not None
    assert band_76.refuse
    assert band_76.motivo is not None
    assert rules.driver_band(17) is None  # sem faixa = recusa


def test_vehicle_age_bands(rules: PlanRules) -> None:
    band_20 = rules.vehicle_band(20)
    assert band_20 is not None
    assert not band_20.refuse
    band_21 = rules.vehicle_band(21)
    assert band_21 is not None
    assert band_21.refuse
    assert rules.vehicle_band(-1) is None  # ano no futuro


def test_high_risk_cep(rules: PlanRules) -> None:
    assert rules.is_high_risk_cep("21000-000")
    assert not rules.is_high_risk_cep("01310-100")


def test_carencia(rules: PlanRules) -> None:
    assert rules.carencia_dias == 30
    assert rules.carencia_coberturas == ("roubo", "furto")
