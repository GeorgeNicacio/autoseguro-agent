# Arquitetura e boas práticas — Agente AutoSeguro

> Documento de referência para quem pega o código. Resume **como o sistema é montado** e
> **quais práticas seguimos**, com o porquê de cada uma. Detalhes em:
> [SDD](sdd/) · [SOLID](agent-design/SOLID.md) · [SPARK](agent-design/SPARK.md) ·
> [SMART](agent-design/SMART.md) · [RACI](agent-design/RACI.md).

## 1. Tese

> Um agente pequeno, determinístico onde importa e auditável de ponta a ponta:
> **o LLM conversa e extrai dados; o código decide fluxo, preço e handoff.**

Consequências diretas:
1. Preço só sai da resposta 200 do `/quote`, via template, conferido por validador.
2. Falha do `/quote` vira mensagem honesta + handoff, nunca preço inventado.
3. Handoff é uma tabela de regras em código, uma regra = um teste.
4. Todo evento tem id e status, num log append-only.

## 2. Arquitetura

### 2.1 Estilo: hexagonal pequeno (ports & adapters)

```
            ┌───────────────────────── adapters (entrada) ─────────────────────────┐
            │  api.py  POST /webhook/whatsapp · GET /conversations/{id}   cli.py   │
            └───────────────────────────────┬──────────────────────────────────────┘
                                            ▼
            ┌──────────────────────── aplicação: graph/ (LangGraph) ───────────────┐
            │ ingest → mask → extract(LLM) → route → ask | answer | quote | handoff │
            │                                    → present → validate_out          │
            └───────────────┬───────────────────────────────────────┬──────────────┘
                            ▼                                       ▼
            ┌────────── domain/ (puro) ─────────┐     ┌──────────── ports.py ─────────────┐
            │ models · rules · eligibility      │     │ LLMClient · QuoteGateway · Vault  │
            │ handoff · output_validator        │     │ EventStore · OutboundChannel·Clock│
            └───────────────────────────────────┘     └───────────────┬───────────────────┘
                                                                      ▼
            ┌───────────────────────── adapters (saída) ───────────────────────────┐
            │ quote_http (httpx+tenacity+breaker) · llm_anthropic · llm_fake        │
            │ sqlite_events · outbound (cli/outbox) · pii (masker+vault)            │
            └───────────────────────────────────────────────────────────────────────┘
```

**Regra de dependência:** setas só apontam para dentro. `domain/` não importa LangGraph,
httpx, SQLite nem SDK de LLM (checado por teste).

### 2.2 Stack e porquê

| Camada | Escolha | Porquê |
|---|---|---|
| Linguagem | Python 3.12, `uv` + lockfile, `ruff`, `mypy --strict` | O quote-service já usa uv; um comando para rodar |
| Orquestração | LangGraph, estado tipado, 1 nó de LLM, checkpoint | Código decide o fluxo; modelo decide só dentro do passo |
| LLM | Claude Opus 5.5 via SDK `anthropic` (`messages.parse` + Pydantic, `effort: low`) atrás do `LLMClient` Protocol + `FakeLLM` | Troca de provedor sem tocar no grafo; testes offline |
| Contratos | Pydantic v2 | Validação sintática e semântica antes de chamar a API |
| HTTP | httpx async + tenacity + circuit breaker próprio | Timeout resolve a lentidão de 8 s; breaker protege o legado |
| Canal | FastAPI webhook formato WhatsApp + CLI | Simula canal real sem depender de Meta/Twilio |
| Persistência | SQLite: `SqliteSaver` + `events` append-only | Zero setup; inspecionável com um comando |
| Observabilidade | structlog JSON com ids; LangSmith opcional | Rastreabilidade pedida na avaliação |
| Testes | pytest, respx, caos com `QUOTE_SEED` | Prova o diferencial, não só o caminho feliz |
| Entrega | docker compose + Makefile | Avaliador roda em um comando |

### 2.3 Fora, de propósito ("faria")

RAG, Redis, fila, Postgres, front-end, multiagente, canal real, retry assíncrono agendado,
Presidio, LLM-as-judge. **Por quê:** nada que não se pague em 3 dias; um grafo com um nó de LLM
e regras em código é mais defensável que cinco agentes.

