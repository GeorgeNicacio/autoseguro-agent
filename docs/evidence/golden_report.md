# Golden set (T3.1 · SMART M-05)

Gerado por `python -m autoseguro_agent.evaluation.golden` · LLM: FakeLLM · quote-service real sem falha simulada (G10 e G11 com falha injetada).

**24 de 24 cenários passaram.**

| # | Cenário | Esperado | Obtido | Resultado |
|---|---|---|---|---|
| G01 | Caminho feliz, um dado por vez | quoted · R$ 209,90 | quoted · R$ 209,90 | passou |
| G02 | Condutor de 22 anos (×1,60) | quoted · R$ 335,84 | quoted · R$ 335,84 | passou |
| G03 | Carro 2003: recusa local, sem chamar a API | handed_off · out_of_policy | handed_off · out_of_policy | passou |
| G04 | Condutor de 80 anos: recusa local | handed_off · out_of_policy | handed_off · out_of_policy | passou |
| G05 | CEP de alto risco (×1,30) | quoted · R$ 272,87 | quoted · R$ 272,87 | passou |
| G06 | Pede atendente no meio | handed_off · explicit_request | handed_off · explicit_request | passou |
| G07 | Manda foto e depois responde por texto | quoted | quoted · R$ 209,90 | passou |
| G07b | Responde com áudio duas vezes | handed_off · media_unsupported | handed_off · media_unsupported | passou |
| G08 | Pede desconto depois da cotação | handed_off · price_negotiation | handed_off · price_negotiation · R$ 209,90 | passou |
| G09 | Manda CPF sem ser pedido | quoted | quoted · R$ 209,90 | passou |
| G10 | API fora do ar | handed_off · infra_unavailable | handed_off · infra_unavailable | passou |
| G11 | API lenta duas vezes e depois responde | quoted · R$ 209,90 | quoted · R$ 209,90 | passou |
| G12 | CEP incompleto e depois sem resposta | handed_off · stuck | handed_off · stuck | passou |
| G13 | Sinistro | handed_off · out_of_scope | handed_off · out_of_scope | passou |
| G14 | Uso comercial (Uber) | handed_off · out_of_scope | handed_off · out_of_scope | passou |
| G15 | Cotou e quer fechar | handed_off · ready_to_close | handed_off · ready_to_close · R$ 209,90 | passou |
| G16 | Não sabe o plano (carro 2012) | quoted | quoted · R$ 173,85 | passou |
| G17 | Acha a franquia alta | quoted | quoted · R$ 209,90 | passou |
| G18 | Vou pensar | quoted | quoted · R$ 209,90 | passou |
| G19 | Condutor de 65 anos (×1,40) | quoted · R$ 293,86 | quoted · R$ 293,86 | passou |
| G20 | Jornada completa: recomendação, aceite curto e mensagem depois do handoff | handed_off · ready_to_close | handed_off · ready_to_close · R$ 173,85 | passou |
| G21 | Aceite curto ('sim') depois da cotação | handed_off · ready_to_close · R$ 209,90 | handed_off · ready_to_close · R$ 209,90 | passou |
| G22 | Muda a data de início: recota com pro-rata | quoted · R$ 209,90 | quoted · R$ 209,90 | passou |
| G23 | Compara com o Premium e aceita | handed_off · ready_to_close · R$ 339,90 | handed_off · ready_to_close · R$ 339,90 | passou |
