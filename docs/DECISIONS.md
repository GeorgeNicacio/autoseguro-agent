# Decisões (ADRs curtos)

Formato: contexto → decisão → alternativa descartada → trade-off. Datas em 2026-11.

## ADR-001 · Um grafo LangGraph com um único nó de LLM
- **Contexto:** o agente precisa entender texto livre, mas preço, fluxo e handoff não podem depender do modelo.
- **Decisão:** LangGraph com estado tipado e checkpoint; só o nó `extract` chama o LLM, com saída estruturada. O resto é código.
- **Alternativa:** agente com tools escolhendo quando cotar e o que responder.
- **Trade-off:** menos "conversa natural" nas perguntas (vêm de templates), em troca de comportamento previsível e testável nó a nó.

## ADR-002 · Claude `claude-opus-5-5` com `messages.parse`, `effort: low`, sem `temperature`
- **Contexto:** o plano pedia "temperatura 0"; a API atual do Claude não aceita parâmetros de amostragem (400).
- **Decisão:** saída estruturada (`output_format=ExtractionResult`), `effort: low`, system prompt fixo (cacheável) e versionado em formato SPARK. Recusa do modelo e erros do SDK viram `LLMUnavailableError`.
- **Alternativa:** temperatura 0 com JSON livre parseado na mão.
- **Trade-off:** o determinismo vem do schema + validação + golden set, não da amostragem. Se a latência pesar, testar `claude-haiku-5-5` trocando só `AGENT_LLM_MODEL`.
- **Prompt v2:** o golden set com o Claude real (v1: 18/20) levou a `wants_recommendation`, a "extraia mesmo se parecer fora da política" e a definições mais estreitas de `wants_to_buy` e `complaint`. Com o v2: 60/60 em três rodadas ([evidência](evidence/golden_claude.md)).

## ADR-003 · Preço só da API, por template, com validador de saída
- **Contexto:** inventar preço é o pior erro possível.
- **Decisão:** o LLM não tem campo para escrever valores; mensagens com número saem de `templates.py` com dados da resposta 200; `validate_output` bloqueia qualquer R$ (ou %) que não esteja na última cotação `success` ou nas franquias do `/planos`.
- **Alternativa:** pedir ao LLM que não invente.
- **Trade-off:** respostas sobre preço são menos flexíveis; nenhuma depende de o modelo obedecer.

## ADR-004 · Resiliência do `/quote`: 3 s, 3 tentativas, backoff com jitter, 12 s de orçamento
- **Contexto:** medido 20,5% de 5xx e 8% de lentidão de 8 s ([evidência](evidence/quote_characterization.md)).
- **Decisão:** timeout por tentativa de 3 s (`asyncio.timeout` + httpx), retry só em 5xx/timeout, até 3 tentativas, backoff ~0,5 s/~1 s com jitter (tenacity), orçamento de 12 s, mensagem de espera após 4 s.
- **Alternativa:** timeout do httpx sozinho; ou mais tentativas.
- **Trade-off:** 3 tentativas dão ~97,7% de sucesso previsto (97% medido) com pior caso ~10,5 s; mais tentativas estourariam o tempo que um lead espera no WhatsApp.

## ADR-005 · Circuit breaker próprio, contando pedidos e não tentativas
- **Contexto:** a v1 contava tentativas; no caos, o circuito abria com a API só instável e só 10% das conversas eram cotadas ([evidência](evidence/chaos_report.md)).
- **Decisão:** conta pedidos que falharam depois de todos os retries; 5 seguidos abrem por 30 s; half-open deixa 1 pedido passar. ~40 linhas, testado com relógio fake.
- **Alternativa:** lib pronta de breaker; contagem por tentativa.
- **Trade-off:** com o legado de fato fora, demora mais para abrir. Em produção: taxa de falha numa janela de tempo.

## ADR-006 · Validação local antes de chamar a API
- **Contexto:** a API sorteia a falha antes da regra de negócio; plano inexistente vira 422 de recusa; ano no futuro e CEP malformado não são validados por ela.
- **Decisão:** `eligibility.py` separa erro de formato (pedir correção uma vez) de recusa de política (handoff sem chamar a API), com regras lidas de `GET /planos` e snapshot como fallback.
- **Trade-off:** as regras ficam duplicadas como leitura; um teste compara o snapshot com o `plans.json` do serviço e o teste de contrato compara as faixas com o que a API aplica.

## ADR-007 · Handoff como tabela de regras em código
- **Decisão:** `decide_handoff` puro, 10 regras em ordem de prioridade, um teste por regra e um teste que quebra se surgir regra sem teste. Resumo estruturado com dados mascarados e ids.
- **Alternativa:** pedir ao LLM que decida quando passar para humano.
- **Trade-off:** regras explícitas são menos "espertas", mas defensáveis, auditáveis e com motivo.

## ADR-008 · Mídia gera handoff só na 2ª vez para o mesmo dado
- **Contexto:** 56,8% das conversas do dataset têm mídia, quase sempre CNH ou foto do carro, que não são necessárias para cotar.
- **Decisão:** 1ª mídia → "não preciso desse arquivo agora" e o fluxo segue; 2ª mídia no mesmo dado pendente → handoff `media_unsupported`.
- **Trade-off:** um lead que só manda áudio espera uma mensagem a mais antes do humano.

