# Log de uma execução completa (entregável 4)

Gerado por `python -m autoseguro_agent.evaluation.demo` em 26/11/2026 17:35 · LLM: claude-haiku-5-5 · quote-service real com instabilidade padrão e `QUOTE_SEED=4` · regras de `/planos` vindas da api.

`conversation_id = demo_001`. As falas do lead aparecem como o agente as guarda e manda ao LLM: já mascaradas (o lead digitou um CPF e um CEP fictícios).

## Conversa

**Lead:** Oi, quero fazer o seguro do meu carro

**Agente:** Olá! Sou o assistente virtual da AutoSeguro e vou te ajudar a cotar o seguro do seu carro.

**Agente:** Pra começar, qual é o modelo e o ano do seu carro?

**Lead:** é um Onix 2022

**Agente:** Qual é a sua idade?

**Lead:** 35 anos

**Agente:** Qual é o CEP de onde o carro fica à noite?

**Lead:** meu cpf é <CPF_1> e o cep é <CEP_1>

**Agente:** Obrigado! Para a cotação não preciso de CPF, e-mail, telefone ou placa — pode ficar tranquilo.

**Agente:** Temos três planos: Essencial, Completo e Premium. Já tem um em mente ou quer que eu recomende?

**Lead:** quero o completo

**Agente:** Estou calculando sua cotação, só um instante.

**Agente:** Vou considerar o início da vigência em 01/12/2026. Se preferir outra data, é só me dizer.

**Agente:** Prontinho! Cotação do plano Completo:  
• Mensalidade: R$ 209,90  
• Franquia: R$ 3.000,00  
• Coberturas: colisão, roubo, furto, danos a terceiros e vidros  
• Carência de 30 dias para roubo e furto, a partir do início da vigência  
Quer seguir com esse plano?

**Lead:** e o premium?

**Agente:** Prontinho! Cotação do plano Premium:  
• Mensalidade: R$ 339,90  
• Franquia: R$ 1.500,00  
• Coberturas: colisão, roubo, furto, danos a terceiros, vidros, carro reserva e assistência 24h  
• Carência de 30 dias para roubo e furto, a partir do início da vigência  
Quer seguir com esse plano?

**Lead:** fechado, quero contratar

**Agente:** Ótimo! Para contratar, um consultor vai seguir com você por aqui para os documentos e o pagamento.

## Estado final

- Status da conversa: `handed_off`
- Handoff: `ready_to_close` (`ho_msg_b867b012d0e7`)
- Perfil guardado (mascarado): `{'idade': 35, 'veiculo_ano': 2022, 'veiculo_modelo': 'Onix', 'cep_token': '<CEP_1>', 'plano_id': 'premium', 'data_inicio': None}`

## Linha do tempo de eventos

Mesma linha do tempo que `GET /conversations/{id}` devolve e que vai para o log JSON.

