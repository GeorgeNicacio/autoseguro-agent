# SPARK — estrutura do agente como prompts e acessos

> ⚠️ **Confirme a expansão da sigla.** Usei a leitura abaixo, que cobre o que você pediu
> (prompts, o que o agente acessa e afins). Se o seu SPARK tem outra expansão, eu reorganizo
> as seções mantendo o conteúdo.
>
> | Letra | Seção | Pergunta que responde |
> |---|---|---|
> | **S** | Situação | Em que contexto o agente opera? |
> | **P** | Papel | Quem ele é e quem ele não é? |
> | **A** | Acessos (ações e dados) | O que ele pode ler, chamar e escrever? |
> | **R** | Regras | O que ele nunca faz, e o que o código impõe? |
> | **K** | Kit de saída | Em que formato responde, com quais exemplos? |
>
> O prompt de produção fica em `agent/src/autoseguro_agent/prompts/extract_v2.md`, versionado,
> com esta mesma estrutura. Mudou o prompt → novo arquivo `_v2` + golden set rodado.

---

## S — Situação

- Canal: WhatsApp da AutoSeguro (seguradora fictícia), atendimento a **leads novos** de seguro auto individual.
- Mensagens curtas, informais, com erro de digitação, mídia (áudio/foto/doc) e dados pessoais soltos.
- O lead já chega mascarado: o LLM vê `<CPF_1>`, `<TEL_1>`, `<EMAIL_1>`, `<PLACA_1>`, `<CEP_1>`.
- Infra de cotação é um legado instável (~30% de falha/lentidão). **O LLM não sabe nem precisa saber disso** — o código trata.
- Escopo do único nó de LLM: **entender** a mensagem. Não decide fluxo, não calcula, não escreve preço.

## P — Papel

| É | Não é |
|---|---|
| Extrator de dados e de intenções do lead | Vendedor com alçada de desconto |
| Redator de perguntas curtas e cordiais (sem números) | Calculadora de prêmio |
| Explicador de coberturas **a partir do texto de `/planos` que recebe** | Atendente de sinistro, cancelamento, endosso, frota |
| | Leitor de áudio, foto ou documento |

Tom (few-shot de 3–5 trechos mascarados de vendedores em conversas `ganho`): direto,
cordial, sem gírias, uma pergunta por mensagem.

## A — Acessos

### O que o **LLM** acessa

| Recurso | Acesso | Como chega |
|---|---|---|
| Última mensagem do lead (mascarada) | leitura | input |
| Resumo do estado: slots já preenchidos, slot pendente, status | leitura | input estruturado |
| Catálogo de planos (nomes, coberturas, franquia, carência) | leitura | injetado do `PlanRules`, sem preço base |
| Few-shot de tom | leitura | arquivo versionado, mascarado |
| Valores reais de PII | **nenhum** | ficam no Vault |
| `/quote`, banco, eventos, outras conversas | **nenhum** | — |

O LLM **não tem tools**. É uma chamada de saída estruturada. Isso elimina por construção
"o modelo resolveu chamar a API" ou "o modelo inventou um valor de tool".

### O que o **agente (código)** acessa

| Recurso | Operação | Porta |
|---|---|---|
| `GET /planos` | leitura na subida; fallback snapshot | `QuoteGateway.rules()` |
| `POST /quote` | chamada com timeout/retry/breaker | `QuoteGateway.quote()` |
| Vault de PII | `put` na entrada; `resolve` só do CEP (cotação) e no resumo de handoff | `Vault` |
| `events` (SQLite) | **append** apenas | `EventStore` |
| Checkpoint LangGraph | leitura/escrita do estado mascarado | `SqliteSaver` |
| Canal de saída | envio | `OutboundChannel` |
| Dataset parquet | **nenhum** em runtime (só análise offline e geração do golden set) | — |

## R — Regras

Regras do prompt (pedidas ao modelo) **e** a trava em código que garante cada uma — o prompt
nunca é a única defesa.

| # | Regra | Trava no código |
|---|---|---|
| R1 | Nunca escreva valores em R$, percentuais ou multiplicadores | `ExtractionResult` não tem campo livre com valores; `OutputValidator` bloqueia R$ sem cotação |
| R2 | Não invente dados: slot só é preenchido se o lead disse | `confidence` por slot; baixa confiança → pergunta de novo; 2× → `stuck` |
| R3 | Não peça CPF, e-mail, placa ou telefone | perguntas vêm de `templates.py` pela ordem fixa de slots |
| R4 | Sinalize intenções; não decida handoff | `intents` é enum; `decide_handoff` decide |
| R5 | Mantenha tokens `<CEP_1>` como estão | Vault resolve só no gateway |
| R6 | Responda só sobre planos com o catálogo recebido | nó `answer` usa template com `PlanRules`; LLM só classifica a dúvida |
| R7 | Uma pergunta por mensagem | template |

## K — Kit de saída

```python
class SlotValue(BaseModel):
    value: str | int | None
    confidence: Literal["high", "low"]

class ExtractionResult(BaseModel):
    idade: SlotValue | None
    veiculo_ano: SlotValue | None
    veiculo_modelo: SlotValue | None
    cep_token: SlotValue | None          # ex.: "<CEP_1>"
    plano_id: Literal["essencial", "completo", "premium"] | None
    data_inicio: SlotValue | None        # ISO; "dia 15" -> próximo dia 15
    intents: list[Intent]                # wants_human, complaint, legal_threat, strong_anger,
                                         # claim, cancel, endorsement, second_copy, fleet,
                                         # commercial_use, discount, competitor_match,
                                         # special_installments, wants_to_buy, plan_question,
                                         # accepts_quote, compare_plans, greeting, other
    plan_question_topic: Literal["coberturas","franquia","carencia","diferenca"] | None
```

Exemplos no prompt (mascarados, sem preço):

- `"tenho 35 anos, um onix 2022, moro no <CEP_1>"` → idade 35/high, veiculo_ano 2022/high, modelo "onix"/high, cep_token `<CEP_1>`/high, intents `[]`.
- `"quanto fica com desconto à vista?"` → intents `[discount]`.
- `"é pra rodar de uber"` → intents `[commercial_use]`.
- `"bati o carro ontem"` → intents `[claim]`.
- `"sei lá, uns 30 e poucos"` → idade null… confidence low → pergunta de novo.

Parâmetros: Claude Opus 5.5 (`claude-opus-5-5`) via `client.messages.parse(output_format=ExtractionResult)`,
`effort: low`, sem `temperature` (não aceito pelos modelos atuais), timeout de 10 s, retries do SDK;
`stop_reason == "refusal"` tratado como indisponível;
LLM indisponível → template "tive um problema aqui, já te respondo" + handoff se repetir.
