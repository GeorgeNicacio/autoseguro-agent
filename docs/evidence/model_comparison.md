# Comparativo de modelos do Claude no golden set

Medido em 2026-11-26 pelo dashboard (botão do golden set com seletor de modelo), contra o
quote-service real sem falha simulada. 24 cenários, mesmo prompt (`extract_v3`), `effort: low`,
prompt caching ligado, **sem** o cache Redis de extração (o golden avalia o modelo de verdade).
Os números vêm dos eventos `llm.call` de cada rodada (`GET /api/golden/history`).

## Antes da proteção determinística

| Modelo | Acerto | Custo da rodada | Custo por conversa | LLM p50 · p95 |
|---|---|---|---|---|
| Opus 5.5 | 24/24 | US$ 0,1613 | US$ 0,0067 | 1,58 s · 2,29 s |
| Sonnet 5.5 | 24/24 | US$ 0,0908 | US$ 0,0038 | 1,61 s · 2,30 s |
| Haiku 5.5 | 22/24 | US$ 0,0053 | US$ 0,0002 | 1,69 s · 3,15 s |

Falhas do Haiku: G01 (mensagem só com o CEP: devolveu vazio em vez de copiar `<CEP_1>`)
e G23 (variação: não extraiu "premium" numa rodada).

## Depois da proteção determinística

O que dá para extrair sem ambiguidade deixou de depender do modelo: um único token de CEP
na mensagem (o mascarador já provou que é um CEP) e um único nome de plano escrito.
O evento `slot.updated` registra `source: codigo` quando isso acontece.

| Modelo | Rodadas | Acerto | Custo por rodada | LLM p50 · p95 |
|---|---|---|---|---|
| Haiku 5.5 | 3 | **24/24 nas 3** | US$ 0,0048 a 0,0053 | 1,62 a 1,85 s · 2,07 a 3,11 s |
| Sonnet 5.5 | 1 | 24/24 | US$ 0,0908 | 1,53 s · 2,20 s |

## Leitura

- O **Haiku 5.5 é ~33× mais barato que o Opus 5.5** e ~18× mais barato que o Sonnet 5.5
  nesta tarefa, com latência equivalente (o tempo é dominado pela rede e pelo raciocínio
  mínimo de `effort: low`, não pelo tamanho do modelo).
- A tarefa do LLM aqui é estreita (extrair dados e marcar intenções em saída estruturada);
  o resto é código. Por isso um modelo pequeno basta, desde que o código feche as lacunas
  que não dependem de interpretação.
- Os tokens de entrada são quase todos leitura de prompt cache (~167 mil por rodada), o que
  barateia os três modelos.
- Recomendação: Haiku 5.5 como padrão, com o golden set rodando a cada mudança de prompt ou
  de modelo e o **modo sombra** (README) antes de trocar em produção.