**Em produção com 10 mil leads/dia:** webhook sem estado, fila para mensagens e para retry
assíncrono da cotação, Postgres, Presidio com reconhecedores BR, métricas de conversão por
regra de handoff.

## 3. Boas práticas

### 3.1 Agente / LLM
1. **LLM nunca escreve números.** Mensagens com valores vêm de `templates.py`.
2. **Uma responsabilidade por nó; um nó de LLM.** Dividir só quando prompt ou tools crescerem.
3. **Saída estruturada (schema Pydantic), `effort: low`, confiança por slot.** Sem `temperature`: os modelos Claude atuais não aceitam; o determinismo vem do schema + validação em código. Baixa confiança → pergunta de novo.
4. **Prompt versionado** (`prompts/extract_vN.md`, formato SPARK). Mudou → golden set verde.
5. **O prompt nunca é a única defesa:** toda regra do prompt tem trava em código (SPARK §R).
6. **Minimização:** pedir só o necessário para cotar.

### 3.2 Integração com legado
1. **Validar localmente antes de chamar** (a falha é sorteada antes da validação na API).
2. **Timeout por tentativa (3 s)** e **orçamento total (12 s)**.
3. **Retry só no que é transitório** (5xx, timeout), backoff exponencial com jitter. Nunca em 400/422.
4. **Circuit breaker** (5 falhas → aberto 30 s → half-open).
5. **Idempotência explícita:** `quote_request_id` por pedido, `quote_attempt_id` por tentativa.
6. **Silêncio parece abandono:** mensagem de espera após 4 s.
7. **Regras de `/planos` na subida, snapshot versionado como fallback.**

### 3.3 Dados sensíveis (LGPD)
1. Mascarar **na entrada**, antes de LLM, log e checkpoint.
2. Valor real só no Vault; resolvido na chamada da API (CEP) ou no resumo do handoff.
3. Log com CEP truncado (`01310-***`); processor do structlog remascara tudo (defesa em profundidade).
4. Parquet bruto fora do git; few-shot e golden set gerados já mascarados.
5. `scripts/sanitize_ai_logs.py` + grep de segredos antes de commitar `ai-logs/`.

### 3.4 Rastreabilidade
1. Ids em toda mensagem, pedido, tentativa e handoff; status de máquina de estados finita.
2. `events` append-only garantido por trigger, não por convenção.
3. `GET /conversations/{id}` reconstrói a linha do tempo.
4. Dedup por `wa_message_id` (webhooks reentregam).

### 3.5 Código
1. **SOLID** pragmático (ver doc); composition root único em `graph/build.py`.
2. **Funções puras no domínio** (`decide_handoff`, `check_eligibility`, `validate_output`).
3. **Relógio injetado** (`Clock`); nada de `date.today()` no domínio.
4. **Configuração por ambiente** (pydantic-settings); `.env.example` versionado, `.env` nunca.
5. Tipos estritos, `ruff` + `mypy` no `make lint`.

### 3.6 Testes (pirâmide)
| Nível | O que prova |
|---|---|
| Unit | regras puras, PII, templates, validador, breaker |
| Contrato | exemplo do README contra a API real: R$ 209,90 / R$ 115,11 |
| Gateway (respx) | uma linha por resposta possível da API |
| Caos | 50 conversas com 60% falha + 20% lentidão: 0 travas, 0 R$ sem cotação, 100% handoff nas falhas esgotadas |
| Cenários (golden set) | 15 conversas roteirizadas, inspiradas no dataset |

TDD: teste antes do código; `make test` verde antes de cada commit.

### 3.7 Processo e uso de IA
1. **SDD primeiro:** requisito com ID → design → tarefa → teste → código.
2. `CLAUDE.md` com as regras do projeto desde o primeiro minuto.
3. Planejar antes de pedir código; pedir testes junto; revisar e recusar sugestões ruins — e registrar isso em `ai-logs/README.md` (2–3 erros da IA e como foram pegos).
4. Commits pequenos, mensagens no imperativo, um commit por tarefa do `03-tasks.md`.
5. **ADRs curtos** em `docs/DECISIONS.md`: contexto, decisão, alternativa descartada, trade-off.

## 4. Como rodar (alvo)

```bash
docker compose up --build -d     # quote-service + agente
make demo                        # conversa completa com cotação e uma falha com retry
make test                        # unit + contrato + cenários
make chaos                       # teste de caos com QUOTE_SEED
```
