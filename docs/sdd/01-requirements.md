# SDD 01 — Requisitos

> Spec-Driven Development: este arquivo diz **o quê** e **como sabemos que está pronto**.
> `02-design.md` diz **como**; `03-tasks.md` diz **em que ordem**. Nenhum código entra sem
> um requisito com ID aqui e um teste que o prove.
>
> Fonte: README do desafio, `quote-service/` (lido linha a linha) e o plano em PDF.
> Status: **rascunho v0.1 — 2026-11-25**, aguardando as decisões abertas da §6.

## 1. Objetivo

Agente de WhatsApp da AutoSeguro (fictícia) que conversa com o lead, qualifica, cota pelo
`POST /quote`, e decide entre resolver sozinho ou passar para humano, **sem travar e sem
inventar preço** quando a API falha.

**Tese:** o LLM conversa e extrai dados; o **código** decide fluxo, preço e handoff.

## 2. Fora de escopo (vai no README como "faria")

RAG, Redis, fila, Postgres, front-end, multiagente, canal real do WhatsApp (Meta/Twilio),
retry assíncrono agendado, Presidio, LLM-as-judge, métricas de conversão.

## 3. Requisitos funcionais

Formato: `REQ-xx` · enunciado (EARS) · critério de aceite verificável.

### Conversa e qualificação

| ID | Requisito | Aceite |
|---|---|---|
| REQ-01 | O agente deve coletar os slots obrigatórios: `idade`, `veiculo_ano`, `cep`, `plano_id`. `data_inicio` e modelo do carro são opcionais (data default = 1º dia do próximo mês, calculada pelo `Clock` e confirmada com o lead; decidido em 2026-11-25). | Cenário feliz do golden set chega à cotação perguntando só o que falta. |
| REQ-02 | Quando faltar um slot, o agente deve perguntar **um** dado por vez, o próximo da ordem fixa. | Teste de nó: estado com 2 slots faltando gera 1 pergunta. |
| REQ-03 | O agente deve pedir só o necessário para cotar (minimização). Se o lead mandar CPF/e-mail/placa espontaneamente, agradece e avisa que não é necessário agora. | Cenário "manda CPF sem pedir". |
| REQ-04 | O agente deve responder dúvidas sobre planos/coberturas/franquia/carência **apenas** com dados de `GET /planos`. | Pergunta "o que cobre o premium?" responde as coberturas do snapshot, sem LLM inventar. |
| REQ-05 | O agente deve permitir comparar planos e recotar com outro plano sem pedir os dados de novo. | Cenário "cota completo, depois premium". |
| REQ-06 | Quando o lead não escolher plano, o agente cota **um** plano recomendado por regra em código (`recommend_plan`, função pura) e oferece os outros por nome e coberturas, sem preço. Regra inicial: `completo` por padrão; `essencial` se o veículo tiver 11–20 anos. O LLM não recomenda plano. | Teste unitário da regra; cenário "não sei qual plano" gera 1 pedido de cotação e menciona os outros 2 sem R$. |

### Validação e cotação

| ID | Requisito | Aceite |
|---|---|---|
| REQ-10 | Antes de chamar `/quote`, o agente deve validar localmente: idade 18–75; `veiculo_ano` ≤ ano atual e idade do veículo ≤ 20; `plano_id` ∈ planos; CEP com 8 dígitos; `data_inicio` ISO, não no passado. Regras lidas de `GET /planos` na subida, fallback para snapshot versionado. | Testes unitários de `eligibility` por fronteira (17/18, 75/76, 20/21 anos, ano futuro, CEP 7 dígitos). |
| REQ-11 | Quando a validação local reprovar por política (idade/veículo), o agente **não** chama a API: explica o motivo e aplica a regra de handoff "fora da política". | Nenhuma tentativa registrada em `events` nesses cenários. |
| REQ-12 | Quando o dado estiver mal formatado, o agente pede correção **uma** vez; na segunda falha, handoff "conversa empacada". | Cenário "CEP inválido duas vezes". |
| REQ-13 | O preço apresentado deve vir **exclusivamente** da resposta 200 da API, por template: prêmio, franquia, coberturas, carência e pro-rata quando houver. | Teste de contrato: exemplo do README → R$ 209,90/mês e 1º pagamento R$ 115,11. |

