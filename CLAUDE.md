# CLAUDE.md — regras do projeto (Agente AutoSeguro)

## Fluxo
- **SDD primeiro.** Nada de código sem requisito em `docs/sdd/01-requirements.md` (REQ-xx) e tarefa em `docs/sdd/03-tasks.md`.
- **TDD.** Teste antes da implementação; `make test` verde antes de cada commit.
- Um commit por tarefa; mensagem cita a tarefa (ex.: `feat(gateway): retry com jitter [T2.2]`).

## Regras inegociáveis
1. **O LLM nunca escreve números.** Valores só por `templates.py` com dados da resposta 200 do `/quote`; `OutputValidator` confere todo R$.
2. **O código decide** fluxo, preço e handoff. O LLM só extrai slots e sinaliza intenções.
3. **PII mascarada antes** do LLM, do log e do checkpoint. Nunca logar mensagem crua nem CEP completo.
4. `quote-service/` e `dataset/` são **intocados**. O agente mora em `agent/`.
5. `domain/` não importa LangGraph, httpx, SQLite nem SDK de LLM.
6. Retry só para 5xx e timeout. Nunca para 400/422.
7. `events` é append-only.
8. Nada de `date.today()` no domínio: use a porta `Clock`.
9. Nunca commitar `.env`, chaves, parquet bruto, nem dados pessoais do autor.

## Stack
LLM: Claude `claude-opus-5-5` via SDK `anthropic` (`messages.parse`, `effort: low`, **sem** `temperature`).
Python 3.12 · uv · ruff · mypy --strict · FastAPI · LangGraph · Pydantic v2 · httpx · tenacity · structlog · SQLite · pytest · respx · polars.

## Comandos
`make test` · `make chaos` · `make demo` · `make lint` · `make chat`

## Documentos
- SDD: `docs/sdd/` (requisitos, design, tarefas)
- Arquitetura e práticas: `docs/ARCHITECTURE_AND_PRACTICES.md`
- SOLID / SPARK / SMART / RACI: `docs/agent-design/`
