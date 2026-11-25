"""Mascaramento de PII antes do LLM, do log e do checkpoint (REQ-50, REQ-51, REQ-52).

Os formatos cobrem o que o dataset tem E o que ele não tem (achado D6): CPF sem
pontuação, telefone sem +55/DDD, placa no padrão antigo.
Todos os dados abaixo são fictícios.
"""

import pytest

from autoseguro_agent.pii import InMemoryVault, PiiMasker, cep_log_prefix, contains_pii

CONV = "conv-1"


@pytest.fixture
def masker() -> PiiMasker:
    return PiiMasker(InMemoryVault())


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("meu cpf é 529.982.247-25", "CPF"),
        ("cpf 52998224725", "CPF"),  # sem pontuação, dígitos verificadores válidos
        ("email ana.souza12@gmail.com ok", "EMAIL"),
        ("ANA_SOUZA@empresa.com.br", "EMAIL"),
        ("whats +55 11 98765-4321", "TEL"),
        ("tel (11) 98765-4321", "TEL"),
        ("liga 11 98765-4321", "TEL"),
        ("cel 98765-4321", "TEL"),  # sem DDD
        ("fixo 3456-7890", "TEL"),  # 8 dígitos
        ("11987654321", "TEL"),  # 11 dígitos que não fecham como CPF
        ("placa ABC1D23", "PLACA"),  # Mercosul
        ("placa abc1d23", "PLACA"),
        ("placa ABC-1234", "PLACA"),  # antiga
        ("placa ABC1234", "PLACA"),
        ("cep 01310-100", "CEP"),
        ("cep 01310100", "CEP"),
        ("cep 01.310-100", "CEP"),
    ],
)
def test_masks_each_format(masker: PiiMasker, text: str, kind: str) -> None:
    result = masker.mask(text, CONV)
    assert f"<{kind}_1>" in result.text
    assert kind in result.kinds
    assert not contains_pii(result.text)


def test_message_like_the_dataset(masker: PiiMasker) -> None:
    text = "Cep 01310-100, cpf 529.982.247-25, tenho 35 anos"
    result = masker.mask(text, CONV)
    assert result.text == "Cep <CEP_1>, cpf <CPF_1>, tenho 35 anos"


def test_keeps_what_the_agent_needs(masker: PiiMasker) -> None:
    """Idade, ano, modelo e plano não são PII e precisam chegar ao LLM."""
    text = "tenho 35 anos, um Onix 2022, quero o plano premium, começo dia 15/12/2026"
    assert masker.mask(text, CONV).text == text


@pytest.mark.parametrize("text", ["gol2012", "ano 2022", "R$ 209,90", "franquia de 3000"])
def test_no_false_positives(masker: PiiMasker, text: str) -> None:
    assert masker.mask(text, CONV).text == text


def test_same_value_same_token_within_conversation(masker: PiiMasker) -> None:
    a = masker.mask("cpf 529.982.247-25", CONV).text
    b = masker.mask("de novo: 52998224725", CONV).text
    assert "<CPF_1>" in a
    assert "<CPF_1>" in b


def test_tokens_are_per_conversation(masker: PiiMasker) -> None:
    masker.mask("cep 01310-100", "conv-a")
    result = masker.mask("cep 20040-020", "conv-b")
    assert "<CEP_1>" in result.text


def test_vault_resolves_only_within_its_conversation() -> None:
    vault = InMemoryVault()
    masker = PiiMasker(vault)
    masker.mask("cep 01310100", CONV)
    assert vault.resolve(CONV, "<CEP_1>") == "01310-100"  # guardado normalizado
    assert vault.resolve("outra", "<CEP_1>") is None
    assert vault.resolve(CONV, "<CEP_2>") is None


def test_cep_log_prefix() -> None:
    assert cep_log_prefix("01310-100") == "01310-***"


def test_contains_pii_detects_raw_values() -> None:
    assert contains_pii("cpf 529.982.247-25")
    assert not contains_pii("tenho 35 anos e um carro 2022")
