# Como usei IA neste desafio

## Ferramentas

| Ferramenta | Para quê |
|---|---|
| **Claude (claude.ai)** | Conversa de planejamento: leitura do desafio e do quote-service, escolha de stack, plano de 3 dias. Virou o PDF que guiou a execução (não versionado; ver abaixo). |
| **Claude Code (app desktop, Claude Opus 5.5)** | Execução inteira: SDD antes do código, TDD por tarefa, análise do dataset, implementação, testes de contrato/caos/golden contra a API real em Docker, documentação e este sanitizador. |
| **Claude (API, `claude-opus-5-5`)** | É o LLM do próprio agente (nó de extração), atrás de uma porta `LLMClient`. |

Sessões do Claude Code exportadas e sanitizadas em [`claude-code/`](claude-code/) (o `.jsonl`
cru, como a ferramenta salva). A conversa de planejamento no claude.ai e o PDF que saiu dela
**não estão no repositório por decisão minha**: misturam contexto pessoal e profissional de
fora do desafio. O conteúdo técnico do plano está refletido no SDD (`docs/sdd/`), e a
sessão do Claude Code mostra o plano sendo lido, conferido contra o código e corrigido
(itens 1 e 2 abaixo).

## Como orquestrei

1. **Planejar antes de pedir código.** Primeiro o SDD (`docs/sdd/`: requisitos com ID,
   design, tarefas), depois SOLID, SPARK, SMART e RACI (`docs/agent-design/`) e um
   `CLAUDE.md` com as regras inegociáveis ("o LLM nunca escreve números", "PII mascarada
   antes de tudo", "retry só em 5xx/timeout").
2. **Ler a fonte, não confiar no plano.** O código do quote-service foi lido linha a linha
   antes do design; as diferenças com o plano viraram a seção "fatos" dos requisitos.
3. **Medir antes de decidir.** Caracterização de 200 chamadas antes de escolher timeout e
   número de tentativas; análise do dataset antes de fechar as regras de handoff.
4. **Teste junto com cada pedaço.** Cada tarefa começou pelo teste (vermelho → verde),
   com `ruff` e `mypy --strict` limpos antes de cada commit; um commit por tarefa.
5. **Provar contra o sistema real.** Contrato, golden set, caos e demo rodam contra o
   quote-service em Docker, não só contra mocks.
6. **Decisões minhas nos pontos de escolha:** provedor do LLM (Claude), data de início
   padrão (1º do mês seguinte), recomendar um plano em vez de cotar três, repo novo.

## Onde a IA (ou o plano) errou, e como pegamos

1. **Plano × código do quote-service.** O plano dizia que dado mal formatado gera 400;
   lendo o código, plano inexistente gera 422 `cotacao_recusada` e o exemplo do README usa
   uma data já no passado. Pego lendo a fonte; virou validação local e teste de contrato.
2. **"Temperatura 0".** O plano pedia temperatura 0 na extração; a API atual do Claude
   rejeita `temperature`. Trocado por saída estruturada + `effort: low` + validação em código.
3. **Regex de uso comercial com falso positivo.** A 1ª análise contou 448 conversas com
   "uso comercial"; o padrão incluía `99` (de "99 Pop") e casava com dígitos de telefone e
   CPF. Conferido contra o gerador do dataset → 0.
4. **Mídia como gatilho de handoff.** O design passava para humano na 1ª mídia; o dataset
   mostrou mídia em 56,8% das conversas → handoff só na 2ª mídia para o mesmo dado.
5. **Circuit breaker por tentativa.** O caos passou nos três critérios, mas só 10% das
   conversas foram cotadas: o breaker abria com a API apenas instável. Contando pedidos
   que falham depois dos retries → 52% sob caos e 97% na configuração padrão.
6. **Timeout do httpx não basta.** O teste com resposta lenta mostrou que ele vale por
   operação de rede; entrou `asyncio.timeout` na tentativa inteira.
7. **Filtro de PII mascarando ids.** No smoke test em Docker, o hash do `conversation_id`
   tinha 8 dígitos seguidos e virava `<CEP_1>` no log, quebrando o rastreio. Corrigido com
   borda de palavra e campos de id fora do filtro; recall no dataset conferido de novo.
8. **Sanitizador dos próprios logs.** A 1ª versão travou (regex de e-mail sem limite,
   quadrática nos blocos base64) e depois quebrou o JSON (leu `\n@app.get` como e-mail).
   Pego validando cada linha do `.jsonl` após a sanitização.
9. **Mensagens bagunçadas com o LLM fora do ar.** A demo com uma chave sem crédito mostrou
   pergunta de retry e aviso de falha na mesma resposta. Agora o turno com LLM indisponível
   responde só "pode repetir?" e, na 2ª falha seguida, passa para humano (teste adicionado).

## Sanitização

`scripts/sanitize_ai_logs.py` remove chaves e tokens de API, e-mails, CPF, telefones, CEPs,
placas, nomes do dataset sintético, o usuário do sistema nos caminhos e termos pessoais
passados por variável de ambiente (que por isso não aparecem no repositório). Depois,
`--check` confere que nada sensível sobrou, e cada linha do `.jsonl` é validada como JSON.

```bash
SANITIZE_EXTRA="<seu e-mail>,<seu telefone>,w:<usuário do sistema>" \
  py scripts/sanitize_ai_logs.py --src ~/.claude/projects/<slug> --out ai-logs/claude-code
py scripts/sanitize_ai_logs.py --check ai-logs
```

## Pendências antes de enviar

- Reexportar a sessão do Claude Code no fim (ela continua crescendo) e rodar o sanitizador.