### Resiliência do `/quote` (o diferencial)

| ID | Requisito | Aceite |
|---|---|---|
| REQ-20 | Timeout por tentativa de 3 s (configurável). | Teste com respx simulando 8 s: tentativa marcada `timeout` em ~3 s. |
| REQ-21 | Retry **só** para 500/502/503 e timeout: até 3 tentativas, backoff exponencial com jitter (~0,5 s, 1 s). Nunca retry em 400/422. | Testes por código de status contando tentativas. |
| REQ-22 | Orçamento total por pedido de cotação ≤ 12 s. | Teste de caos: p100 do tempo por pedido ≤ 12 s + folga. |
| REQ-23 | Se a cotação passar de 4 s, o agente envia mensagem de espera ("estou calculando…"). | Evento `message.sent` de espera antes do resultado. |
| REQ-24 | Circuit breaker: após N (=5) falhas seguidas, abre por 30 s; aberto, não chama a API e vai direto para handoff "infra indisponível". | Teste com relógio fake: 5 falhas → próxima chamada `circuit_open` sem HTTP; após 30 s, half-open. |
| REQ-25 | Esgotadas as tentativas, o agente diz com honestidade que o sistema de cotação está instável, que um consultor enviará o valor, e abre handoff com os dados coletados. | Teste de caos: toda falha esgotada termina em `handoff.opened`. |
| REQ-26 | 422 `cotacao_recusada`: não tenta de novo, explica o motivo da API, oferece outro plano só se a recusa for de plano; senão handoff. | Teste unitário do mapeamento de resposta. |
| REQ-27 | 422 do FastAPI (schema) é bug do agente: não tenta de novo, registra `invalid` com severidade erro e faz handoff. | Teste com respx retornando `{"detail":[...]}`. |

### Handoff

| ID | Requisito | Aceite |
|---|---|---|
| REQ-30 | O handoff é decidido por uma função pura `decide_handoff(state) -> HandoffDecision | None` com a tabela de regras do design (§5 de `02-design.md`). O LLM só **sinaliza** intenções. | Um teste por regra + teste de prioridade quando duas disparam. |
| REQ-31 | Todo handoff gera resumo estruturado: slots (mascarados), cotações com ids, regra, motivo, prioridade, última mensagem do lead. | Snapshot do resumo no golden set. |
| REQ-32 | Após o handoff, o agente avisa o lead e para de cotar naquela conversa (status `handed_off`). | Mensagem seguinte do lead não gera nova cotação. |

### Rastreabilidade

| ID | Requisito | Aceite |
|---|---|---|
| REQ-40 | Toda mensagem e cotação carrega `conversation_id`, `message_id`, `quote_request_id`, `quote_attempt_id` (quando aplicável) e status (tabela em `02-design.md` §6). | Teste: toda linha de `events` tem `conversation_id` e status válido. |
| REQ-41 | Eventos vão para tabela `events` append-only (SQLite) e para log JSON (structlog). | `UPDATE`/`DELETE` em `events` não existem no código (grep no CI). |
| REQ-42 | `GET /conversations/{id}` devolve a linha do tempo da conversa. | Teste de API. |
| REQ-43 | Webhook deduplica reentrega por `wa_message_id`. | Mesmo payload 2× → 1 processamento. |

### Dados sensíveis

| ID | Requisito | Aceite |
|---|---|---|
| REQ-50 | Mascarar CPF, e-mail, telefone, placa (antiga e Mercosul) e CEP **antes** do LLM, do log e do checkpoint, com tokens `<CPF_1>`, `<CEP_1>`… | Testes de `pii` por formato; teste de que o prompt enviado ao FakeLLM não contém dígitos de CPF. |
| REQ-51 | Valor real fica num cofre local separado, referenciado pelo token; só é resolvido na chamada da API (CEP) ou no handoff. | Teste do cofre. |
| REQ-52 | Logs gravam só o prefixo de 5 dígitos do CEP. | Grep no log de demo. |
| REQ-53 | Parquet bruto e mensagens cruas do dataset nunca aparecem em README, logs ou few-shot; `scripts/sanitize_ai_logs.py` roda antes de commitar `ai-logs/`. | Script com teste; checklist final. |

