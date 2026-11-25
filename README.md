# Agente AutoSeguro — desafio FDE Namastex

Agente de WhatsApp que conversa com o lead, qualifica, cota seguro auto pelo `POST /quote`
e decide entre resolver sozinho ou passar para um humano. **O LLM conversa e extrai dados;
o código decide fluxo, preço e handoff.** Quando a API de cotação falha, o agente tenta de
novo com critério, avisa o lead com honestidade e passa para um consultor, sem nunca
inventar preço.

> O enunciado original do desafio está em [`docs/CHALLENGE.md`](docs/CHALLENGE.md).

## Como rodar

Com Docker (só isso é necessário):

```bash
docker compose up --build -d   # quote-service + agente (webhook em http://localhost:8080)
make demo                      # conversa completa com timeout, 5xx e retry visíveis
```

Sem `make`: os comandos de cada alvo estão no [`Makefile`](Makefile). Para conversar no terminal:

```bash
docker compose exec agent python -m autoseguro_agent.cli --fake-llm --events
```

Por padrão o agente sobe com o `FakeLLM` (extrator determinístico, sem chave). Para usar o
Claude: `AGENT_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=... docker compose up -d`.

Para desenvolver (precisa de [uv](https://docs.astral.sh/uv/)):

```bash
make setup     # dependências travadas pelo uv.lock
make test      # unitários + contrato contra a API real + cenários
make golden    # 20 cenários roteirizados contra a API sem falha simulada
make chaos     # 50 conversas contra a API com 60% de falha e 20% de lentidão
make check     # ruff + mypy --strict + testes (o que roda antes de cada commit)
```

Webhook no formato do WhatsApp Cloud API:

```bash
curl -X POST localhost:8080/webhook/whatsapp -H 'content-type: application/json' -d '{
  "entry":[{"changes":[{"value":{"messages":[{"from":"5511900000001","id":"wamid.1",
  "type":"text","text":{"body":"tenho 35 anos, Onix 2022, cep 01310-100, completo"}}]}}]}]}'
curl localhost:8080/conversations/<conversation_id>   # linha do tempo com ids e status
```

## Fluxo

```mermaid
flowchart LR
    A[Mensagem do lead<br/>webhook ou CLI] --> B[Mascarar PII<br/>antes de tudo]
    B --> C[Extrair dados<br/>único nó com LLM]
    C --> D[Aplicar e validar<br/>regras de /planos]
    D --> E{decide_handoff<br/>tabela em código}
    E -- regra disparou --> H[Handoff<br/>resumo + motivo]
    E -- falta dado --> Q[Perguntar<br/>próximo dado]
    E -- dados ok --> R[/quote resiliente<br/>timeout · retry · breaker/]
    R -- 200 --> T[Cotação<br/>template da API]
    R -- esgotou ou recusa --> H
    T --> V[Validador de saída<br/>R$ só de cotação ok]
    Q --> V
    H --> V
    V --> S[Resposta ao lead<br/>com ids e status]
```

Um grafo LangGraph com **um único nó de LLM** (extração com saída estruturada). Regras de
handoff, elegibilidade, chamada ao `/quote` e validação de saída são código determinístico
e testado. Arquitetura hexagonal pequena: o domínio não conhece LangGraph, httpx, SQLite
nem o SDK do LLM (um teste quebra se conhecer). Detalhes em
[`docs/ARCHITECTURE_AND_PRACTICES.md`](docs/ARCHITECTURE_AND_PRACTICES.md).

## Decisões

Cada decisão tem contexto, alternativa e trade-off em [`docs/DECISIONS.md`](docs/DECISIONS.md).
O processo seguiu SDD: [requisitos](docs/sdd/01-requirements.md) →
[design](docs/sdd/02-design.md) → [tarefas](docs/sdd/03-tasks.md) → teste → código.

### Quando o `/quote` falha (o diferencial)

Medi antes de decidir: 200 chamadas na configuração padrão deram **20,5% de 5xx, 8% de
respostas lentas (8 s) e 71,5% de sucesso rápido na 1ª tentativa**
([evidência](docs/evidence/quote_characterization.md)).

1. **Validar antes de chamar.** A API sorteia a falha antes da regra de negócio: um 503 não
   diz se o payload seria recusado. Idade, idade do veículo, plano, CEP e data são checados
   com as regras de `GET /planos` (snapshot versionado como fallback). Pelo dataset, ~30%
   dos leads seriam recusados: nesses casos o agente nem chama a API.
2. **Timeout de 3 s por tentativa.** A lentidão é `sleep(8)` e **depois** sucesso: sem timeout
   o lead esperaria 8 s. O teto vale para a tentativa inteira (`asyncio.timeout`), não só por
   operação de rede.
3. **Retry só em 5xx e timeout**, até 3 tentativas, backoff exponencial com jitter
   (~0,5 s, ~1 s), orçamento total de 12 s. Nunca em 400/422: repetir não muda a resposta.
4. **Circuit breaker por pedido**: 5 pedidos falhos seguidos abrem o circuito por 30 s, e o
   agente responde e passa para humano sem martelar o legado.
5. **Mensagem de espera** se passar de 4 s: no WhatsApp, silêncio parece abandono.
6. **Esgotou**: "o sistema de cotação está instável e não quero te passar um valor errado;
   um consultor vai te enviar a cotação", e handoff com os dados já coletados.
7. **Preço nunca inventado**: o LLM não tem campo para escrever valores; mensagens com número
   saem de templates preenchidos pela resposta 200, e um validador bloqueia qualquer R$ que
   não esteja na última cotação `success` (ou nas franquias do `/planos`).
8. **Idempotência explícita**: `quote_request_id` por pedido e `quote_attempt_id` por
   tentativa, enviados em headers (o `/quote` é cálculo puro, mas a intenção fica visível).

### Critério de handoff

Função pura `decide_handoff(contexto)` em [`domain/handoff.py`](agent/src/autoseguro_agent/domain/handoff.py):
uma regra por linha, avaliada em ordem de prioridade, um teste por regra e um teste que
quebra se surgir regra sem teste. O LLM só sinaliza intenções; quem decide é o código.

| Regra | Gatilho | Por quê | Prioridade |
|---|---|---|---|
| `explicit_request` | Pede atendente ou humano | Respeitar o cliente; insistir custa a venda | imediata |
| `infra_unavailable` | Retries esgotados ou breaker aberto | Não inventar preço nem deixar o lead sem resposta | imediata |
| `risk_or_conflict` | Reclamação, Procon, irritação forte | Situação sensível pede pessoa | alta |
| `out_of_policy` | Condutor > 75 ou < 18, carro > 20 anos, recusa da API | Exceção comercial é decisão humana | alta |
| `out_of_scope` | Sinistro, cancelamento, endosso, 2ª via, frota, Uber/app | O agente só vende seguro individual novo | alta |
| `agent_bug` | 422 de schema do FastAPI | Erro nosso: humano assume e o log vira bug | alta |
| `price_negotiation` | Desconto, cobrir concorrente, parcelamento especial | Sem alçada de desconto | média |
| `stuck` | 2 falhas no mesmo dado, 2 respostas sem o dado, 2 falhas do LLM | Evita loop e frustração | média |
| `media_unsupported` | 2 mídias para o mesmo dado pendente | O agente não lê mídia | média |
| `ready_to_close` | Cotação aceita, quer contratar | Contratação pede CPF, documentos e pagamento | fim feliz |

Dois ajustes vieram do dataset: **mídia aparece em 56,8% das conversas** (quase sempre CNH
ou foto do carro), então a 1ª mídia só gera "não preciso desse arquivo agora" e o handoff
fica para a 2ª; e "vou pensar" (17,6%) recebe resumo e porta aberta, não handoff.
O resumo do handoff leva dados mascarados, cotações com ids, regra, motivo, prioridade e
a última mensagem do lead.

### Rastreabilidade

| Entidade | Id | Status |
|---|---|---|
| Conversa | `conversation_id` (hash do telefone; o número nunca é guardado) | `active`, `quoted`, `handed_off` |
| Mensagem | `message_id` + `wa_message_id` (dedup de reentrega do webhook) | `received`, `processed`, `sent` |
| Pedido de cotação | `quote_request_id` | `pending`, `success`, `refused`, `invalid`, `failed` |
| Tentativa | `quote_attempt_id` + latência | `ok`, `timeout`, `http_5xx`, `refused`, `invalid`, `circuit_open` |
| Handoff | `handoff_id` | `opened` + regra e prioridade |

Tudo vai para uma tabela `events` em SQLite, **append-only por trigger** (UPDATE e DELETE
abortam), e para o log JSON (structlog) com os ids em toda linha.
`GET /conversations/{id}` devolve a linha do tempo. Exemplo real em
[`docs/demo-conversation.md`](docs/demo-conversation.md): *tentativa 1 timeout em 3.006 ms,
tentativa 2 http 502, tentativa 3 ok em 44 ms*, com a mensagem de espera antes do resultado.

### Dados sensíveis

- **Mascarados na entrada**, antes do LLM, do log e do checkpoint: CPF (com dígito
  verificador, para não confundir com telefone de 11 dígitos), e-mail, telefone com e sem
  DDD, placa antiga e Mercosul, CEP. Tokens estáveis por conversa (`<CPF_1>`, `<CEP_1>`).
- O valor real fica num **cofre separado**; o CEP só é resolvido na chamada ao `/quote`.
  O LLM nunca vê o CEP; o log grava só o prefixo (`01310-***`).
- **Minimização**: o vendedor do dataset pedia CPF em 100% das conversas; o `/quote` não usa
  CPF, então o agente não pede, e se vier, agradece e avisa que não precisa.
- O log tem um segundo filtro que remascara qualquer string (defesa em profundidade).
- Medido no dataset: **100% de recall nos 5 tipos, 0 mensagens com PII crua depois do
  mascaramento** ([evidência](docs/evidence/pii_recall.md)). Os relatórios do dataset só
  têm agregados; o parquet não é reprocessado em runtime.

### Por que LangGraph, e não um agente livre

O fluxo é decidido por código (arestas condicionais), o estado é tipado e vai para
checkpoint, e cada nó é testável isolado. Um agente com tools decidiria sozinho quando
cotar e o que dizer do preço — exatamente o que não pode acontecer aqui. Um nó de LLM basta
para este escopo; eu dividiria quando o prompt ou as tools crescessem.

### Por que SQLite

Zero setup para o avaliador e inspecionável com um comando
(`sqlite3 autoseguro.db "select event_type, status, latency_ms from events"`). Em
produção seria Postgres com a mesma tabela e as mesmas regras.

## Números medidos

| Medida | Resultado | Evidência |
|---|---|---|
| Falha real do `/quote` (padrão) | 20,5% 5xx · 8% lentas · 71,5% ok na 1ª | [caracterização](docs/evidence/quote_characterization.md) |
| Sucesso com retry (padrão, 100 conversas) | **97%** (previsto 97,7%) · 0 travas · 0 R$ sem cotação | [caos](docs/evidence/chaos_report.md) |
| Caos: 60% falha + 20% lenta, 50 conversas | **0 travas · 0 R$ sem cotação · 100% das falhas em handoff** · 52% cotadas | [caos](docs/evidence/chaos_report.md) |
| Golden set (FakeLLM) | **20 de 20** cenários | [golden](docs/evidence/golden_report.md) |
| Golden set com o Claude real | **60 de 60** em 3 rodadas seguidas (prompt v2); v1 tinha 18/20 | [golden Claude](docs/evidence/golden_claude.md) |
| Mascarador no dataset | 100% recall · 0 vazamentos · idades preservadas | [PII](docs/evidence/pii_recall.md) |
| Testes automatizados | 260 + 20 golden + caos; `ruff` e `mypy --strict` limpos | `make check` |

Golden set (resumo; tabela completa na evidência):

| | Cenário | Resultado |
|---|---|---|
| G01 | Caminho feliz, um dado por vez | cotado R$ 209,90 · passou |
| G02 / G05 / G19 | 22 anos (×1,60) · CEP de risco (×1,30) · 65 anos (×1,40) | R$ 335,84 · 272,87 · 293,86 · passou |
| G03 / G04 | Carro 2003 · condutor de 80 anos | recusa local, 0 chamadas · passou |
| G06 / G08 / G15 | Pede humano · pede desconto · quer fechar | handoff com a regra certa · passou |
| G07 / G07b | Foto e depois texto · áudio 2× | segue · handoff · passou |
| G09 | CPF sem ser pedido | mascarado e avisado · passou |
| G10 / G11 | API fora · API lenta 2× | handoff honesto sem R$ · espera e cotação · passou |
| G12 / G13 / G14 | CEP incompleto · sinistro · Uber | `stuck` · `out_of_scope` · passou |
| G16 / G17 / G18 | Sem plano · franquia alta · vou pensar | recomenda 1 · explica · resume · passou |

O que o Claude real ensinou: rodando o golden set com o modelo de verdade, a v1 do prompt
fez 18/20 e expôs dois bugs de código e três ambiguidades de prompt ("quero cotar" lido
como compra, "franquia alta" lido como reclamação). Com o prompt v2, 60/60 em três
rodadas ([detalhes](docs/evidence/golden_claude.md)). A [demo](docs/demo-conversation.md)
foi gerada com o Claude.

O que o caos ensinou: a primeira versão do breaker contava **tentativas**; os critérios
passavam, mas só 10% das conversas eram cotadas, porque o circuito abria com a API apenas
instável. Contando **pedidos** que falham depois dos retries, foram 52%, perto do teórico.

## Limitações e o que eu faria com mais tempo

- O golden set com o Claude real tem 20 cenários; em produção eu ampliaria com conversas
  reais anonimizadas e rodaria a cada mudança de prompt ou de modelo.
- Cofre de PII em memória: o checkpoint sobrevive a restart, o cofre não. Faria uma tabela
  cifrada com acesso restrito.
- Retry assíncrono da cotação depois do handoff (fila), avisando o lead se der certo.
- Breaker por taxa de falha numa janela de tempo, em vez de contagem consecutiva.
- Postgres, fila para mensagens, webhook sem estado; canal real do WhatsApp com verificação.
- Presidio com reconhecedores BR; avaliação com LLM-as-judge; métricas de conversão por
  regra de handoff ([métricas de produto](docs/agent-design/SMART.md)).

## Como usei IA

Planejei antes de pedir código (SDD, SOLID, SPARK, SMART e RACI em `docs/`), pedi teste
junto com cada pedaço, revisei e corrigi o que a IA gerou. Sessões exportadas e
sanitizadas, ferramentas usadas e os erros que peguei estão em [`ai-logs/`](ai-logs/).

## Estrutura

```
agent/                      # o agente (uv, ruff, mypy, pytest)
  src/autoseguro_agent/
    domain/                 # regras puras: modelos, elegibilidade, handoff, validador
    adapters/               # quote_http (resiliência), llm_anthropic, llm_fake, sqlite, breaker
    graph/                  # nós e montagem do LangGraph
    prompts/extract_v2.md   # prompt versionado (formato SPARK; v1 mantido para histórico)
    templates.py            # toda mensagem com número ou de falha
    pii.py                  # mascarador + cofre
    api.py · cli.py         # webhook WhatsApp e chat no terminal
    evaluation/             # caos, golden set e demo
  tests/                    # unit · contract · scenarios · chaos
analysis/                   # análise agregada do dataset e recall do mascarador
docs/                       # SDD, decisões, evidências, demo, design do agente
ai-logs/                    # conversas com IA, sanitizadas
quote-service/ · dataset/   # intocados
```
