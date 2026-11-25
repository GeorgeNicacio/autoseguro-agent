# SDD 04 — Cache, filas e dashboard (fase 4)

> Fase pedida depois da entrega base: reduzir custo e latência com cache em Redis,
> processar mensagens por fila (RQ) e dar visibilidade com um dashboard de conversas,
> métricas, custos, latência e trace. Mesmo fluxo: requisito → design → tarefa → teste.

## 1. Por que Redis + RQ (e não algo mais robusto)

O desafio é um teste de escopo fechado. Redis já resolve cache **e** fila com um único
container, zero configuração e bibliotecas maduras; RQ é uma fila simples em cima dele.
Em produção, com volume real, a escolha seria outra (§6). Essa decisão vai explícita no
README e no ADR-015.

## 2. Requisitos

### Cache

| ID | Requisito | Aceite |
|---|---|---|
| REQ-70 | Cache de **cotação**: a chave usa exatamente os campos que o `/quote` usa (plano, idade, ano do veículo, região do CEP pelos 2 primeiros dígitos, como `/planos` define, data de início), a **versão das regras** e a **data do dia** (a API calcula a idade do veículo com `date.today()`). | Teste: mesma entrada → 1 chamada HTTP; data, regras ou plano diferentes → nova chamada. |
| REQ-71 | Só resposta **200** entra no cache. Falha, recusa e payload inválido nunca são cacheados. | Teste por status. |
| REQ-72 | Hit de cotação continua rastreável: evento com `cache=hit`, latência e a economia estimada; o preço continua vindo de uma resposta 200 real (a que foi cacheada). | Teste de evento. |
| REQ-73 | Cache das **regras de `/planos`** em Redis com TTL; a versão (hash) entra na chave da cotação. | Teste. |
| REQ-74 | Cache de **extração do LLM**: chave = hash de (versão do prompt, modelo, texto **mascarado** normalizado, dado esperado, data). Nenhum dado pessoal cru na chave ou no valor. | Teste: "35" com dado esperado `idade` em duas conversas → 1 chamada ao LLM. |
| REQ-75 | **Consultas quentes**: contador de hits por chave (sorted set); chave que passa de N hits tem o TTL estendido. Top-N aparece no dashboard (texto mascarado). | Teste de promoção de TTL. |
| REQ-76 | **Prompt caching** da Anthropic no system prompt (bloco fixo com `cache_control`); tokens de cache lidos e gravados entram no custo. | Teste do request montado. |
| REQ-77 | Redis fora do ar **não derruba** o agente: o cache vira no-op e o evento registra `cache=error`. | Teste com Redis indisponível. |

### Custos, latência e trace

| ID | Requisito | Aceite |
|---|---|---|
| REQ-80 | Toda chamada ao LLM gera `llm.call` com modelo, versão do prompt, tokens (entrada, saída, cache lido, cache gravado), custo em US$ pela tabela de preços configurável, latência e se veio do cache. | Teste com cliente simulado. |
| REQ-81 | Cada nó do grafo gera um span `trace.span` (nó, duração, ordem) e o turno gera `turn.finished` com a duração total. | Teste: turno feliz tem spans de ingest → deliver. |
| REQ-82 | `GET /api/metrics`: conversas por status, handoffs por regra, sucesso do `/quote`, tentativas, hit rate de cache (cotação e LLM), tokens, custo total e por conversa, economia estimada do cache, latência p50/p95 (turno, LLM, cotação), profundidade da fila, consultas quentes. | Teste de API. |

### Filas

| ID | Requisito | Aceite |
|---|---|---|
| REQ-90 | O webhook **enfileira** cada mensagem e responde na hora (o WhatsApp reenvia se o 200 demora). Um worker processa; com um worker, as mensagens saem em ordem. | Teste com fila síncrona. |
| REQ-91 | Handoff por `infra_unavailable` agenda **nova tentativa de cotação** (ex.: 1, 5 e 15 min). Se der certo, o lead recebe a cotação e o consultor é avisado por evento. | Teste do job. |
| REQ-92 | Rodar o golden set é um job da fila, disparado pelo dashboard; o resultado fica consultável. | Teste. |

