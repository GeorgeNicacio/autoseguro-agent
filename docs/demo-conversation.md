# Log de uma execução completa (entregável 4)

Gerado por `python -m autoseguro_agent.evaluation.demo` em 25/11/2026 14:28 · LLM: FakeLLM (sem chave) · quote-service real com instabilidade padrão e `QUOTE_SEED=4` · regras de `/planos` vindas da api.

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
- Handoff: `ready_to_close` (`ho_msg_ef0ee17fae45`)
- Perfil guardado (mascarado): `{'idade': 35, 'veiculo_ano': 2022, 'veiculo_modelo': 'Onix', 'cep_token': '<CEP_1>', 'plano_id': 'premium', 'data_inicio': None}`

## Linha do tempo de eventos

Mesma linha do tempo que `GET /conversations/{id}` devolve e que vai para o log JSON.

| # | Evento | Status | Latência | message_id | quote_request_id | quote_attempt_id | Detalhe |
|---|---|---|---|---|---|---|---|
| 1 | `message.received` | received |  | msg_4ae0f82c4fab |  |  | PII mascarada: nenhum |
| 2 | `message.sent` | sent |  | msg_4ae0f82c4fab |  |  |  |
| 3 | `message.sent` | sent |  | msg_4ae0f82c4fab |  |  |  |
| 4 | `message.received` | processed |  | msg_4ae0f82c4fab |  |  |  |
| 5 | `message.received` | received |  | msg_e10bda461428 |  |  | PII mascarada: nenhum |
| 6 | `slot.updated` | ok |  | msg_e10bda461428 |  |  | veiculo_ano = 2022 |
| 7 | `slot.updated` | ok |  | msg_e10bda461428 |  |  | veiculo_modelo = Onix |
| 8 | `message.sent` | sent |  | msg_e10bda461428 |  |  |  |
| 9 | `message.received` | processed |  | msg_e10bda461428 |  |  |  |
| 10 | `message.received` | received |  | msg_7b5d06f6a6bd |  |  | PII mascarada: nenhum |
| 11 | `slot.updated` | ok |  | msg_7b5d06f6a6bd |  |  | idade = 35 |
| 12 | `message.sent` | sent |  | msg_7b5d06f6a6bd |  |  |  |
| 13 | `message.received` | processed |  | msg_7b5d06f6a6bd |  |  |  |
| 14 | `message.received` | received |  | msg_83b73b47d3ef |  |  | PII mascarada: CPF, CEP |
| 15 | `slot.updated` | ok |  | msg_83b73b47d3ef |  |  | cep_token = 01310-*** |
| 16 | `message.sent` | sent |  | msg_83b73b47d3ef |  |  |  |
| 17 | `message.sent` | sent |  | msg_83b73b47d3ef |  |  |  |
| 18 | `message.received` | processed |  | msg_83b73b47d3ef |  |  |  |
| 19 | `message.received` | received |  | msg_01a0d79e66b4 |  |  | PII mascarada: nenhum |
| 20 | `slot.updated` | ok |  | msg_01a0d79e66b4 |  |  | plano_id = completo |
| 21 | `message.sent` | sent |  | msg_01a0d79e66b4 |  |  | mensagem de espera |
| 22 | `quote_request.started` | pending |  | msg_01a0d79e66b4 | qr_6a624f6b7d4e |  | completo · início 2026-12-01 |
| 23 | `quote_attempt` | timeout | 3006 ms | msg_01a0d79e66b4 | qr_6a624f6b7d4e | qa_8cc86f0f6509 | tentativa 1 · http — |
| 24 | `quote_attempt` | http_5xx | 4 ms | msg_01a0d79e66b4 | qr_6a624f6b7d4e | qa_60a0a77ef3cd | tentativa 2 · http 502 |
| 25 | `quote_attempt` | ok | 44 ms | msg_01a0d79e66b4 | qr_6a624f6b7d4e | qa_aa60db48342b | tentativa 3 · http 200 |
| 26 | `quote_request.finished` | success | 4816 ms | msg_01a0d79e66b4 | qr_6a624f6b7d4e |  | 3 tentativa(s) 209.90 |
| 27 | `conversation.status` | quoted |  | msg_01a0d79e66b4 |  |  |  |
| 28 | `message.sent` | sent |  | msg_01a0d79e66b4 |  |  |  |
| 29 | `message.sent` | sent |  | msg_01a0d79e66b4 |  |  |  |
| 30 | `message.received` | processed |  | msg_01a0d79e66b4 |  |  |  |
| 31 | `message.received` | received |  | msg_131401f3119f |  |  | PII mascarada: nenhum |
| 32 | `slot.updated` | ok |  | msg_131401f3119f |  |  | plano_id = premium |
| 33 | `quote_request.started` | pending |  | msg_131401f3119f | qr_f9dbf4b24a01 |  | premium · início 2026-12-01 |
| 34 | `quote_attempt` | http_5xx | 45 ms | msg_131401f3119f | qr_f9dbf4b24a01 | qa_b3b41b756a2f | tentativa 1 · http 500 |
| 35 | `quote_attempt` | ok | 44 ms | msg_131401f3119f | qr_f9dbf4b24a01 | qa_5fba7ca67f63 | tentativa 2 · http 200 |
| 36 | `quote_request.finished` | success | 814 ms | msg_131401f3119f | qr_f9dbf4b24a01 |  | 2 tentativa(s) 339.90 |
| 37 | `conversation.status` | quoted |  | msg_131401f3119f |  |  |  |
| 38 | `message.sent` | sent |  | msg_131401f3119f |  |  |  |
| 39 | `message.received` | processed |  | msg_131401f3119f |  |  |  |
| 40 | `message.received` | received |  | msg_ef0ee17fae45 |  |  | PII mascarada: nenhum |
| 41 | `handoff.opened` | opened |  | msg_ef0ee17fae45 |  |  | regra ready_to_close · prioridade fim_feliz |
| 42 | `conversation.status` | handed_off |  | msg_ef0ee17fae45 |  |  |  |
| 43 | `message.sent` | sent |  | msg_ef0ee17fae45 |  |  |  |
| 44 | `message.received` | processed |  | msg_ef0ee17fae45 |  |  |  |
