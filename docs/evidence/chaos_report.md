# Teste de caos do `/quote` (T2.6 · SMART M-02, M-03, M-04, M-07, M-08)

Medido em 2026-11-25 com `python -m autoseguro_agent.evaluation.chaos` contra o
quote-service **real** em Docker. Cada conversa manda o perfil completo numa mensagem
e passa pelo agente inteiro (grafo, gateway, validador, handoff). LLM = FakeLLM: o que
se mede aqui é a resiliência, não a extração.

## Caos: 60% de falha, 20% de lentidão de 8 s, `QUOTE_SEED=42`, 50 conversas, 10 em paralelo

| Medida | v1: breaker por **tentativa** | v2: breaker por **pedido** (atual) |
|---|---|---|
| Travas (turno > 15 s) | 0 | **0** |
| Mensagens com R$ sem cotação válida | 0 | **0** |
| Falha esgotada sem handoff | 0 | **0** |
| Cotações com sucesso | 5 de 50 (**10%**) | 26 de 50 (**52%**) |
| Handoff por breaker aberto | 42 | 0 |
| Tentativas: ok / 5xx / timeout | 5 / 16 / 9 | 26 / 66 / 23 |
| Latência por pedido p50 / p95 / máx | 0 / 3.021 / 3.032 ms | 128 / 6.050 / 6.054 ms |
| Tempo do turno inteiro, máx | 4,9 s | 8,1 s |
| Mensagens de espera enviadas | 2 | 17 |

Dados brutos: [`chaos_report_v1_breaker_por_tentativa.json`](chaos_report_v1_breaker_por_tentativa.json)
e [`chaos_report.json`](chaos_report.json).

### O que a v1 ensinou

Os três critérios do desafio passaram já na v1, mas o número de sucesso mostrou um
problema: o breaker contava cada **tentativa** que falhava. Com 80% de chamadas ruins e
10 conversas em paralelo, 5 falhas seguidas aparecem em segundos, o circuito abriu e
mandou 84% dos leads para humano com a API apenas instável, não fora do ar.

Correção: o breaker passou a contar **pedidos** que falharam depois de todos os retries.
Uma falha que o retry resolve não é sinal de legado fora. Resultado: 52% de sucesso,
próximo do teórico com 3 tentativas e 80% de chamadas ruins (1 − 0,8³ ≈ 48,8%). O
breaker continua abrindo quando o legado está de fato fora (testes unitários
`test_breaker_opens_after_failed_requests_and_skips_http` e cenário G10).

Trade-off assumido: com o legado fora, o breaker por pedido demora mais para abrir
(5 pedidos × até ~10 s cada) do que por tentativa. Em produção eu mediria a janela por
taxa de falha num intervalo de tempo, não por contagem consecutiva.

## Configuração padrão: 20% de falha, 10% de lentidão, 100 conversas

| Medida | Valor |
|---|---|
| Travas / R$ sem cotação / falha sem handoff | **0 / 0 / 0** |
| Cotações com sucesso | **97 de 100 (97%)** — previsto 97,7% na caracterização (M-01) |
| Latência por pedido p50 / p95 / máx | 46 / 3.054 / 6.049 ms |
| Tempo do turno, máx | 8,0 s (orçamento de 12 s respeitado) |
| Mensagens de espera | 4 |

Dados brutos: [`default_config_report.json`](default_config_report.json).
