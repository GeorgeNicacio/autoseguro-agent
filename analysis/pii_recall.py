"""Recall do mascarador do agente contra o dataset (SMART M-10, M-09).

Compara quantos dados pessoais o `pii.py` do agente mascara com as contagens da
regex de referência (`dataset_report.py`) e confere que nada cru sobra depois.
Imprime só contagens.

    cd agent && py -m uv run --with polars python ../analysis/pii_recall.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import polars as pl

from autoseguro_agent.pii import InMemoryVault, PiiMasker, contains_pii

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = {"CPF": 2500, "EMAIL": 1379, "TEL": 1379, "PLACA": 839, "CEP": 2500}
TOKEN = re.compile(r"<(EMAIL|CPF|PLACA|CEP|TEL)_\d+>")
AGE = re.compile(r"\b\d{1,3} anos\b")


def main() -> int:
    df = pl.read_parquet(ROOT / "dataset" / "conversations.parquet").filter(
        (pl.col("sender_role") == "lead") & (pl.col("message_type") == "text")
    )
    masker = PiiMasker(InMemoryVault())
    counts: Counter[str] = Counter()
    leaks = 0
    ages_before = ages_after = 0

    for conv, body in df.select("conversation_id", "message_body").iter_rows():
        masked = masker.mask(body, conv).text
        counts.update(TOKEN.findall(masked))
        leaks += contains_pii(masked)
        ages_before += len(AGE.findall(body))
        ages_after += len(AGE.findall(masked))

    print(f"Mensagens de texto de leads: {df.height}")
    print("| Tipo | Referência | Mascarados pelo agente | Recall |")
    print("|---|---|---|---|")
    for kind, ref in REFERENCE.items():
        got = counts[kind]
        print(f"| {kind} | {ref} | {got} | {100 * got / ref:.1f}% |")
    print(f"\nMensagens com PII crua depois do mascaramento: {leaks}")
    print(f"Idades preservadas (não confundidas com PII): {ages_after}/{ages_before}")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
