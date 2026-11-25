# SDD 03 — Tarefas

> Ordem de execução. Cada tarefa cita os requisitos que fecha e o teste que prova.
> Regra: **teste primeiro** (TDD), `make test` verde antes de cada commit.
> Se o tempo apertar, corte do Dia 3 para trás — **nunca** a resiliência (Dia 2).

## Dia 0 — Preparação (30 min)

- [ ] T0.1 Avisar quem enviou o desafio que começou; anotar horário no `ai-logs/README.md`.
- [ ] T0.2 Instalar `uv` (não está nesta máquina): `py -m pip install uv` ou instalador oficial.
- [ ] T0.3 **Repo novo** (decidido 2026-11-25): criar repo público próprio, preservando o histórico do upstream (`quote-service/`, `dataset/` intocados); renomear o remote original para `upstream` e apontar `origin` para o repo novo. Créditos ao upstream no README.
- [ ] T0.4 `CLAUDE.md` com as regras do projeto (já rascunhado na raiz).
- [ ] T0.5 Sessões do Claude Code já ficam em `~/.claude/projects/<slug>/*.jsonl` — exportar no fim.

## Dia 1 — Entender e caminho feliz

- [ ] T1.1 `docker compose up --build`; `GET /health`; salvar `GET /planos` em `agent/src/autoseguro_agent/domain/plans_snapshot.json`.
- [ ] T1.2 `scripts/characterize_quote.py`: 200 chamadas → taxa de 5xx, de lentidão, p50/p95. Número vai para o README. *(evidência SMART M-01)*
- [ ] T1.3 `analysis/dataset_report.py` (polars): desfechos, objeções frequentes, PII por conversa, carros > 20 anos. Só agregados, nada cru.
- [ ] T1.4 Scaffold `agent/` com uv, ruff, mypy, pytest, Makefile.
- [ ] T1.5 `domain/models.py` + `rules.py` + `eligibility.py` — testes de fronteira, incluindo data default = 1º do mês seguinte com `Clock` fixo (25/11/2026 → 01/12/2026; 31/12 → 01/01 do ano seguinte). **REQ-01, 10, 11**
- [ ] T1.5b `domain/recommendation.py` — `recommend_plan` com teste por faixa de idade do veículo. **REQ-06**
- [ ] T1.6 Teste de contrato com o exemplo do README (209,90 / 115,11). **REQ-13**
- [ ] T1.7 `pii.py` + Vault — testes por formato e colisão CPF×telefone. **REQ-50, 51**
- [ ] T1.8 `ports.py`, `FakeLLM`, `templates.py`, `OutputValidator`. **REQ-13**
- [ ] T1.9 Grafo mínimo: ingest → mask → extract → route → ask/quote(sem retry) → present → validate_out. **REQ-01, 02**
- [ ] T1.10 CLI de chat ponta a ponta com o LLM real. Commit + push.

## Dia 2 — Falhas, handoff e rastreio (onde está a nota)

- [ ] T2.1 `CircuitBreaker` com `Clock` fake — testes de transição. **REQ-24**
- [ ] T2.2 `HttpQuoteGateway`: timeout, retry+jitter, orçamento, mapeamento 200/422×2/400/5xx/lento — 1 teste respx por linha. **REQ-20..27**
- [ ] T2.3 Mensagem de espera (> 4 s) e de falha honesta, por template. **REQ-23, 25**
- [ ] T2.4 `decide_handoff` + tabela + 1 teste por regra + teste de prioridade; nó `handoff` com resumo. **REQ-30..32**
- [ ] T2.5 `SqliteEventStore` append-only (triggers) + structlog com ids; `GET /conversations/{id}`. **REQ-40..42**
- [ ] T2.6 Teste de caos (FAILURE 0.6, SLOW 0.2, SEED fixo, 50 conversas). **REQ-22, 25** *(SMART M-02..04)*
- [ ] T2.7 Webhook FastAPI + dedup por `wa_message_id`. **REQ-43, 60** Commit + push.

## Dia 3 — Evidências, avaliação e README

- [ ] T3.1 Golden set (10–15 cenários, ver lista abaixo) com FakeLLM; tabela passou/falhou no README. *(SMART M-05)*
- [ ] T3.2 `make demo` com `QUOTE_SEED` que garanta ≥ 1 falha + retry visível → `docs/demo-conversation.md`. **REQ-62**
- [ ] T3.3 README (esqueleto do plano) + `docs/DECISIONS.md` (ADRs curtos).
- [ ] T3.4 `scripts/sanitize_ai_logs.py` + exportar sessões → `ai-logs/` + `ai-logs/README.md`. **REQ-53**
- [ ] T3.5 Clone limpo → seguir só o README → `docker compose up` + `make demo`.
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
| G07 | Manda áudio | pede texto; repetiu → `media_unsupported` |
| G08 | Pede desconto após cotação | `price_negotiation` |
| G09 | Manda CPF sem pedir | mascarado, aviso de minimização, segue |
| G10 | API fora do ar (FAILURE=1.0) | mensagem honesta + `infra_unavailable`, zero R$ |
| G11 | API lenta 1× e depois ok | espera + retry + cotação |
| G12 | CEP inválido 2× | `stuck` |
| G13 | Sinistro / cancelamento | `out_of_scope` |
| G14 | Uso para Uber | `out_of_scope` (`commercial_use`) |
| G15 | Cotou e quer fechar | `ready_to_close` com resumo |
| G16 | "Não sei qual plano" (carro 2012) | 1 cotação do `essencial` recomendado + oferta de completo/premium sem R$ |
