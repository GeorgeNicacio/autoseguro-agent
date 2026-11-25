# O que o dataset mudou no agente (T1.3)

Números de [`dataset_report.md`](dataset_report.md) (gerado por `analysis/dataset_report.py`,
só agregados). Cada achado vira uma decisão rastreável.

| # | Achado | Decisão no agente | Onde |
|---|---|---|---|
| D1 | O desfecho é sorteado de forma independente de tudo (desfechos com métricas iguais; confirmado no gerador) | Nenhuma regra é justificada por "aumenta conversão". Regras vêm da política comercial e do `/planos` | README, DECISIONS |
| D2 | **56,8%** das conversas têm mídia (31% documento, 22% foto, 18,6% áudio), quase sempre CNH ou foto do carro, que não são necessárias para cotar | **Mídia não gera handoff na hora.** O agente avisa que não precisa do arquivo agora e segue pedindo o dado por texto. Handoff `media_unsupported` só se o lead responder com mídia 2× ao mesmo dado pendente. Sem isso, mais da metade dos leads iria para humano | `02-design.md` §5 regra 9 · G07 |
| D3 | **30,0%** dos leads cairiam em recusa (11,2% com mais de 75 anos; 21,2% com carro de mais de 20 anos) | Validação local antes de chamar o `/quote` economiza ~30% das chamadas e dos retries; `out_of_policy` vai ser a regra de handoff mais frequente | REQ-10/11 · SMART M-12, P-03 |
| D4 | Vendedor pediu CPF em **100%** das conversas, mas o `/quote` não usa CPF | Minimização: o agente nunca pede CPF; se vier, mascara e avisa que não precisa | REQ-03 · G09 |
| D5 | PII em todas as conversas: CPF e CEP em 100%, e-mail e telefone em 55,2%, placa em 33,6% | Mascarador é obrigatório no caminho de toda mensagem; contagens servem de referência para o recall do `pii.py` | REQ-50 · SMART M-10 |
| D6 | No dataset os formatos são uniformes (CPF sempre pontuado, telefone `+55 DD 9XXXX-XXXX`, placa 100% Mercosul) | Os testes do `pii.py` **não** podem se limitar ao dataset: cobrem CPF sem pontuação, telefone sem +55/DDD, placa antiga | T1.7 |
| D7 | Objeções: concorrente 26,1%, "vou pensar" 17,6%, preço caro 17,2%, franquia 9,0% | Concorrente/desconto → `price_negotiation`; franquia → explicar com `/planos` e oferecer plano com franquia menor; "vou pensar" → resumo e oferta de retomar, **sem** handoff | `02-design.md` §5 · G08, G17, G18 |
| D8 | CEP de alto risco em **35,8%** dos leads | Cenário G05 é comum, não exceção; template mostra que o valor veio da API sem explicar o agravo | G05 |
| D9 | Uso comercial (Uber, aplicativo): **0** menções | `commercial_use` continua como regra (política), testado com cenário sintético G14 | G14 |
| D10 | 100% das conversas têm preço escrito pelo vendedor, fora da fórmula do `/quote` | Few-shot de tom nunca inclui trechos com R$ | SPARK §K |
| D11 | Timestamps voltam no tempo em 99,8% das conversas | Ordenar sempre por `message_index`; métricas de tempo do dataset não são usadas | `analysis/` |
| D12 | 18–24 anos (×1,60) são 9,4%; 60–75 (×1,40) são 26,2% | Golden set cobre as duas faixas com agravo (G02 e nova G19 com 65 anos) | G02, G19 |
