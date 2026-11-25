# Log de uma execução completa (entregável 4)

Gerado por `python -m autoseguro_agent.evaluation.demo` em 25/11/2026 14:56 · LLM: claude-opus-5-5 · quote-service real com instabilidade padrão e `QUOTE_SEED=4` · regras de `/planos` vindas da api.

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
- Handoff: `ready_to_close` (`ho_msg_a09950ef98ea`)
- Perfil guardado (mascarado): `{'idade': 35, 'veiculo_ano': 2022, 'veiculo_modelo': 'Onix', 'cep_token': '<CEP_1>', 'plano_id': 'premium', 'data_inicio': None}`

## Linha do tempo de eventos

Mesma linha do tempo que `GET /conversations/{id}` devolve e que vai para o log JSON.

| # | Evento | Status | Latência | message_id | quote_request_id | quote_attempt_id | Detalhe |
|---|---|---|---|---|---|---|---|
| 1 | `message.received` | received |  | msg_354adee44cc6 |  |  | PII mascarada: nenhum |
| 2 | `message.sent` | sent |  | msg_354adee44cc6 |  |  |  |
| 3 | `message.sent` | sent |  | msg_354adee44cc6 |  |  |  |
| 4 | `message.received` | processed |  | msg_354adee44cc6 |  |  |  |
| 5 | `message.received` | received |  | msg_305fd8cb452a |  |  | PII mascarada: nenhum |
| 6 | `slot.updated` | ok |  | msg_305fd8cb452a |  |  | veiculo_ano = 2022 |
| 7 | `slot.updated` | ok |  | msg_305fd8cb452a |  |  | veiculo_modelo = Onix |
| 8 | `message.sent` | sent |  | msg_305fd8cb452a |  |  |  |
| 9 | `message.received` | processed |  | msg_305fd8cb452a |  |  |  |
| 10 | `message.received` | received |  | msg_f8a210a57224 |  |  | PII mascarada: nenhum |
| 11 | `slot.updated` | ok |  | msg_f8a210a57224 |  |  | idade = 35 |
| 12 | `message.sent` | sent |  | msg_f8a210a57224 |  |  |  |
| 13 | `message.received` | processed |  | msg_f8a210a57224 |  |  |  |
| 14 | `message.received` | received |  | msg_a1bb87dca3d0 |  |  | PII mascarada: CPF, CEP |
| 15 | `slot.updated` | ok |  | msg_a1bb87dca3d0 |  |  | cep_token = 01310-*** |
| 16 | `message.sent` | sent |  | msg_a1bb87dca3d0 |  |  |  |
| 17 | `message.sent` | sent |  | msg_a1bb87dca3d0 |  |  |  |
| 18 | `message.received` | processed |  | msg_a1bb87dca3d0 |  |  |  |
| 19 | `message.received` | received |  | msg_0841eafe0e8c |  |  | PII mascarada: nenhum |
| 20 | `slot.updated` | ok |  | msg_0841eafe0e8c |  |  | plano_id = completo |
| 21 | `message.sent` | sent |  | msg_0841eafe0e8c |  |  | mensagem de espera |
| 22 | `quote_request.started` | pending |  | msg_0841eafe0e8c | qr_efade1dc84d2 |  | completo · início 2026-12-01 |
| 23 | `quote_attempt` | timeout | 3007 ms | msg_0841eafe0e8c | qr_efade1dc84d2 | qa_e5f332e9a5f3 | tentativa 1 · http — |
| 24 | `quote_attempt` | http_5xx | 4 ms | msg_0841eafe0e8c | qr_efade1dc84d2 | qa_3b42cb6bf540 | tentativa 2 · http 502 |
| 25 | `quote_attempt` | ok | 46 ms | msg_0841eafe0e8c | qr_efade1dc84d2 | qa_9fcd315c1ff4 | tentativa 3 · http 200 |
| 26 | `quote_request.finished` | success | 4834 ms | msg_0841eafe0e8c | qr_efade1dc84d2 |  | 3 tentativa(s) 209.90 |
| 27 | `conversation.status` | quoted |  | msg_0841eafe0e8c |  |  |  |
| 28 | `message.sent` | sent |  | msg_0841eafe0e8c |  |  |  |
| 29 | `message.sent` | sent |  | msg_0841eafe0e8c |  |  |  |
| 30 | `message.received` | processed |  | msg_0841eafe0e8c |  |  |  |
| 31 | `message.received` | received |  | msg_dd1cb38f6490 |  |  | PII mascarada: nenhum |
| 32 | `slot.updated` | ok |  | msg_dd1cb38f6490 |  |  | plano_id = premium |
| 33 | `quote_request.started` | pending |  | msg_dd1cb38f6490 | qr_e28fb9908779 |  | premium · início 2026-12-01 |
| 34 | `quote_attempt` | http_5xx | 42 ms | msg_dd1cb38f6490 | qr_e28fb9908779 | qa_6aed4ee1a0dc | tentativa 1 · http 500 |
| 35 | `quote_attempt` | ok | 42 ms | msg_dd1cb38f6490 | qr_e28fb9908779 | qa_64bd86fb1a0e | tentativa 2 · http 200 |
| 36 | `quote_request.finished` | success | 610 ms | msg_dd1cb38f6490 | qr_e28fb9908779 |  | 2 tentativa(s) 339.90 |
| 37 | `conversation.status` | quoted |  | msg_dd1cb38f6490 |  |  |  |
| 38 | `message.sent` | sent |  | msg_dd1cb38f6490 |  |  |  |
| 39 | `message.received` | processed |  | msg_dd1cb38f6490 |  |  |  |
| 40 | `message.received` | received |  | msg_a09950ef98ea |  |  | PII mascarada: nenhum |
| 41 | `handoff.opened` | opened |  | msg_a09950ef98ea |  |  | regra ready_to_close · prioridade fim_feliz |
| 42 | `conversation.status` | handed_off |  | msg_a09950ef98ea |  |  |  |
| 43 | `message.sent` | sent |  | msg_a09950ef98ea |  |  |  |
| 44 | `message.received` | processed |  | msg_a09950ef98ea |  |  |  |