### Canais e entrega

| ID | Requisito | Aceite |
|---|---|---|
| REQ-60 | `POST /webhook/whatsapp` (payload no formato Cloud API) e CLI de chat (`make chat`). | Golden set roda pelo mesmo núcleo usado pelos dois canais. |
| REQ-61 | `docker compose up` sobe quote-service + agente; `make demo`, `make test`, `make chaos`. | Clone limpo → README → funciona. |
| REQ-62 | Entregáveis: README com decisões, `docs/DECISIONS.md`, `docs/demo-conversation.md` (com ao menos 1 falha + retry visível), `ai-logs/` + `ai-logs/README.md`. | Checklist final do `03-tasks.md`. |

## 4. Requisitos não funcionais

- **NFR-1 Determinismo:** extração com saída estruturada (schema Pydantic) e validação em código — a API do Claude não aceita `temperature` nos modelos atuais; relógio injetável (`Clock`); `QUOTE_SEED` nos testes de caos e na demo.
- **NFR-2 Testabilidade:** domínio não importa LangGraph, httpx nem SDK de LLM. Toda a suíte roda offline com `FakeLLM` + respx; só `make demo` precisa de chave.
- **NFR-3 Qualidade:** `ruff` + `mypy --strict` no `agent/src`; `make test` verde é pré-requisito de commit.
- **NFR-4 Um comando:** avaliador roda com `docker compose up` e `make demo`.

## 5. Fatos do `quote-service` que o plano em PDF não cobria (lidos no código)

1. **Plano inexistente volta 422 `cotacao_recusada`**, não 400 — por isso valida-se `plano_id` localmente.
2. **400 `payload_invalido`** só acontece com `data_inicio` mal formatada (`fromisoformat`) ou tipo que quebra `int()`. **422 do FastAPI** sai com `idade` fora de 0–200 ou `veiculo_ano` fora de 1950–2100.
3. **A API aceita `data_inicio` no passado.** O exemplo do README (15/07/2026) já é passado em relação a hoje (25/11/2026): o agente rejeita data passada (REQ-10), mas o **teste de contrato chama o gateway direto** com essa data.
4. **A idade do veículo usa `date.today()` do servidor.** O contrato "2022 → ×1,00" só vale até 2027; o teste de contrato fixa a expectativa pelo ano corrente ou usa ano relativo.
5. **Arredondamento:** prêmio arredondado uma vez; pro-rata calculado sobre o prêmio já arredondado (209,90 × 17/31 = **115,11**).
6. **`QUOTE_SEED` é um RNG global do processo:** a sequência depende de **todas** as chamadas desde a subida. Teste de caos e demo precisam de container recém-iniciado.
7. **A falha é sorteada antes da validação:** um 503 não diz nada sobre o payload (reforça REQ-10).
8. **CEP vazio vale ×1,0 e não é validado**; só os 2 primeiros dígitos contam.
9. **Lentidão = `sleep(8)` e depois sucesso**; o servidor continua processando após o timeout do cliente (sem efeito colateral, retry é seguro).

## 6. Decisões abertas (precisam de você)

1. ~~Provedor de LLM~~ → **decidido 2026-11-25: Claude (Anthropic), `claude-opus-5-5`** (ver `02-design.md` §12).
2. ~~Fork ou repo novo~~ → **decidido 2026-11-25: repo novo**, com o histórico do upstream preservado e `upstream` como remote de referência (T0.3).
3. ~~Data de início default~~ → **decidido 2026-11-25: 1º dia do mês seguinte** (via `Clock`), confirmado com o lead antes de cotar. Motivo: sem pro-rata, a primeira cotação mostra um valor único e mais fácil de entender; se o lead pedir outra data, ela é validada (não pode ser passada) e o pro-rata da API aparece.
4. ~~Exibir os 3 planos ou recomendar 1~~ → **decidido 2026-11-25: recomendar 1 e oferecer os outros** (ver REQ-06). Motivo: uma chamada ao `/quote` em vez de três (menos exposição aos ~30% de falha e à espera) e uma resposta mais simples no WhatsApp; comparar continua possível sob pedido (REQ-05).
