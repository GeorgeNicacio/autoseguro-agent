"""Regras de cotação lidas de GET /planos, com snapshot versionado como fallback.

Estas regras servem para VALIDAR antes de chamar a API e para RESPONDER dúvidas
sobre planos. Elas nunca são usadas para calcular preço: preço só vem do /quote.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from importlib.resources import files
from typing import Any


@dataclass(frozen=True)
class Plan:
    id: str
    nome: str
    franquia: int
    coberturas: tuple[str, ...]


@dataclass(frozen=True)
class Band:
    """Faixa de idade (condutor ou veículo). `refuse` = a API recusa com `motivo`."""

    min: int
    max: int
    refuse: bool
    motivo: str | None

    def contains(self, value: int) -> bool:
        return self.min <= value <= self.max


@dataclass(frozen=True)
class PlanRules:
    plans: tuple[Plan, ...]
    driver_bands: tuple[Band, ...]
    vehicle_bands: tuple[Band, ...]
    high_risk_cep_prefixes: tuple[str, ...]
    carencia_dias: int
    carencia_coberturas: tuple[str, ...]

    @classmethod
    def from_planos(cls, data: dict[str, Any]) -> PlanRules:
        regras = data["regras"]
        return cls(
            plans=tuple(
                Plan(
                    id=p["id"],
                    nome=p["nome"],
                    franquia=int(p["franquia"]),
                    coberturas=tuple(p["coberturas"]),
                )
                for p in data["planos"]
            ),
            driver_bands=tuple(
                Band(f["idade_min"], f["idade_max"], bool(f.get("recusar")), f.get("motivo"))
                for f in regras["faixa_etaria"]
            ),
            vehicle_bands=tuple(
                Band(f["anos_min"], f["anos_max"], bool(f.get("recusar")), f.get("motivo"))
                for f in regras["idade_veiculo"]
            ),
            high_risk_cep_prefixes=tuple(regras["regiao_cep"]["prefixos_alto_risco"]),
            carencia_dias=int(regras["carencia"]["dias"]),
            carencia_coberturas=tuple(regras["carencia"]["coberturas_com_carencia"]),
        )

    @property
    def version(self) -> str:
        """Hash das regras: entra na chave do cache de cotação (mudou a regra, muda a chave)."""
        raw = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def plan(self, plan_id: str) -> Plan | None:
        return next((p for p in self.plans if p.id == plan_id), None)

    def driver_band(self, idade: int) -> Band | None:
        return next((b for b in self.driver_bands if b.contains(idade)), None)

    def vehicle_band(self, anos: int) -> Band | None:
        return next((b for b in self.vehicle_bands if b.contains(anos)), None)

    def is_high_risk_cep(self, cep: str) -> bool:
        return cep.replace("-", "")[:2] in self.high_risk_cep_prefixes


def load_snapshot() -> PlanRules:
    """Snapshot de GET /planos salvo em 2026-11-25 (fallback se a API não responder)."""
    raw = files("autoseguro_agent.domain").joinpath("plans_snapshot.json").read_text("utf-8")
    return PlanRules.from_planos(json.loads(raw))
