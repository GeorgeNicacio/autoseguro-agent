"""Sanitiza as sessões de IA antes de irem para o repositório público (REQ-53).

Remove: chaves e tokens de API, e-mails, CPF, telefones, CEPs, placas, nomes do
dataset sintético, o usuário do Windows nos caminhos e termos extras passados por
variável de ambiente (ex.: o e-mail e o telefone de quem fez o desafio), que por isso
nunca ficam escritos neste arquivo.

    SANITIZE_EXTRA="meu@email.com,11999999999" py scripts/sanitize_ai_logs.py \\
        --src ~/.claude/projects/<slug> --out ai-logs/claude-code
    py scripts/sanitize_ai_logs.py --check ai-logs     # falha se sobrou algo

Só biblioteca padrão. Os arquivos de entrada não são alterados.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Nomes usados pelo gerador do dataset sintético (scripts/generate_dataset.py).
NOMES = ("Ana|Bruno|Carla|Diego|Eduarda|Felipe|Gabriela|Hugo|Isabela|Joao|Karina|Lucas|"
         "Marina|Nicolas|Olivia|Paulo|Queila|Rafael|Sabrina|Thiago|Ursula|Vinicius|Wesley|Yara")
SOBRENOMES = ("Silva|Souza|Oliveira|Santos|Pereira|Costa|Almeida|Rodrigues|Ferreira|Gomes|"
              "Martins|Araujo|Barbosa|Ribeiro")

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("<API_KEY>", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,200}|sk-[A-Za-z0-9]{20,200}")),
    ("<GITHUB_TOKEN>", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("<AWS_KEY>", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("<BEARER>", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")),
    # Quantificadores limitados: sem limite, a regex fica quadrática nos blocos base64.
    # Não começa depois de "\" (evita "\n@app.get" em código colado no log).
    ("<EMAIL>", re.compile(r"(?<![\w.+\-\\])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,4}")),
    ("<CPF>", re.compile(r"(?<![\w.\-/])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\w\-/])")),
    ("<TEL>", re.compile(r"\+55[\s-]?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}")),
    ("<CEP>", re.compile(r"(?<![\w.\-/])\d{5}-\d{3}(?![\w\-/])")),
    ("<PLACA>", re.compile(r"\b[A-Z]{3}\d[A-Z]\d{2}\b|\b[A-Z]{3}-\d{4}\b")),
    ("<NOME>", re.compile(rf"\b(?:{NOMES})\s(?:{SOBRENOMES})\b")),
]

# Usuário do sistema nos caminhos. Troca só o nome e preserva o separador, seja `/`,
# `\` ou `\\\\` (JSON aninhado), para o .jsonl continuar sendo JSON válido.
USER_PATH = re.compile(r"(?i)(?<=users)(\\+|/)[^\\/\"\s<]+")
USER_SLUG = re.compile(r"(?i)(?<=c--users-)[A-Za-z0-9]+")


def extra_rules() -> list[tuple[str, re.Pattern[str]]]:
    """Termos separados por vírgula; prefixo `w:` casa só a palavra inteira (ex.: w:usuario)."""
    rules = []
    for raw in os.getenv("SANITIZE_EXTRA", "").split(","):
        term = raw.strip()
        if term.startswith("w:"):
            rules.append(("<REDACTED>", re.compile(r"\b" + re.escape(term[2:]) + r"\b")))
        elif term:
            rules.append(("<REDACTED>", re.compile(re.escape(term), re.IGNORECASE)))
    return rules


def sanitize(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for label, rx in [*extra_rules(), *RULES]:
        text, n = rx.subn(lambda _m, lbl=label: lbl, text)  # literal, sem escapes
        if n:
            counts[label] = counts.get(label, 0) + n
    text, n = USER_PATH.subn(lambda m: m.group(1) + "<user>", text)
    text, n2 = USER_SLUG.subn("<user>", text)
    if n + n2:
        counts["<user>"] = n + n2
    return text, counts


def check(paths: list[Path]) -> int:
    dangerous = [r for r in [*extra_rules(), *RULES][:5] if r[0] != "<EMAIL>"]
    dangerous += extra_rules()
    bad = 0
    for path in paths:
        for f in [path] if path.is_file() else sorted(path.rglob("*")):
            if not f.is_file():
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            for label, rx in dangerous:
                for m in rx.finditer(text):
                    if "<" not in m.group(0):
                        print(f"{f}: {label} ainda presente")
                        bad += 1
                        break
    print("ok: nada sensível encontrado" if not bad else f"{bad} ocorrência(s)")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, help="pasta ou arquivo de sessões (.jsonl, .md)")
    ap.add_argument("--out", type=Path, help="pasta de saída dentro de ai-logs/")
    ap.add_argument("--check", nargs="*", type=Path, help="só verifica, não altera")
    args = ap.parse_args()
    if args.check is not None:
        return check(args.check or [Path("ai-logs")])
    if not args.src or not args.out:
        ap.error("use --src e --out, ou --check")
    args.out.mkdir(parents=True, exist_ok=True)
    files = [args.src] if args.src.is_file() else sorted(
        p for p in args.src.iterdir() if p.suffix in {".jsonl", ".md", ".txt"}
    )
    total: dict[str, int] = {}
    for f in files:
        clean, counts = sanitize(f.read_text(encoding="utf-8", errors="replace"))
        (args.out / f.name).write_text(clean, encoding="utf-8", newline="\n")
        for k, v in counts.items():
            total[k] = total.get(k, 0) + v
        print(f"{f.name}: {sum(counts.values())} substituições")
    print("total por tipo:", dict(sorted(total.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
