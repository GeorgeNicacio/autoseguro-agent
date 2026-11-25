# SOLID aplicado ao agente AutoSeguro

> Cada princípio com: onde aparece no código, o que ganhamos, e o teste que prova.
> Ligação com a história da clínica: Parte 5 (Liskov e inversão de dependência).

## S — Responsabilidade única

| Módulo | Uma razão para mudar |
|---|---|
| `domain/eligibility.py` | Regras de aceitação de `/planos` mudaram |
| `domain/handoff.py` | Política comercial de passar para humano mudou |
| `domain/output_validator.py` | Política de "o que pode sair com R$" mudou |
| `adapters/quote_http.py` | Protocolo/latência do legado mudou |
| `adapters/circuit_breaker.py` | Estratégia de proteção do legado mudou |
| `pii.py` | Formatos de dado sensível mudaram |
| `templates.py` | Texto que vai para o lead mudou |
| `graph/` | Ordem do fluxo mudou |

**Anti-exemplo evitado:** um nó "agente" que pergunta, cota, formata preço e decide handoff
no mesmo prompt. **Prova:** cada módulo tem sua pasta de teste e nenhum teste de `domain/`
importa httpx, LangGraph ou SQLite.

## O — Aberto/fechado

- **Handoff:** nova regra = nova linha em `HANDOFF_RULES` (predicado + metadados). `decide_handoff` não muda.
- **Respostas da API:** mapeamento status → `QuoteOutcome` é uma tabela; novo código de erro = nova linha.
- **Canais:** novo canal (Telegram, WhatsApp real) = novo adaptador de entrada + `OutboundChannel`; o grafo não muda.

**Prova:** teste parametrizado itera sobre `HANDOFF_RULES` e exige um caso por `rule_id`.

## L — Substituição de Liskov

- `FakeLLM` e `AnthropicLLM` (Claude) cumprem o mesmo `LLMClient`: mesma entrada (texto mascarado + estado), mesma saída (`ExtractionResult` validado por Pydantic), mesmas exceções (`LLMUnavailable`).
- `HttpQuoteGateway` e `FakeQuoteGateway` devolvem sempre `QuoteOutcome`; **nunca** levantam `httpx.*` para fora do adaptador.
- `SqliteEventStore` e `InMemoryEventStore` têm o mesmo contrato de append-only.

**Prova:** suíte de contrato de porta (`tests/unit/ports/`) roda a mesma bateria contra o fake e o real.

## I — Segregação de interface

Portas pequenas, cada uma com o mínimo que o consumidor usa:

```python
class LLMClient(Protocol):
    def extract(self, req: ExtractionRequest) -> ExtractionResult: ...

class QuoteGateway(Protocol):
    async def quote(self, req: QuoteRequest, ctx: TraceContext) -> QuoteOutcome: ...
    def rules(self) -> PlanRules: ...

class EventStore(Protocol):
    def append(self, event: Event) -> None: ...
    def timeline(self, conversation_id: str) -> list[Event]: ...

class OutboundChannel(Protocol):
    def send(self, msg: OutboundMessage) -> None: ...

class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...

class Vault(Protocol):
    def put(self, conversation_id: str, kind: PiiKind, value: str) -> str: ...  # devolve token
    def resolve(self, conversation_id: str, token: str) -> str: ...
```

Nada de "`AgentServices`" gordo: o nó `quote` recebe só `QuoteGateway`, `Clock`, `EventStore`.

## D — Inversão de dependência

- O domínio define as portas (`ports.py`); adaptadores dependem delas, não o contrário.
- Composição em um único lugar: `graph/build.py::build_agent(settings) -> Agent` monta as dependências (composition root). Testes chamam `build_agent(...)` com fakes.
- Trocar provedor de LLM = trocar `LLM_PROVIDER` no `.env`; zero linhas no grafo.

**Prova:** `import-linter` (ou teste simples com `ast`) falha se `domain/` importar de `adapters/`, `graph/`, `httpx`, `langgraph` ou do SDK do LLM.

## Onde **não** aplicamos (de propósito)

- Sem fábrica abstrata, sem DI container, sem repositório genérico: 3 dias, um composition root basta.
- `templates.py` é um módulo de funções, não uma hierarquia de classes.
