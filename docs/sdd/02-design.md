# SDD 02 — Design

> Como os requisitos de `01-requirements.md` viram código. Cada seção cita os `REQ-xx` que atende.
> Princípios de código em `../agent-design/SOLID.md`; prompts em `../agent-design/SPARK.md`;
> métricas em `../agent-design/SMART.md`; responsabilidades em `../agent-design/RACI.md`.

## 1. Visão geral

```
WhatsApp webhook ─┐                                              ┌─> OutboundChannel (CLI print | outbox SQLite)
CLI de chat ──────┴─> handle_inbound() ─> LangGraph (1 nó LLM) ──┤
                                         │                        └─> EventStore (events append-only) + structlog
                                         ├─> PiiMasker + Vault
                                         ├─> LLMClient (extração estruturada)
                                         ├─> Eligibility (regras de /planos)
                                         ├─> decide_handoff (tabela pura)
                                         ├─> QuoteGateway (httpx + timeout + retry + breaker)
                                         └─> OutputValidator (R$ só de cotação success)
```

Hexagonal pequeno: `domain/` não conhece LangGraph, httpx, SQLite nem o SDK do LLM.
Os adaptadores implementam `Protocol`s de `ports.py`. (NFR-2)

## 2. Estrutura do código

```
agent/
├── pyproject.toml                    # uv, ruff, mypy, pytest
├── src/autoseguro_agent/
│   ├── domain/
│   │   ├── models.py                 # LeadProfile, QuoteRequest, QuoteResult, QuoteOutcome, HandoffDecision, Intent
│   │   ├── rules.py                  # PlanRules (parse de /planos) + snapshot fallback
│   │   ├── eligibility.py            # check(profile, rules, today) -> EligibilityResult
│   │   ├── handoff.py                # HANDOFF_RULES + decide_handoff(state)
│   │   ├── recommendation.py         # recommend_plan(profile, rules, today) — REQ-06
│   │   └── output_validator.py       # valida R$ contra última cotação success
│   ├── ports.py                      # LLMClient, QuoteGateway, EventStore, OutboundChannel, Clock, Vault
│   ├── adapters/
│   │   ├── quote_http.py             # HttpQuoteGateway
│   │   ├── circuit_breaker.py        # CircuitBreaker(clock)
│   │   ├── llm_anthropic.py          # Claude via SDK anthropic: messages.parse(output_format=ExtractionResult)
│   │   ├── llm_fake.py               # FakeLLM roteirizado p/ testes e golden set
│   │   ├── sqlite_events.py          # SqliteEventStore (INSERT only)
│   │   └── outbound.py               # CliOutbound, OutboxOutbound
│   ├── pii.py                        # PiiMasker + InMemoryVault
│   ├── graph/{state.py,nodes.py,build.py}
│   ├── prompts/extract_v2.md         # prompt versionado no formato SPARK (v1 no histórico)
│   ├── templates.py                  # TODAS as mensagens com números ou de falha
│   ├── settings.py                   # pydantic-settings (timeouts, URLs, limites)
│   ├── api.py                        # FastAPI: /webhook/whatsapp, /conversations/{id}, /health
│   └── cli.py
└── tests/{unit,contract,chaos,scenarios}/
```

## 3. Estado do grafo (`graph/state.py`)

```python
class ConversationState(TypedDict):
    conversation_id: str
    status: Literal["active", "quoted", "handed_off", "closed"]
    profile: LeadProfile              # slots já validados (CEP como token <CEP_1>)
    pending_slot: SlotName | None
    slot_failures: dict[SlotName, int]   # REQ-12
    low_confidence_streak: int
    intents: set[Intent]              # sinalizados pelo LLM no turno atual
    last_quote: QuoteOutcome | None   # success | refused | failed (+ ids)
    quotes: list[QuoteOutcome]
    handoff: HandoffDecision | None
    last_inbound_masked: str
    outbox: list[OutboundMessage]
```

Checkpoint: `SqliteSaver` por `conversation_id` (thread_id). O estado só contém texto **mascarado**. (REQ-50)

## 4. Grafo

| Nó | Tipo | Faz | Próximo |
|---|---|---|---|
| `ingest` | código | registra `message.received`, dedup `wa_message_id`, mídia → intent `media` | `mask` |
| `mask` | código | PiiMasker; tokens no Vault; flag `unsolicited_pii` | `extract` |
| `extract` | **LLM** | `ExtractionResult` Pydantic: slots, intents, plano pedido, confiança | `route` |
| `route` | código | aplica slots via `eligibility`; chama `decide_handoff` | `handoff` \| `ask` \| `quote` \| `answer` |
| `ask` | código+LLM opcional | próxima pergunta por template (sem números) | `validate_out` |
| `answer` | código | dúvida de plano respondida a partir de `PlanRules` via template | `validate_out` |
| `quote` | código | `QuoteGateway.quote()`; espera > 4 s envia template de espera | `route_quote` |
| `route_quote` | código | success → `present`; refused/failed → `decide_handoff` | `present` \| `handoff` \| `ask` |
| `present` | código | `templates.quote_message(result)` | `validate_out` |
| `handoff` | código | monta `HandoffSummary`, evento `handoff.opened`, template de aviso | `validate_out` |
| `validate_out` | código | `OutputValidator`; reprovado → troca por template seguro + evento `output.blocked` | `END` |