| # | Evento | Status | Latência | message_id | quote_request_id | quote_attempt_id | Detalhe |
|---|---|---|---|---|---|---|---|
| 1 | `message.received` | received |  | msg_44d0e42d39ee |  |  | PII mascarada: nenhum |
| 2 | `trace.span` | ok | 0 ms | msg_44d0e42d39ee |  |  | nó ingest |
| 3 | `llm.call` | none | 1635 ms | msg_44d0e42d39ee |  |  | claude-haiku-5-5 · extract_v3 · 143 in / 24 out / 3558 cache · US$ 0.000062 |
| 4 | `trace.span` | ok | 1635 ms | msg_44d0e42d39ee |  |  | nó extract |
| 5 | `trace.span` | ok | 0 ms | msg_44d0e42d39ee |  |  | nó apply |
| 6 | `trace.span` | ok | 0 ms | msg_44d0e42d39ee |  |  | nó route |
| 7 | `trace.span` | ok | 0 ms | msg_44d0e42d39ee |  |  | nó respond |
| 8 | `message.sent` | sent |  | msg_44d0e42d39ee |  |  |  |
| 9 | `message.sent` | sent |  | msg_44d0e42d39ee |  |  |  |
| 10 | `trace.span` | ok | 0 ms | msg_44d0e42d39ee |  |  | nó deliver |
| 11 | `message.received` | processed |  | msg_44d0e42d39ee |  |  |  |
| 12 | `turn.finished` | active | 1642 ms | msg_44d0e42d39ee |  |  |  |
| 13 | `message.received` | received |  | msg_f4e4caf9ec0d |  |  | PII mascarada: nenhum |
| 14 | `trace.span` | ok | 0 ms | msg_f4e4caf9ec0d |  |  | nó ingest |
| 15 | `llm.call` | none | 756 ms | msg_f4e4caf9ec0d |  |  | claude-haiku-5-5 · extract_v3 · 136 in / 62 out / 3558 cache · US$ 0.000080 |
| 16 | `trace.span` | ok | 756 ms | msg_f4e4caf9ec0d |  |  | nó extract |
| 17 | `slot.updated` | ok |  | msg_f4e4caf9ec0d |  |  | veiculo_ano = 2022 |
| 18 | `slot.updated` | ok |  | msg_f4e4caf9ec0d |  |  | veiculo_modelo = Onix |
| 19 | `trace.span` | ok | 0 ms | msg_f4e4caf9ec0d |  |  | nó apply |
| 20 | `trace.span` | ok | 0 ms | msg_f4e4caf9ec0d |  |  | nó route |
| 21 | `trace.span` | ok | 0 ms | msg_f4e4caf9ec0d |  |  | nó respond |
| 22 | `message.sent` | sent |  | msg_f4e4caf9ec0d |  |  |  |
| 23 | `trace.span` | ok | 0 ms | msg_f4e4caf9ec0d |  |  | nó deliver |
| 24 | `message.received` | processed |  | msg_f4e4caf9ec0d |  |  |  |
| 25 | `turn.finished` | active | 761 ms | msg_f4e4caf9ec0d |  |  |  |
| 26 | `message.received` | received |  | msg_852b7817830d |  |  | PII mascarada: nenhum |
| 27 | `trace.span` | ok | 0 ms | msg_852b7817830d |  |  | nó ingest |
| 28 | `llm.call` | none | 759 ms | msg_852b7817830d |  |  | claude-haiku-5-5 · extract_v3 · 155 in / 87 out / 3558 cache · US$ 0.000095 |
| 29 | `trace.span` | ok | 759 ms | msg_852b7817830d |  |  | nó extract |
| 30 | `slot.updated` | ok |  | msg_852b7817830d |  |  | idade = 35 |
| 31 | `trace.span` | ok | 0 ms | msg_852b7817830d |  |  | nó apply |
| 32 | `trace.span` | ok | 0 ms | msg_852b7817830d |  |  | nó route |
| 33 | `trace.span` | ok | 0 ms | msg_852b7817830d |  |  | nó respond |
| 34 | `message.sent` | sent |  | msg_852b7817830d |  |  |  |
| 35 | `trace.span` | ok | 0 ms | msg_852b7817830d |  |  | nó deliver |
| 36 | `message.received` | processed |  | msg_852b7817830d |  |  |  |
| 37 | `turn.finished` | active | 764 ms | msg_852b7817830d |  |  |  |
| 38 | `message.received` | received |  | msg_96cf5cc3ea6b |  |  | PII mascarada: CPF, CEP |
| 39 | `trace.span` | ok | 0 ms | msg_96cf5cc3ea6b |  |  | nó ingest |
| 40 | `llm.call` | none | 706 ms | msg_96cf5cc3ea6b |  |  | claude-haiku-5-5 · extract_v3 · 182 in / 37 out / 3558 cache · US$ 0.000072 |
| 41 | `trace.span` | ok | 706 ms | msg_96cf5cc3ea6b |  |  | nó extract |
| 42 | `slot.updated` | ok |  | msg_96cf5cc3ea6b |  |  | cep_token = 01310-*** |
| 43 | `trace.span` | ok | 0 ms | msg_96cf5cc3ea6b |  |  | nó apply |
| 44 | `trace.span` | ok | 0 ms | msg_96cf5cc3ea6b |  |  | nó route |
| 45 | `trace.span` | ok | 0 ms | msg_96cf5cc3ea6b |  |  | nó respond |
| 46 | `message.sent` | sent |  | msg_96cf5cc3ea6b |  |  |  |
| 47 | `message.sent` | sent |  | msg_96cf5cc3ea6b |  |  |  |
| 48 | `trace.span` | ok | 0 ms | msg_96cf5cc3ea6b |  |  | nó deliver |
| 49 | `message.received` | processed |  | msg_96cf5cc3ea6b |  |  |  |
| 50 | `turn.finished` | active | 711 ms | msg_96cf5cc3ea6b |  |  |  |
| 51 | `message.received` | received |  | msg_22c143556cdf |  |  | PII mascarada: nenhum |
| 52 | `trace.span` | ok | 0 ms | msg_22c143556cdf |  |  | nó ingest |
| 53 | `llm.call` | none | 732 ms | msg_22c143556cdf |  |  | claude-haiku-5-5 · extract_v3 · 180 in / 29 out / 3558 cache · US$ 0.000068 |
| 54 | `trace.span` | ok | 732 ms | msg_22c143556cdf |  |  | nó extract |
| 55 | `slot.updated` | ok |  | msg_22c143556cdf |  |  | plano_id = completo |
| 56 | `trace.span` | ok | 0 ms | msg_22c143556cdf |  |  | nó apply |
| 57 | `trace.span` | ok | 0 ms | msg_22c143556cdf |  |  | nó route |
| 58 | `message.sent` | sent |  | msg_22c143556cdf |  |  | mensagem de espera |
| 59 | `quote_request.started` | pending |  | msg_22c143556cdf | qr_8bcca2c4e84c |  | completo · início 2026-12-01 |
| 60 | `quote_attempt` | timeout | 3003 ms | msg_22c143556cdf | qr_8bcca2c4e84c | qa_690d295905b7 | tentativa 1 · http — |
| 61 | `quote_attempt` | http_5xx | 2 ms | msg_22c143556cdf | qr_8bcca2c4e84c | qa_5fa3c0538f05 | tentativa 2 · http 502 |
| 62 | `quote_attempt` | ok | 1 ms | msg_22c143556cdf | qr_8bcca2c4e84c | qa_9759c6693735 | tentativa 3 · http 200 |
| 63 | `quote_request.finished` | success | 4708 ms | msg_22c143556cdf | qr_8bcca2c4e84c |  | 3 tentativa(s) 209.90 |
| 64 | `conversation.status` | quoted |  | msg_22c143556cdf |  |  |  |
| 65 | `trace.span` | ok | 4708 ms | msg_22c143556cdf |  |  | nó quote |
| 66 | `trace.span` | ok | 0 ms | msg_22c143556cdf |  |  | nó route_quote |
| 67 | `trace.span` | ok | 0 ms | msg_22c143556cdf |  |  | nó present |
| 68 | `message.sent` | sent |  | msg_22c143556cdf |  |  |  |
| 69 | `message.sent` | sent |  | msg_22c143556cdf |  |  |  |
| 70 | `trace.span` | ok | 0 ms | msg_22c143556cdf |  |  | nó deliver |
| 71 | `message.received` | processed |  | msg_22c143556cdf |  |  |  |
| 72 | `turn.finished` | quoted | 5447 ms | msg_22c143556cdf |  |  |  |
| 73 | `message.received` | received |  | msg_9328429a042b |  |  | PII mascarada: nenhum |
| 74 | `trace.span` | ok | 0 ms | msg_9328429a042b |  |  | nó ingest |
| 75 | `llm.call` | none | 1462 ms | msg_9328429a042b |  |  | claude-haiku-5-5 · extract_v3 · 208 in / 36 out / 3558 cache · US$ 0.000074 |
| 76 | `trace.span` | ok | 1462 ms | msg_9328429a042b |  |  | nó extract |
| 77 | `slot.updated` | ok |  | msg_9328429a042b |  |  | plano_id = premium |
| 78 | `trace.span` | ok | 0 ms | msg_9328429a042b |  |  | nó apply |
| 79 | `trace.span` | ok | 0 ms | msg_9328429a042b |  |  | nó route |
| 80 | `quote_request.started` | pending |  | msg_9328429a042b | qr_309935b01a40 |  | premium · início 2026-12-01 |
| 81 | `quote_attempt` | http_5xx | 1 ms | msg_9328429a042b | qr_309935b01a40 | qa_a8b2a7c058f1 | tentativa 1 · http 500 |
| 82 | `quote_attempt` | ok | 1 ms | msg_9328429a042b | qr_309935b01a40 | qa_7851abb19511 | tentativa 2 · http 200 |
| 83 | `quote_request.finished` | success | 604 ms | msg_9328429a042b | qr_309935b01a40 |  | 2 tentativa(s) 339.90 |
| 84 | `conversation.status` | quoted |  | msg_9328429a042b |  |  |  |
| 85 | `trace.span` | ok | 604 ms | msg_9328429a042b |  |  | nó quote |
| 86 | `trace.span` | ok | 0 ms | msg_9328429a042b |  |  | nó route_quote |
| 87 | `trace.span` | ok | 0 ms | msg_9328429a042b |  |  | nó present |
| 88 | `message.sent` | sent |  | msg_9328429a042b |  |  |  |
| 89 | `trace.span` | ok | 0 ms | msg_9328429a042b |  |  | nó deliver |
| 90 | `message.received` | processed |  | msg_9328429a042b |  |  |  |
| 91 | `turn.finished` | quoted | 2073 ms | msg_9328429a042b |  |  |  |
| 92 | `message.received` | received |  | msg_b867b012d0e7 |  |  | PII mascarada: nenhum |
| 93 | `trace.span` | ok | 0 ms | msg_b867b012d0e7 |  |  | nó ingest |
| 94 | `llm.call` | none | 1658 ms | msg_b867b012d0e7 |  |  | claude-haiku-5-5 · extract_v3 · 212 in / 89 out / 3558 cache · US$ 0.000101 |
| 95 | `trace.span` | ok | 1658 ms | msg_b867b012d0e7 |  |  | nó extract |
| 96 | `trace.span` | ok | 0 ms | msg_b867b012d0e7 |  |  | nó apply |
| 97 | `trace.span` | ok | 0 ms | msg_b867b012d0e7 |  |  | nó route |
| 98 | `handoff.opened` | opened |  | msg_b867b012d0e7 |  |  | regra ready_to_close · prioridade fim_feliz |
| 99 | `conversation.status` | handed_off |  | msg_b867b012d0e7 |  |  |  |
| 100 | `trace.span` | ok | 0 ms | msg_b867b012d0e7 |  |  | nó handoff |
| 101 | `message.sent` | sent |  | msg_b867b012d0e7 |  |  |  |
| 102 | `trace.span` | ok | 0 ms | msg_b867b012d0e7 |  |  | nó deliver |
| 103 | `message.received` | processed |  | msg_b867b012d0e7 |  |  |  |
| 104 | `turn.finished` | handed_off | 1663 ms | msg_b867b012d0e7 |  |  |  |
