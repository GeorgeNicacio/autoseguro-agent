# RACI — agente × humano

> **R** = Responsável (executa) · **A** = Aprovador (responde pelo resultado, um só por linha)
> · **C** = Consultado (antes) · **I** = Informado (depois).
>
> Papéis:
> - **LLM** — nó de extração (entende a mensagem, sinaliza intenções).
> - **Agente** — código determinístico (fluxo, validação, cotação, handoff, mensagens).
> - **API** — `quote-service` (`/planos`, `/quote`), fonte única de preço.
> - **Consultor** — vendedor humano que recebe o handoff.
> - **Supervisor** — dono da política comercial e de exceções.
> - **Eng/Op** — quem mantém o agente (FDE).

## 1. Atendimento

| Atividade | LLM | Agente | API | Consultor | Supervisor | Eng/Op |
|---|---|---|---|---|---|---|
| Receber mensagem, deduplicar e registrar | | **R/A** | | | | I |
| Mascarar PII antes de LLM/log/checkpoint | | **R/A** | | | | I |
| Entender a mensagem (slots + intenções) | **R** | A | | | | |
| Decidir próxima pergunta | C | **R/A** | | | | |
| Tirar dúvida sobre planos/coberturas | C | **R/A** | C (`/planos`) | | | |
| Validar elegibilidade local | | **R/A** | C (`/planos`) | | | |
| Calcular preço | | | **R/A** | | | |
| Chamar `/quote` com timeout/retry/breaker | | **R/A** | | | | I |
| Apresentar cotação ao lead (template) | | **R/A** | C | | | |
| Comparar planos / recotar | C | **R/A** | C | | | |
| Avisar falha honestamente | | **R/A** | | I | | I |

## 2. Decisão de handoff (por regra)

| Regra | Decide | Executa o atendimento | Aprova exceção | Informado |
|---|---|---|---|---|
| `explicit_request` (pede humano) | Agente (R/A) | Consultor (R) | — | LLM sinaliza (C) |
| `infra_unavailable` | Agente (R/A) | Consultor (R): envia valor depois | — | Eng/Op (I) |
| `risk_or_conflict` (reclamação, Procon) | Agente (R) | Consultor (R) | **Supervisor (A)** | Eng/Op (I) |
| `out_of_policy` (>75 anos, >20 anos de carro) | Agente (R) | Consultor (R) | **Supervisor (A)** | — |
| `out_of_scope` (sinistro, cancelamento, frota, Uber) | Agente (R/A) | Consultor ou área certa (R) | — | — |
| `agent_bug` (422 de schema) | Agente (R) | Consultor (R) | — | **Eng/Op (A)**: corrige |
| `price_negotiation` (desconto, concorrente) | Agente (R) | Consultor (R) | **Supervisor (A)**: alçada | — |
| `stuck` (2 falhas no mesmo dado) | Agente (R/A) | Consultor (R) | — | Eng/Op (I): melhora prompt |
| `media_unsupported` (áudio/foto/doc) | Agente (R/A) | Consultor (R) | — | — |
| `ready_to_close` (quer contratar) | Agente (R/A) | **Consultor (R/A)**: CPF, documentos, pagamento | — | Supervisor (I) |

## 3. O que é **sempre** humano

- Conceder desconto, condição de pagamento especial ou cobrir concorrente.
- Aceitar exceção de política (idade, idade do veículo, uso comercial).
- Coletar CPF, documentos e dados de pagamento; emitir apólice.
- Tratar sinistro, cancelamento, endosso, segunda via, reclamação formal.
- Enviar valor quando a cotação automática falhou.

## 4. O que é **sempre** do agente (nunca do LLM)

- Qualquer número exibido ao lead.
- A decisão de chamar ou não a API, e de passar ou não para humano.
- Mascaramento, registro de eventos e ids.

## 5. Governança do próprio agente

| Atividade | Eng/Op | Supervisor | Consultor |
|---|---|---|---|
| Mudar regra de handoff (`HANDOFF_RULES`) | R | **A** | C |
| Mudar prompt (`prompts/extract_vN.md`) | **R/A** (golden set verde) | I | C (tom) |
| Mudar timeouts / breaker | **R/A** | I | |
| Revisar métricas SMART semanalmente | R | **A** | I |
| Incidente de PII | **R/A** | I | I |