**Por que só um nó de LLM:** o único problema que precisa de linguagem natural é entender o
lead. Preço, fluxo e handoff são regras — código testável.

## 5. Handoff (`domain/handoff.py`) — REQ-30

Tabela avaliada em ordem de prioridade; a primeira que dispara vence. Cada linha = uma
função predicado + um teste.

| # | rule_id | Gatilho (estado) | Prioridade | Motivo |
|---|---|---|---|---|
| 1 | `explicit_request` | intent `wants_human` | imediata | Respeitar o cliente; insistir custa a venda |
| 2 | `infra_unavailable` | `last_quote.status == failed` (retries esgotados) ou breaker aberto | imediata | Não inventar preço nem deixar o lead sem resposta |
| 3 | `risk_or_conflict` | intent `complaint` / `legal_threat` / `strong_anger` | alta | Situação sensível pede pessoa |
| 4 | `out_of_policy` | eligibility reprovada por idade>75 / veículo>20 anos, ou 422 `cotacao_recusada` não-plano | alta | Exceção comercial é decisão humana |
| 5 | `out_of_scope` | intent `claim`, `cancel`, `endorsement`, `second_copy`, `fleet`, `commercial_use` | alta | O agente só vende seguro individual novo |
| 6 | `agent_bug` | 422 de schema do FastAPI | alta | Erro nosso; humano assume e o log vira bug |
| 7 | `price_negotiation` | intent `discount` / `competitor_match` / `special_installments` | média | Agente sem alçada de desconto |
| 8 | `stuck` | `slot_failures[x] >= 2` ou `low_confidence_streak >= 2` | média | Evita loop e frustração |
| 9 | `media_unsupported` | lead responde com mídia **2×** ao mesmo slot pendente | média | O agente não lê mídia; 56,8% das conversas têm mídia (CNH, foto), por isso a 1ª mídia só gera aviso (dataset D2) |
| 10 | `ready_to_close` | `status == quoted` e intent `wants_to_buy` | fim feliz | Contratação pede CPF/documentos/pagamento |

Decisão de projeto (baseada no dataset, D2): a 1ª mídia gera só o template "não preciso
desse arquivo agora; me diz por texto …" e o fluxo segue. Só a 2ª mídia no mesmo slot
pendente abre handoff.

## 6. Rastreabilidade — REQ-40..43

| Entidade | Id | Status |
|---|---|---|
| Conversa | `conversation_id` (uuid7) | `active`, `quoted`, `handed_off`, `closed` |
| Mensagem | `message_id` (+ `wa_message_id`) | `received`, `processed`, `sent`, `failed` |
| Pedido de cotação | `quote_request_id` | `pending`, `success`, `refused`, `failed` |
| Tentativa | `quote_attempt_id` (filha) | `ok`, `timeout`, `http_5xx`, `refused`, `invalid`, `circuit_open` + `latency_ms` |
| Handoff | `handoff_id` | `opened` + `rule_id` + `priority` |

```sql
CREATE TABLE events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, event_type TEXT NOT NULL,
  conversation_id TEXT NOT NULL, message_id TEXT, quote_request_id TEXT,
  quote_attempt_id TEXT, handoff_id TEXT, status TEXT NOT NULL,
  latency_ms INTEGER, payload_json TEXT NOT NULL   -- sempre mascarado
);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE UNIQUE INDEX ux_wa_msg ON events(json_extract(payload_json,'$.wa_message_id')) WHERE event_type='message.received';
```

## 7. Gateway resiliente — REQ-20..27

```
quote(req) ──> breaker.allow()? ──não──> QuoteOutcome.failed(circuit_open)
                 │sim
                 ▼
     for attempt in 1..3 (orçamento 12 s):
        POST /quote timeout=3 s
        200 ─────────────> success (breaker.record_success)
        422 cotacao_recusada > refused(motivo)       [sem retry]
        422 {"detail":…} ──> invalid(agent_bug)      [sem retry]
        400 payload_invalido > invalid(bad_input)    [sem retry]
        5xx / timeout ─────> breaker.record_failure; sleep(backoff+jitter) se houver orçamento
     esgotou ──> failed(exhausted)
```

- `tenacity` para o laço de retry (`retry_if_exception_type(Retryable)`, `wait_exponential_jitter(initial=0.5, max=2)`, `stop_after_attempt(3) | stop_after_delay(12)`).
- `CircuitBreaker` próprio (~40 linhas): `closed → open` após 5 **pedidos** falhos seguidos (depois de todos os retries); `open` por 30 s; `half_open` deixa 1 pedido passar. Usa `Clock` para teste. Contar por tentativa foi a v1 e abria o circuito com a API só instável (ver `docs/evidence/chaos_report.md`).
- Mensagem de espera: a cotação roda numa task; `asyncio.wait(timeout=4)` e, se não terminou, envia o template de espera e continua aguardando.
- Timeout por tentativa com `asyncio.timeout` (teto da tentativa inteira) além do timeout do httpx (que vale por operação de rede).
- `quote_request_id` por pedido, `quote_attempt_id` por tentativa, enviados também como header `X-Request-Id` (a API ignora, mas mostra a ideia de idempotência).

