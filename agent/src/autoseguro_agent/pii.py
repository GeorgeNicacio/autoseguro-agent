"""Mascaramento de PII + cofre de tokens (REQ-50..52).

Aplicado na ENTRADA, antes do LLM, do log e do checkpoint. O texto passa a ter
tokens estáveis por conversa (`<CPF_1>`, `<CEP_1>`...); o valor real fica só no
cofre e é resolvido em dois momentos: o CEP na chamada ao /quote e os dados no
resumo do handoff.

Por que regex e não um NER: os formatos brasileiros são fechados e a regex testada
é previsível, rápida e auditável. Presidio com reconhecedores BR fica como "faria".
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

PiiKind = Literal["EMAIL", "CPF", "PLACA", "CEP", "TEL"]

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CPF_FORMATTED = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_DIGITS_11 = re.compile(r"(?<![\d.\-/])\d{11}(?![\d.\-/])")
_PLACA = re.compile(
    r"\b[A-Za-z]{3}\d[A-Za-z]\d{2}\b"  # Mercosul (padrão distinto: aceita minúsculas)
    r"|\b[A-Z]{3}-?\d{4}\b"  # antiga, maiúsculas
    r"|\b[A-Za-z]{3}-\d{4}\b"  # antiga com hífen, qualquer caixa
)
_CEP = re.compile(r"(?<![\d.\-/])(?:\d{5}-\d{3}|\d{2}\.\d{3}-\d{3}|\d{8})(?![\d\-/])")
_TEL = re.compile(
    r"\+55[\s-]?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}"  # +55 DD 9XXXX-XXXX
    r"|\(\d{2}\)\s?9?\d{4}[\s-]?\d{4}"  # (DD) 9XXXX-XXXX
    r"|(?<![\d.\-/])\d{2}\s9?\d{4}-?\d{4}(?![\d\-/])"  # DD 9XXXX-XXXX
    r"|(?<![\d.\-/])9?\d{4}-\d{4}(?![\d\-/])"  # 9XXXX-XXXX ou XXXX-XXXX (sem DDD)
    r"|(?<![\d.\-/])\d{10,11}(?![\d.\-/])"  # 10/11 dígitos colados (CPF válido já saiu)
)
_TOKEN = re.compile(r"<(?:EMAIL|CPF|PLACA|CEP|TEL)_\d+>")
_NON_DIGIT = re.compile(r"\D")


def is_valid_cpf(digits: str) -> bool:
    """Dígitos verificadores do CPF: separa CPF sem pontuação de telefone de 11 dígitos."""
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    nums = [int(d) for d in digits]
    for size in (9, 10):
        total = sum(n * w for n, w in zip(nums[:size], range(size + 1, 1, -1), strict=True))
        check = (total * 10) % 11 % 10
        if check != nums[size]:
            return False
    return True


def _normalize(kind: PiiKind, raw: str) -> str:
    if kind == "EMAIL":
        return raw.lower()
    if kind == "PLACA":
        return raw.upper().replace("-", "")
    digits = _NON_DIGIT.sub("", raw)
    if kind == "CEP":
        return f"{digits[:5]}-{digits[5:]}"
    if kind == "TEL":
        return digits[2:] if digits.startswith("55") and len(digits) > 11 else digits
    return digits  # CPF


def cep_log_prefix(cep: str) -> str:
    """No log, só o prefixo de 5 dígitos (REQ-52)."""
    return f"{_NON_DIGIT.sub('', cep)[:5]}-***"


class Vault(Protocol):
    def put(self, conversation_id: str, kind: PiiKind, value: str) -> str: ...
    def resolve(self, conversation_id: str, token: str) -> str | None: ...


@dataclass
class InMemoryVault:
    """Cofre local separado do estado do grafo. Em produção: tabela cifrada com acesso restrito."""

    _by_token: dict[tuple[str, str], str] = field(default_factory=dict)
    _by_value: dict[tuple[str, str, str], str] = field(default_factory=dict)
    _counters: dict[tuple[str, str], int] = field(default_factory=dict)

    def put(self, conversation_id: str, kind: PiiKind, value: str) -> str:
        key = (conversation_id, kind, value)
        if key in self._by_value:
            return self._by_value[key]
        n = self._counters.get((conversation_id, kind), 0) + 1
        self._counters[(conversation_id, kind)] = n
        token = f"<{kind}_{n}>"
        self._by_value[key] = token
        self._by_token[(conversation_id, token)] = value
        return token

    def resolve(self, conversation_id: str, token: str) -> str | None:
        return self._by_token.get((conversation_id, token))


@dataclass(frozen=True)
class MaskResult:
    text: str
    kinds: tuple[PiiKind, ...]


class PiiMasker:
    def __init__(self, vault: Vault) -> None:
        self._vault = vault

    def mask(self, text: str, conversation_id: str) -> MaskResult:
        found: list[PiiKind] = []

        def replacer(
            kind: PiiKind, accept: Callable[[str], bool] | None = None
        ) -> Callable[[re.Match[str]], str]:
            def _sub(m: re.Match[str]) -> str:
                raw = m.group(0)
                if accept is not None and not accept(raw):
                    return raw
                found.append(kind)
                return self._vault.put(conversation_id, kind, _normalize(kind, raw))

            return _sub

        # Ordem importa: e-mail (tem dígitos) > CPF > placa > CEP > telefone.
        text = _EMAIL.sub(replacer("EMAIL"), text)
        text = _CPF_FORMATTED.sub(replacer("CPF"), text)
        text = _DIGITS_11.sub(replacer("CPF", is_valid_cpf), text)
        text = _PLACA.sub(replacer("PLACA"), text)
        text = _CEP.sub(replacer("CEP"), text)
        text = _TEL.sub(replacer("TEL"), text)
        return MaskResult(text=text, kinds=tuple(dict.fromkeys(found)))


def contains_pii(text: str) -> bool:
    """Detector para defesa em profundidade (processor do log) e para os testes M-09."""
    stripped = _TOKEN.sub("", text)
    if _EMAIL.search(stripped) or _CPF_FORMATTED.search(stripped):
        return True
    if any(is_valid_cpf(m.group(0)) for m in _DIGITS_11.finditer(stripped)):
        return True
    return bool(_PLACA.search(stripped) or _CEP.search(stripped) or _TEL.search(stripped))
