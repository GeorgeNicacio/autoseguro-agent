# /// script
# requires-python = ">=3.12"
# dependencies = ["polars>=1.0"]
# ///
"""Análise agregada do dataset de conversas (tarefa T1.3).

Regra de privacidade: este script só imprime CONTAGENS e PERCENTUAIS. Nenhuma
mensagem, nome ou dado pessoal sai daqui — nem no terminal, nem no relatório.

    py -m uv run analysis/dataset_report.py --out docs/evidence/dataset_report.md

O ano de referência para a idade do veículo é fixo (como o Clock do agente),
para o relatório ser reproduzível.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import polars as pl

# Regex de REFERÊNCIA (independentes do pii.py do agente, que vem depois e será
# comparado contra estas contagens — métrica SMART M-10).
PII_PATTERNS = {
    "cpf": r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b",
    "email": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "telefone": r"(?:\+55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}",
    "placa": r"\b[A-Z]{3}-?\d[A-Z0-9]\d{2}\b",
    "cep": r"\b\d{5}-?\d{3}\b",
}

# Objeções / pedidos que viram regra de handoff ou cenário do golden set.
OBJECTIONS = {
    "preco_caro": r"caro|salgad",
    "franquia": r"franquia",
    "concorrente": r"concorrente|porto seguro|azul seguros|bradesco|sulamerica|itau",
    "vou_pensar": r"pensar|esposa|marido",
}

HIGH_RISK_CEP = ("07", "08", "21", "26", "59")


def pct(part: int, total: int) -> str:
    return f"{100 * part / total:.1f}%" if total else "0%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset/conversations.parquet")
    ap.add_argument("--ref-year", type=int, default=2026)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    df = pl.read_parquet(args.data).with_columns(
        pl.col("timestamp").str.to_datetime()
    ).sort(["conversation_id", "message_index"])

    n_msgs = df.height
    convs = df.unique("conversation_id", keep="first")
    n_conv = convs.height
    lines: list[str] = []
    w = lines.append

    w("# Análise do dataset de conversas (T1.3)\n")
    w(f"Gerado por `analysis/dataset_report.py` · ano de referência {args.ref_year} · "
      "só agregados, nenhuma mensagem crua.\n")

    # 1. Volume e desfechos ---------------------------------------------------
    w("## 1. Volume e desfechos\n")
    w(f"- {n_conv} conversas, {n_msgs} mensagens "
      f"(média {n_msgs / n_conv:.1f} por conversa).")
    w("\n| Desfecho | Conversas | % |\n|---|---|---|")
    for row in convs.group_by("conversation_outcome").len().sort("len", descending=True).iter_rows():
        w(f"| {row[0]} | {row[1]} | {pct(row[1], n_conv)} |")

    # 2. Ganho x perdido: há sinal? -------------------------------------------
    w("\n## 2. Ganho × perdido: existe sinal nos dados?\n")
    first_vendor = (
        df.filter(pl.col("sender_role") == "vendedor")
        .group_by("conversation_id").agg(pl.col("timestamp").min().alias("t_vend"))
    )
    first_msg = df.group_by("conversation_id").agg(pl.col("timestamp").min().alias("t0"))
    per_conv = (
        convs.select("conversation_id", "conversation_outcome")
        .join(first_msg, on="conversation_id")
        .join(first_vendor, on="conversation_id", how="left")
        .join(df.group_by("conversation_id").len().rename({"len": "n_msgs"}), on="conversation_id")
        .join(
            df.group_by("conversation_id").agg(
                (pl.col("message_type") != "text").sum().alias("n_media")),
            on="conversation_id",
        )
        .with_columns(((pl.col("t_vend") - pl.col("t0")).dt.total_minutes()).alias("min_1a_resposta"))
    )
    stats = (
        per_conv.group_by("conversation_outcome")
        .agg(
            pl.col("min_1a_resposta").median().alias("med_min"),
            pl.col("n_msgs").mean().alias("msgs"),
            pl.col("n_media").mean().alias("midia"),
        ).sort("conversation_outcome")
    )
    w("| Desfecho | 1ª resposta do vendedor (mediana, min) | Mensagens (média) | Mídias (média) |")
    w("|---|---|---|---|")
    for o, m, msgs, mid in stats.iter_rows():
        w(f"| {o} | {m:.0f} | {msgs:.1f} | {mid:.2f} |")

    non_monotonic = (
        df.with_columns(pl.col("timestamp").diff().over("conversation_id").alias("dt"))
        .filter(pl.col("dt") < pl.duration(seconds=0))
        .select("conversation_id").unique().height
    )
    w(f"\n- Conversas com timestamp **voltando no tempo**: {non_monotonic} "
      f"({pct(non_monotonic, n_conv)}). Ordenar por `message_index`, nunca por `timestamp`; "
      "por isso o tempo de 1ª resposta acima **não é confiável**.")
    w("- **Conclusão honesta:** as métricas por desfecho são praticamente iguais. O gerador "
      "(`scripts/generate_dataset.py`) sorteia o desfecho de forma independente do perfil, do carro "
      "e das mensagens, então o dataset **não** sustenta regras do tipo \"X aumenta conversão\". "
      "As regras do agente se justificam pela política comercial e pelo `/planos`; o dataset serve "
      "para formatos de PII, volume de casos, objeções e cenários de teste.")

    # 3. Mídia -----------------------------------------------------------------
    w("\n## 3. Mídia sem transcrição\n")
    w("| Tipo | Mensagens | Conversas com ao menos uma | % das conversas |\n|---|---|---|---|")
    for t in ("document", "image", "audio"):
        n_m = df.filter(pl.col("message_type") == t).height
        n_c = df.filter(pl.col("message_type") == t).select("conversation_id").unique().height
        w(f"| {t} | {n_m} | {n_c} | {pct(n_c, n_conv)} |")
    any_media = df.filter(pl.col("message_type") != "text").select("conversation_id").unique().height
    w(f"\n- Conversas com **qualquer** mídia: {any_media} ({pct(any_media, n_conv)}).")

    # 4. PII -------------------------------------------------------------------
    w("\n## 4. Dados pessoais no texto livre (regex de referência)\n")
    text = df.filter(pl.col("message_type") == "text")
    lead_text = text.filter(pl.col("sender_role") == "lead")
    w("| Tipo | Ocorrências | Conversas com ao menos uma | % das conversas |\n|---|---|---|---|")
    for name, rx in PII_PATTERNS.items():
        counts = lead_text.with_columns(
            pl.col("message_body").str.count_matches(rx).alias("c"))
        occ = int(counts["c"].sum())
        c_conv = counts.filter(pl.col("c") > 0).select("conversation_id").unique().height
        w(f"| {name} | {occ} | {c_conv} | {pct(c_conv, n_conv)} |")
    asked_cpf = text.filter(
        (pl.col("sender_role") == "vendedor") & pl.col("message_body").str.contains("(?i)cpf")
    ).select("conversation_id").unique().height
    w(f"\n- Conversas em que o **vendedor pediu CPF** para cotar: {asked_cpf} "
      f"({pct(asked_cpf, n_conv)}). O `/quote` não usa CPF: o agente não pede (minimização).")
    placa_formats = lead_text.select(
        pl.col("message_body").str.extract_all(PII_PATTERNS["placa"]).alias("p")
    ).explode("p").drop_nulls()
    mercosul = placa_formats.filter(pl.col("p").str.contains(r"^[A-Z]{3}\d[A-Z]\d{2}$")).height
    w(f"- Placas: {placa_formats.height} no total, {mercosul} no padrão Mercosul "
      f"({pct(mercosul, placa_formats.height)}); o mascarador cobre os dois padrões mesmo assim.")

    # 5. Perfil vs regras do /quote ---------------------------------------------
    w("\n## 5. Perfil dos leads frente às regras do `/quote`\n")
    prof = convs.with_columns(
        pl.col("veiculo_texto").str.extract(r"(\d{4})\s*$").cast(pl.Int32).alias("ano")
    ).with_columns((args.ref_year - pl.col("ano")).alias("idade_veic"))
    over75 = prof.filter(pl.col("lead_idade_informada") > 75).height
    under18 = prof.filter(pl.col("lead_idade_informada") < 18).height
    old_car = prof.filter(pl.col("idade_veic") > 20).height
    refused = prof.filter(
        (pl.col("lead_idade_informada") > 75) | (pl.col("idade_veic") > 20)
        | (pl.col("lead_idade_informada") < 18)
    ).height
    w(f"- Condutor acima de 75 anos (recusa): {over75} ({pct(over75, n_conv)}).")
    w(f"- Condutor abaixo de 18 anos: {under18}.")
    w(f"- Veículo com mais de 20 anos em {args.ref_year} (recusa): {old_car} ({pct(old_car, n_conv)}).")
    w(f"- **Cairiam em `out_of_policy`** (qualquer recusa): {refused} ({pct(refused, n_conv)}). "
      "Validação local evita gastar chamada e retry nesses casos.")

    w("\n| Faixa etária do condutor | Multiplicador | Conversas | % |\n|---|---|---|---|")
    bands = [(18, 24, "1,60"), (25, 29, "1,25"), (30, 59, "1,00"), (60, 75, "1,40"), (76, 200, "recusa")]
    for lo, hi, mult in bands:
        c = prof.filter(pl.col("lead_idade_informada").is_between(lo, hi)).height
        w(f"| {lo}–{hi if hi < 200 else '+'} | {mult} | {c} | {pct(c, n_conv)} |")

    lead_ceps = lead_text.select(
        pl.col("message_body").str.extract_all(PII_PATTERNS["cep"]).alias("c")
    ).explode("c").drop_nulls()
    high = lead_ceps.filter(pl.col("c").str.slice(0, 2).is_in(list(HIGH_RISK_CEP))).height
    w(f"\n- CEPs de alto risco (×1,30): {high} de {lead_ceps.height} ({pct(high, lead_ceps.height)}).")

    # 6. Objeções ----------------------------------------------------------------
    w("\n## 6. Objeções e pedidos do lead\n")
    w("| Objeção | Conversas | % | Vira |\n|---|---|---|---|")
    destino = {
        "preco_caro": "`price_negotiation` se pedir desconto; senão comparar planos",
        "franquia": "explicar franquia do `/planos`; comparar planos",
        "concorrente": "`price_negotiation` (cobrir concorrente)",
        "vou_pensar": "resumo + oferta de retomar; sem handoff",
    }
    for name, rx in OBJECTIONS.items():
        c = lead_text.filter(pl.col("message_body").str.contains(f"(?i){rx}")) \
            .select("conversation_id").unique().height
        w(f"| {name} | {c} | {pct(c, n_conv)} | {destino[name]} |")
    uber = lead_text.filter(
        pl.col("message_body").str.contains(r"(?i)\buber\b|\b99 ?pop\b|\baplicativo\b|\bentregas?\b|\bifood\b")) \
        .select("conversation_id").unique().height
    w(f"\n- Menções a uso comercial (Uber, aplicativo, entregas): {uber}. "
      "O cenário existe nas regras (`commercial_use`) mas não no dataset: entra no golden set como caso sintético.")

    # 7. Preço do vendedor --------------------------------------------------------
    vend_price = text.filter(
        (pl.col("sender_role") == "vendedor") & pl.col("message_body").str.contains(r"R\$")
    ).select("conversation_id").unique().height
    w("\n## 7. Preço nas conversas históricas\n")
    w(f"- Conversas com preço escrito pelo vendedor: {vend_price} ({pct(vend_price, n_conv)}). "
      "Esses valores **não** seguem a fórmula do `/quote` e nunca entram em few-shot "
      "(reforça: preço só da API).")

    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
