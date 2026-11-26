# Métricas SMART do agente AutoSeguro

> Cada métrica é **S**pecífica, **M**ensurável, **A**tingível, **R**elevante (ligada a um
> critério de avaliação do desafio) e **T**emporal (quando e como é medida).
> Os valores medidos substituem a coluna "Resultado" no README — "fiz" com número.

## 1. Métricas de engenharia (medidas no repositório)

| ID | Métrica (S) | Como medir (M) | Meta (A) | Por que importa (R) | Quando (T) | Resultado |
|---|---|---|---|---|---|---|
| M-01 | Taxa real de falha e lentidão do `/quote` | `scripts/characterize_quote.py`, 200 chamadas, config padrão | Só medir (esperado ~20% 5xx, ~10% lentas) | Justifica timeout, retry e breaker com dado, não com chute | Dia 1 | **20,5% 5xx · 8,0% lentas · 71,5% ok na 1ª em < 3 s** (2026-11-25, [evidência](../evidence/quote_characterization.md)) |
| M-02 | Conversas que travam no teste de caos | `tests/chaos`, 50 conversas, FAILURE 0.6 / SLOW 0.2 / SEED fixo; trava = turno > 15 s sem resposta | **0** | Critério "não trava" | Dia 2, todo `make chaos` | **0 de 50** no caos; 0 de 100 no padrão ([evidência](../evidence/chaos_report.md)) |
| M-03 | Mensagens com R$ sem cotação `success` | `OutputValidator` + varredura do outbox no caos e no golden set | **0** | Critério "nunca inventa preço" | Dia 2, todo `make test` | **0** no caos e no padrão ([evidência](../evidence/chaos_report.md)) |
| M-04 | Falhas esgotadas que viram handoff | eventos `quote_request.failed` com `handoff.opened` correspondente / total | **100%** | Lead nunca fica sem resposta | Dia 2 | **100%** (24 de 24 no caos) ([evidência](../evidence/chaos_report.md)) |
| M-05 | Golden set aprovado | `tests/scenarios`, 15 cenários (ampliado para 24, até o aceite final) | **100%** | Critério de handoff explícito e defensável | Dia 3, a cada mudança de prompt ou modelo | **24/24** com FakeLLM; Claude: **60/60** em 3 rodadas com 20 cenários (Opus, prompt v2) e **24/24** com Opus, Sonnet e Haiku 5.5 (prompt v3; Haiku 3 rodadas seguidas) ([evidência](../evidence/golden_claude.md), [comparativo](../evidence/model_comparison.md)) |
| M-06 | Cobertura de regras de handoff por teste | `rule_id`s com teste / total em `HANDOFF_RULES` | **100%** (10/10) | Cada regra defensável tem prova | Dia 2 | **10/10**, com teste que quebra se surgir regra sem teste |
| M-07 | Latência por pedido de cotação | p50 / p95 / máx de `quote_request` no caos | p95 ≤ 8 s, máx ≤ 12,5 s | Orçamento de 12 s respeitado | Dia 2 | p95 6,05 s · máx 6,05 s no caos; máx 6,05 s no padrão ([evidência](../evidence/chaos_report.md)) |
| M-08 | Taxa de sucesso de cotação com resiliência | `success / (success + failed)` com FAILURE 0.2 / SLOW 0.1 | ≥ 97% (3 tentativas com 30% de falha ≈ 1 − 0,3³) | Mostra que o retry paga | Dia 2 | **97%** (97/100); 52% sob caos de 80% ruins ([evidência](../evidence/chaos_report.md)) |
| M-09 | Vazamento de PII em log e checkpoint | regex de CPF/e-mail/telefone/placa sobre `events`, logs JSON e SQLite do checkpoint após o golden set | **0 ocorrências** | Critério de dados sensíveis | Dia 3 | _a medir_ |
| M-10 | Recall do mascarador no dataset | PII encontrada pelo `pii.py` vs contagem por regex de referência nas ~2.500 conversas | ≥ 99% em CPF e e-mail; ≥ 95% em telefone e placa | Testa o mascarador contra formatos "reais" | Dia 1 | **100% nos 5 tipos, 0 mensagens com PII crua, 2500/2500 idades preservadas** (2026-11-25, [evidência](../evidence/pii_recall.md)) |
| M-11 | Rastreabilidade completa | eventos com `conversation_id` e `status` válidos / total; tentativas com `quote_request_id` pai | **100%** | Critério de rastreabilidade | Dia 2 | **100%** nos testes de cenário e de API (todo evento com `conversation_id` e status; tentativas com `quote_request_id`) |
| M-12 | Chamadas desperdiçadas em payload que seria recusado | tentativas com 422 `cotacao_recusada` evitáveis por validação local | **0** | Validação local antes de gastar retry | Dia 2 | **0** chamadas nos cenários de recusa (teste `test_policy_refusal_never_calls_api`) |
| M-13 | Setup do avaliador | tempo de clone limpo até `make demo` rodando | ≤ 2 comandos, ≤ 5 min | "Roda em um comando" | Dia 3 | _a medir_ |

## 2. Métricas de produto (o que eu acompanharia em produção — "faria")

| ID | Métrica | Meta inicial | Fonte |
|---|---|---|---|
| P-01 | Tempo até a primeira resposta do agente | p95 < 5 s | `message.received` → `message.sent` |
| P-02 | Taxa de conversas que chegam à cotação | baseline do dataset (desfecho `ganho` + `em_negociacao`) + 10 p.p. | eventos `quote_request.success` / conversas |
| P-03 | Taxa de handoff por regra | acompanhar tendência; `stuck` < 10% | `handoff.opened.rule_id` |
| P-04 | Conversão pós-handoff `ready_to_close` | ≥ baseline humano do dataset | CRM (fora do escopo) |
| P-05 | Abandono após mensagem de espera | < abandono atual sem espera | análise do dataset (tempo de 1ª resposta × `sem_resposta`) |

Pergunta para levar à conversa de feedback: **qual métrica de negócio eles usariam para
dizer que o agente deu certo?** (P-02 ou P-04 são os candidatos naturais.)