## 8. Garantia contra preço inventado — REQ-13

1. O LLM **não gera mensagens com números**; `ExtractionResult` não tem campo de texto livre para o lead com valores.
2. Mensagens com valores só saem de `templates.py`, preenchidas por `QuoteResult`.
3. `OutputValidator`: extrai todo `R$ x` da mensagem final; cada valor deve existir em `last_quote` com status `success` (prêmio, franquia, pro-rata). Sem cotação success → zero `R$` permitido. Falhou → template seguro + evento `output.blocked`.

## 9. PII — REQ-50..53

- Regex testadas: CPF (com/sem pontuação, 11 dígitos), e-mail, telefone (+55, DDD opcional, 8/9 dígitos), placa antiga `AAA-9999` e Mercosul `AAA9A99`, CEP `99999-999`/`99999999`.
- Ordem de aplicação: CPF antes de telefone (evita colisão de 11 dígitos); testes de colisão.
- Tokens estáveis por conversa (`<CPF_1>` sempre o mesmo valor) guardados no `Vault`.
- O LLM devolve `cep: "<CEP_1>"`; o código resolve no Vault só no momento do `POST /quote`. **O LLM nunca vê o CEP completo.**
- structlog processor final: aplica o masker de novo em todo evento (defesa em profundidade); CEP logado como `01310-***`.

## 10. Configuração

`settings.py` (pydantic-settings, prefixo `AGENT_`): `QUOTE_BASE_URL`, `QUOTE_TIMEOUT_S=3`, `QUOTE_MAX_ATTEMPTS=3`, `QUOTE_BUDGET_S=12`, `WAIT_MESSAGE_AFTER_S=4`, `BREAKER_FAILURES=5`, `BREAKER_OPEN_S=30`, `LLM_PROVIDER=anthropic|fake`, `LLM_MODEL=claude-opus-5-5`, `LLM_EFFORT=low`, `LLM_TIMEOUT_S=10`, `DB_PATH`, `LANGSMITH_*` opcional. `ANTHROPIC_API_KEY` só no `.env` (nunca versionado).

## 12. Adaptador Claude (ADR-001)

**Decisão (2026-11-25):** provedor Anthropic, SDK oficial `anthropic` em Python, modelo `claude-opus-5-5`. **Atualização (2026-11-26):** padrão `claude-haiku-5-5`, escolhido por medição no golden set (ADR-017).

```python
response = client.messages.parse(
    model=settings.llm_model,                 # "claude-haiku-5-5" (padrão)
    max_tokens=2048,
    system=EXTRACT_PROMPT_V1,                 # SPARK, estável → elegível a prompt caching
    messages=[{"role": "user", "content": masked_turn_payload}],
    output_format=ExtractionResult,           # Pydantic → saída validada
    output_config={"effort": "low"},          # extração simples: menos latência e custo
)
if response.stop_reason == "refusal":  -> LLMUnavailable (template seguro; 2× → handoff `stuck`)
result = response.parsed_output
```

- **Sem `temperature`:** nos modelos Claude atuais os parâmetros de amostragem não são aceitos (a API devolve 400). O determinismo que importa vem de outro lugar: saída estruturada com schema, validação em código, `effort: low`, e golden set rodando com `FakeLLM`.
- **Thinking:** no Opus 5.5 não dá para desligar; `effort: low` mantém a extração rápida.
- **Erros do SDK:** cadeia específica → `RateLimitError` / `APIStatusError` 5xx / `APIConnectionError` viram `LLMUnavailable`; o SDK já faz 2 retries; nosso timeout por chamada é 10 s.
- **Prompt caching:** system prompt fixo primeiro, nada volátil (data, ids) nele — o estado vai na mensagem do usuário.
- **Trade-off a medir (M-07/P-01):** se a latência do Opus 5.5 na extração pesar no "tempo até a primeira resposta", testar `claude-haiku-5-5` com o mesmo golden set. Troca é só `LLM_MODEL` — decisão sua, com número na mão.

## 11. Estratégia de testes

| Camada | Pasta | Ferramenta | Prova |
|---|---|---|---|
| Unit | `tests/unit` | pytest | eligibility, handoff (1 teste/regra), pii, templates, validator, breaker |
| Contrato | `tests/contract` | quote-service real (FAILURE_RATE=0) | exemplo do README = R$ 209,90 / R$ 115,11 |
| Gateway | `tests/unit/test_quote_http.py` | respx | cada linha da tabela de respostas |
| Caos | `tests/chaos` | quote-service real, FAILURE 0.6 / SLOW 0.2 / SEED | 50 conversas: nenhuma trava, nenhum R$ sem success, toda falha esgotada → handoff |
| Cenários | `tests/scenarios` | FakeLLM roteirizado + respx | golden set 10–15 conversas |
