"""Validação local antes de chamar o /quote (REQ-10, REQ-11)."""

from datetime import date

import pytest

from autoseguro_agent.domain.eligibility import (
    default_start_date,
    normalize_cep,
    policy_refusal,
    validate_data_inicio,
    validate_idade,
    validate_plano,
    validate_veiculo_ano,
)
from autoseguro_agent.domain.models import LeadProfile
from autoseguro_agent.domain.rules import PlanRules

# --- formato de cada dado (erro = pedir correção ao lead) -----------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01310-100", "01310-100"),
        ("01310100", "01310-100"),
        (" 01.310-100 ", "01310-100"),
        ("1310-100", None),  # 7 dígitos
        ("013101000", None),  # 9 dígitos
        ("abcde-fgh", None),
        ("", None),
    ],
)
def test_normalize_cep(raw: str, expected: str | None) -> None:
    assert normalize_cep(raw) == expected


@pytest.mark.parametrize("idade", [0, -3, 121])
def test_idade_implausivel_e_erro_de_formato(idade: int) -> None:
    err = validate_idade(idade)
    assert err is not None
    assert err.code == "idade_invalida"


@pytest.mark.parametrize("idade", [17, 18, 75, 76, 90])
def test_idade_plausivel_nao_e_erro_de_formato(idade: int) -> None:
    """Abaixo de 18 ou acima de 75 é política (recusa), não erro de digitação."""
    assert validate_idade(idade) is None


def test_ano_no_futuro_e_erro(today: date) -> None:
    err = validate_veiculo_ano(today.year + 1, today)
    assert err is not None
    assert err.code == "veiculo_ano_futuro"


def test_ano_muito_antigo_fora_do_schema_da_api(today: date) -> None:
    """A API devolve 422 de schema abaixo de 1950: o agente pega antes."""
    err = validate_veiculo_ano(1949, today)
    assert err is not None
    assert err.code == "veiculo_ano_invalido"


@pytest.mark.parametrize("ano", [1950, 2003, 2026])
def test_ano_valido(ano: int, today: date) -> None:
    assert validate_veiculo_ano(ano, today) is None


def test_data_inicio_no_passado_e_erro(today: date) -> None:
    err = validate_data_inicio(date(2026, 7, 15), today)
    assert err is not None
    assert err.code == "data_inicio_passada"


def test_data_inicio_hoje_ou_futura(today: date) -> None:
    assert validate_data_inicio(today, today) is None
    assert validate_data_inicio(date(2027, 1, 10), today) is None


def test_plano_desconhecido(rules: PlanRules) -> None:
    err = validate_plano("ouro", rules)
    assert err is not None
    assert err.code == "plano_invalido"
    assert validate_plano("premium", rules) is None


# --- data de início padrão: 1º do mês seguinte (decisão 2026-11-25) --------------


@pytest.mark.parametrize(
    ("hoje", "esperado"),
    [
        (date(2026, 11, 25), date(2026, 12, 1)),
        (date(2026, 12, 31), date(2027, 1, 1)),
        (date(2027, 1, 1), date(2027, 2, 1)),
    ],
)
def test_default_start_date(hoje: date, esperado: date) -> None:
    assert default_start_date(hoje) == esperado


# --- política (recusa = handoff out_of_policy, sem chamar a API) ------------------


@pytest.mark.parametrize(
    ("idade", "code"),
    [(76, "condutor_acima_limite"), (82, "condutor_acima_limite"), (17, "condutor_abaixo_minimo")],
)
def test_recusa_por_idade(idade: int, code: str, rules: PlanRules, today: date) -> None:
    refusal = policy_refusal(LeadProfile(idade=idade), rules, today)
    assert refusal is not None
    assert refusal.code == code
    assert refusal.motivo


@pytest.mark.parametrize("idade", [18, 22, 35, 60, 75])
def test_idade_aceita(idade: int, rules: PlanRules, today: date) -> None:
    assert policy_refusal(LeadProfile(idade=idade), rules, today) is None


def test_recusa_veiculo_com_mais_de_20_anos(rules: PlanRules, today: date) -> None:
    refusal = policy_refusal(LeadProfile(veiculo_ano=today.year - 21), rules, today)
    assert refusal is not None
    assert refusal.code == "veiculo_acima_limite"
    assert "20 anos" in refusal.motivo


def test_veiculo_com_20_anos_e_aceito(rules: PlanRules, today: date) -> None:
    assert policy_refusal(LeadProfile(veiculo_ano=today.year - 20), rules, today) is None


def test_politica_funciona_com_perfil_parcial(rules: PlanRules, today: date) -> None:
    """Recusa assim que o dado chega: não precisa coletar o resto para fazer handoff."""
    assert policy_refusal(LeadProfile(), rules, today) is None
    assert policy_refusal(LeadProfile(idade=80), rules, today) is not None