### Dashboard

| ID | Requisito | Aceite |
|---|---|---|
| REQ-95 | `GET /dashboard`: KPIs, custos, latência, cache, fila, handoffs por regra, consultas quentes, lista de conversas e detalhe com transcrição (mascarada), trace e eventos. | Smoke test em Docker. |
| REQ-96 | Chat manual no dashboard (nova conversa, texto, simular mídia), passando pela mesma fila e pelo mesmo agente do webhook. | Teste da API de chat. |
| REQ-97 | Botão para rodar o golden set (FakeLLM ou Claude) e ver a tabela de resultado. | Teste da API. |

## 3. Design

```
WhatsApp/dashboard ──> API (FastAPI) ──enqueue──> Redis (fila "agent") ──> worker RQ (SimpleWorker)
        ^                    │                                              │  Agent + LangGraph
        │                    └── GET métricas/conversas/trace <── SQLite (events, WAL) <──┘
        └──────────── dashboard (HTML estático + fetch) ────────────────────────────────┘
                                         Redis também guarda: cache de cotação, de regras,
                                         de extração e o ranking de consultas quentes
```

- **Um processo roda o agente: o worker.** A API só enfileira e lê. Isso evita dois
  escritores no checkpoint SQLite e mantém o cofre de PII num processo só.
  `SimpleWorker` (sem fork) e um event loop persistente por processo.
- Cache como **decorator nas portas** (SOLID · O/D): `CachedQuoteGateway(inner, cache)` e
  `CachedLLM(inner, cache)`. O grafo não sabe que existe cache.
- `CacheStore` é uma porta pequena (`get`, `set`, `incr_hot`, `top_hot`); adaptadores
  `RedisCache` e `NullCache` (Redis fora → no-op).
- Métricas calculadas a partir dos eventos (fonte única); em produção, séries temporais.

## 4. Riscos e como foram tratados

| Risco | Tratamento |
|---|---|
| Servir preço velho | Chave inclui data do dia e hash das regras; TTL curto; só 200 entra |
| Cachear dado pessoal | Chaves são hashes de texto mascarado; CEP entra só como prefixo de 2 dígitos |
| Agrupar pelo prefixo do CEP pressupõe a regra da API | É a regra publicada em `/planos`; o hash das regras entra na chave, então mudou a regra, muda a chave |
| Cache de LLM devolver interpretação errada para outro contexto | Chave inclui o dado esperado e a data; dados já coletados ficam fora de propósito (mais hits) — trade-off registrado |
| Fila parada | Webhook responde e registra; dashboard mostra profundidade da fila |

## 5. Tarefas

- [x] T4.1 Redis e worker no compose; dependências (`redis`, `rq`, `fakeredis`).
- [x] T4.2 `CacheStore` + `RedisCache`/`NullCache`; `CachedQuoteGateway`; cache de regras. **REQ-70..73, 77**
- [x] T4.3 `CachedLLM`, consultas quentes, prompt caching, tabela de preços e `llm.call`. **REQ-74..76, 80**
- [x] T4.4 Spans por nó e `turn.finished`. **REQ-81**
- [x] T4.5 Fila: jobs de mensagem, retry pós-handoff e golden; webhook assíncrono. **REQ-90..92**
- [x] T4.6 API de métricas, conversas e chat; página do dashboard. **REQ-82, 95..97**
- [x] T4.7 README e ADR-015; validação em Docker.

## 6. Em produção (fica no README como "faria")

- Fila: **SQS/Kafka/Pub-Sub** com partição por conversa, DLQ e reprocessamento; ou
  **Temporal** para o fluxo de retry da cotação.
- Cache: **Redis gerenciado** (ElastiCache/Memorystore) em cluster, com métricas de evicção.
- Observabilidade: **OpenTelemetry** + Langfuse/LangSmith para traces de LLM, Prometheus/Grafana.
- **Modo sombra**: nova versão do prompt/modelo roda em paralelo nas conversas reais, sem
  responder ao lead; compara extrações e decisões de handoff com a versão em produção antes
  de promover.