## ADR-009 · Data de início padrão: dia 1º do mês seguinte
- **Decisão:** sem data informada, usa o 1º do mês seguinte e avisa na 1ª cotação; outra data é validada (não pode ser passada) e o pro-rata vem da API.
- **Trade-off:** a 1ª cotação mostra um valor só, mais simples; quem quer começar já precisa pedir.

## ADR-010 · Sem plano escolhido, recomendar um (por regra) e oferecer os outros sem preço
- **Decisão:** `recommend_plan`: completo por padrão; essencial para carro de 11 a 20 anos. Uma chamada ao `/quote` em vez de três.
- **Trade-off:** menos comparação imediata, menos exposição à instabilidade; comparar continua a um pedido de distância.

## ADR-011 · PII por regex testada + cofre de tokens
- **Decisão:** regex para CPF (com dígito verificador), e-mail, telefone, placa antiga e Mercosul, CEP; tokens estáveis por conversa; CEP real só no gateway; log com prefixo do CEP e segundo filtro; ids de rastreio fora do filtro (bug encontrado no smoke test em Docker).
- **Alternativa:** Presidio/NER.
- **Trade-off:** formatos brasileiros são fechados e a regex é previsível e rápida (100% de recall no dataset); Presidio com reconhecedores BR fica como "faria". Cofre em memória não sobrevive a restart.

## ADR-012 · SQLite append-only para eventos e checkpoint
- **Decisão:** tabela `events` com triggers que abortam UPDATE/DELETE; `AsyncSqliteSaver` para o estado; structlog JSON com os mesmos ids.
- **Trade-off:** zero setup e inspecionável; não escala para escrita concorrente alta — em produção, Postgres.

## ADR-013 · Canal simulado: webhook no formato do WhatsApp Cloud API + CLI
- **Decisão:** `POST /webhook/whatsapp` com o payload da Cloud API, `conversation_id` = hash do telefone, dedup por `wa_message_id`; as respostas voltam no corpo (simulando o envio).
- **Trade-off:** sem dependência de Meta/Twilio; falta a verificação do webhook e o envio assíncrono real.

## ADR-014 · Docker sobe com FakeLLM por padrão
- **Contexto:** o avaliador precisa rodar sem chave.
- **Decisão:** `AGENT_LLM_PROVIDER=fake` por padrão no compose; com chave, uma variável troca para o Claude. Toda a suíte roda offline.
- **Trade-off:** a demo padrão não exercita o LLM real; o que ela prova é o fluxo, a resiliência e o rastreio.

## ADR-015 · Redis para cache e fila (RQ), sem infraestrutura mais robusta
- **Contexto:** a fase 4 pediu redução de custo e latência, filas e um dashboard, num teste de escopo fechado.
- **Decisão:** um container Redis para cache (cotação, regras, extração do LLM, consultas quentes) e para a fila (RQ). Caches como decorators nas portas; um worker `SimpleWorker` roda o agente; prompt caching da Anthropic no system prompt; métricas agregadas dos eventos.
- **Alternativas:** Celery/Kafka/SQS, Temporal, Prometheus/OpenTelemetry, cache semântico.
- **Trade-off:** simples e suficiente para o teste, mas sem partição por conversa, DLQ, alta disponibilidade nem séries temporais. A tabela "neste teste × em produção" está no README.

## ADR-016 · O que entra (e o que não entra) na chave de cache
- **Cotação:** campos do cálculo segundo `/planos` + versão das regras + data do dia; CEP só pelo prefixo de 2 dígitos (a regra publicada), o que também evita guardar o CEP completo. Só resposta 200 é cacheada.
- **Extração:** texto mascarado normalizado + dado esperado + data + prompt + modelo. Os dados já coletados ficam fora de propósito: mais hits, e a extração da mensagem quase não depende deles.
- **Golden set roda sem cache:** ele avalia o fluxo e o modelo de verdade; com cache, a 2ª rodada não testaria nada.

## ADR-017 · Modelo do Claude escolhido por medição, com proteção determinística
- **Contexto:** o dashboard passou a permitir escolher Opus, Sonnet ou Haiku 5.5 por conversa e no golden set, para achar o modelo mais barato que ainda acerta tudo.
- **Medição:** Opus 24/24 (US$ 0,161 por rodada), Sonnet 24/24 (US$ 0,091), Haiku 22/24 (US$ 0,005). As 2 falhas do Haiku eram dados extraíveis sem interpretação (mensagem só com o CEP; nome do plano).
- **Decisão:** quando a mensagem tem um único token de CEP ou um único nome de plano e o LLM não devolve, o código preenche (`source: codigo` no evento). Com isso o Haiku fez 24/24 em 3 rodadas, ~33× mais barato que o Opus, mesma latência ([evidência](evidence/model_comparison.md)).
- **Trade-off:** inferir o plano pelo nome escrito pode errar numa negação ("não quero o premium"); o cenário é raro e o lead vê a cotação antes de fechar. O modelo padrão continua configurável (`AGENT_LLM_MODEL`).
