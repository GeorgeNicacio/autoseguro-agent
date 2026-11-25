# SDD 03 — Tarefas

> Ordem de execução. Cada tarefa cita os requisitos que fecha e o teste que prova.
> Regra: **teste primeiro** (TDD), `make test` verde antes de cada commit.
> Se o tempo apertar, corte do Dia 3 para trás — **nunca** a resiliência (Dia 2).

## Dia 0 — Preparação (30 min)

- [ ] T0.1 Avisar quem enviou o desafio que começou; anotar horário no `ai-logs/README.md`.
- [x] T0.2 Instalar `uv`: `py -m pip install --user uv` (0.13.10; fora do PATH nesta máquina → usar `py -m uv`).
- [ ] T0.3 **Repo novo** (decidido 2026-11-25): criar repo público próprio, preservando o histórico do upstream (`quote-service/`, `dataset/` intocados); renomear o remote original para `upstream` e apontar `origin` para o repo novo. Créditos ao upstream no README.
- [ ] T0.4 `CLAUDE.md` com as regras do projeto (já rascunhado na raiz).
- [ ] T0.5 Sessões do Claude Code já ficam em `~/.claude/projects/<slug>/*.jsonl` — exportar no fim.

## Dia 1 — Entender e caminho feliz

- [x] T1.1 `docker compose up --build`; `GET /health`; salvar `GET /planos` em `agent/src/autoseguro_agent/domain/plans_snapshot.json`. *(snapshot idêntico ao `plans.json`)*
- [x] T1.2 `scripts/characterize_quote.py`: 200 chamadas → taxa de 5xx, de lentidão, p50/p95. Número vai para o README. *(evidência SMART M-01)*
- [x] T1.3 `analysis/dataset_report.py` (polars) → [`dataset_report.md`](../evidence/dataset_report.md) + [`dataset_findings.md`](../evidence/dataset_findings.md): desfechos, objeções frequentes, PII por conversa, carros > 20 anos. Só agregados, nada cru.
- [x] T1.4 Scaffold `agent/` com uv, ruff, mypy, pytest, Makefile.
- [x] T1.5 `domain/models.py` + `rules.py` + `eligibility.py` — testes de fronteira, incluindo data default = 1º do mês seguinte com `Clock` fixo (25/11/2026 → 01/12/2026; 31/12 → 01/01 do ano seguinte). **REQ-01, 10, 11**
- [x] T1.5b `domain/recommendation.py` — `recommend_plan` com teste por faixa de idade do veículo. **REQ-06**
- [x] T1.6 Teste de contrato com o exemplo do README (209,90 / 115,11). **REQ-13**
- [x] T1.7 `pii.py` + Vault — testes por formato e colisão CPF×telefone (dígito verificador). Recall 100% no dataset ([evidência](../evidence/pii_recall.md)). **REQ-50, 51**
- [x] T1.8 `ports.py`, `FakeLLM`, `templates.py`, `OutputValidator` (+ contratos de extração, cotação e eventos; `FixedClock`). **REQ-13**
- [x] T1.9 Grafo mínimo: ingest → mask → extract → route → ask/quote(sem retry) → present → validate_out. **REQ-01, 02**
- [x] T1.10 CLI de chat ponta a ponta (`--fake-llm`, `--events`, `--script`) contra a API real. *Pendente: rodar com o Claude real quando houver `ANTHROPIC_API_KEY` em `agent/.env`.*

## Dia 2 — Falhas, handoff e rastreio (onde está a nota)

- [x] T2.1 `CircuitBreaker` com `Clock` fake — testes de transição. **REQ-24**
- [x] T2.2 `HttpQuoteGateway`: timeout, retry+jitter, orçamento, mapeamento 200/422×2/400/5xx/lento — 1 teste respx por linha. **REQ-20..27**
- [x] T2.3 Mensagem de espera (> 4 s) e de falha honesta, por template. **REQ-23, 25**
- [x] T2.4 *(adiantada no Dia 1)* `decide_handoff` + tabela + 1 teste por regra + teste de prioridade; nó `handoff` com resumo. **REQ-30..32**
- [x] T2.5 `SqliteEventStore` append-only (triggers) + structlog com ids; `GET /conversations/{id}`. **REQ-40..42**
- [x] T2.6 Teste de caos (FAILURE 0.6, SLOW 0.2, SEED fixo, 50 conversas). **REQ-22, 25** *(SMART M-02..04)*
- [x] T2.7 Webhook FastAPI + dedup por `wa_message_id`. **REQ-43, 60** Commit + push.

## Dia 3 — Evidências, avaliação e README

- [x] T3.1 Golden set (10–15 cenários, ver lista abaixo) com FakeLLM; tabela passou/falhou no README. *(SMART M-05)*
- [x] T3.2 `make demo` com `QUOTE_SEED` que garanta ≥ 1 falha + retry visível → `docs/demo-conversation.md`. **REQ-62**
- [x] T3.3 README (esqueleto do plano) + `docs/DECISIONS.md` (ADRs curtos).
- [x] T3.4 `scripts/sanitize_ai_logs.py` + exportar sessões → `ai-logs/` + `ai-logs/README.md`. **REQ-53**
- [x] T3.5 Clone limpo → seguir só o README → `docker compose up` + `make demo` (validado em 2026-11-25 com os comandos do alvo, só Docker).
- [ ] T3.6 Grep final: `sk-`, `key`, e-mail e telefone pessoais. Enviar link.

## Golden set (rascunho)

| # | Cenário | Esperado |
|---|---|---|
| G01 | Caminho feliz (35 anos, 2022, CEP SP, completo) | cotação 209,90 por template |
| G02 | Jovem 22 anos | ×1,60 vindo da API |
| G03 | Carro 2003 | recusa local, sem chamada, handoff `out_of_policy` |
| G04 | Idade 80 | recusa local, handoff `out_of_policy` |
| G05 | CEP alto risco (21…) | ×1,30 vindo da API |
| G06 | Pede humano no meio | handoff `explicit_request` imediato |
| G07 | Manda foto da CNH, depois responde por texto | aviso "não preciso do arquivo", segue e cota; sem handoff |
| G07b | Responde áudio 2× à mesma pergunta | `media_unsupported` |
| G08 | Pede desconto após cotação | `price_negotiation` |
| G09 | Manda CPF sem pedir | mascarado, aviso de minimização, segue |
| G10 | API fora do ar (FAILURE=1.0) | mensagem honesta + `infra_unavailable`, zero R$ |
| G11 | API lenta 1× e depois ok | espera + retry + cotação |
| G12 | CEP inválido 2× | `stuck` |
| G13 | Sinistro / cancelamento | `out_of_scope` |
| G14 | Uso para Uber | `out_of_scope` (`commercial_use`) |
| G15 | Cotou e quer fechar | `ready_to_close` com resumo |
| G16 | "Não sei qual plano" (carro 2012) | 1 cotação do `essencial` recomendado + oferta de completo/premium sem R$ |
| G17 | "A franquia tá alta" após cotação | explica franquias do `/planos`, oferece recotar plano com franquia menor; sem handoff |
| G18 | "Vou pensar" | resumo da cotação + oferta de retomar; conversa fica `quoted`, sem handoff |
| G19 | Condutor de 65 anos | ×1,40 vindo da API |
