# Análise do dataset de conversas (T1.3)

Gerado por `analysis/dataset_report.py` · ano de referência 2026 · só agregados, nenhuma mensagem crua.

## 1. Volume e desfechos

- 2500 conversas, 26470 mensagens (média 10.6 por conversa).

| Desfecho | Conversas | % |
|---|---|---|
| em_negociacao | 757 | 30.3% |
| ganho | 712 | 28.5% |
| perdido | 538 | 21.5% |
| sem_resposta | 493 | 19.7% |

## 2. Ganho × perdido: existe sinal nos dados?

| Desfecho | 1ª resposta do vendedor (mediana, min) | Mensagens (média) | Mídias (média) |
|---|---|---|---|
| em_negociacao | 5 | 11.3 | 0.77 |
| ganho | 4 | 10.2 | 0.67 |
| perdido | 4 | 11.2 | 0.70 |
| sem_resposta | 4 | 9.3 | 0.71 |

- Conversas com timestamp **voltando no tempo**: 2495 (99.8%). Ordenar por `message_index`, nunca por `timestamp`; por isso o tempo de 1ª resposta acima **não é confiável**.
- **Conclusão honesta:** as métricas por desfecho são praticamente iguais. O gerador (`scripts/generate_dataset.py`) sorteia o desfecho de forma independente do perfil, do carro e das mensagens, então o dataset **não** sustenta regras do tipo "X aumenta conversão". As regras do agente se justificam pela política comercial e pelo `/planos`; o dataset serve para formatos de PII, volume de casos, objeções e cenários de teste.

## 3. Mídia sem transcrição

| Tipo | Mensagens | Conversas com ao menos uma | % das conversas |
|---|---|---|---|
| document | 774 | 774 | 31.0% |
| image | 550 | 550 | 22.0% |
| audio | 465 | 465 | 18.6% |

- Conversas com **qualquer** mídia: 1420 (56.8%).

## 4. Dados pessoais no texto livre (regex de referência)

| Tipo | Ocorrências | Conversas com ao menos uma | % das conversas |
|---|---|---|---|
| cpf | 2500 | 2500 | 100.0% |
| email | 1379 | 1379 | 55.2% |
| telefone | 1379 | 1379 | 55.2% |
| placa | 839 | 839 | 33.6% |
| cep | 2500 | 2500 | 100.0% |

- Conversas em que o **vendedor pediu CPF** para cotar: 2500 (100.0%). O `/quote` não usa CPF: o agente não pede (minimização).
- Placas: 839 no total, 839 no padrão Mercosul (100.0%); o mascarador cobre os dois padrões mesmo assim.

## 5. Perfil dos leads frente às regras do `/quote`

- Condutor acima de 75 anos (recusa): 280 (11.2%).
- Condutor abaixo de 18 anos: 0.
- Veículo com mais de 20 anos em 2026 (recusa): 531 (21.2%).
- **Cairiam em `out_of_policy`** (qualquer recusa): 751 (30.0%). Validação local evita gastar chamada e retry nesses casos.

| Faixa etária do condutor | Multiplicador | Conversas | % |
|---|---|---|---|
| 18–24 | 1,60 | 236 | 9.4% |
| 25–29 | 1,25 | 196 | 7.8% |
| 30–59 | 1,00 | 1133 | 45.3% |
| 60–75 | 1,40 | 655 | 26.2% |
| 76–+ | recusa | 280 | 11.2% |

- CEPs de alto risco (×1,30): 895 de 2500 (35.8%).

## 6. Objeções e pedidos do lead

| Objeção | Conversas | % | Vira |
|---|---|---|---|
| preco_caro | 431 | 17.2% | `price_negotiation` se pedir desconto; senão comparar planos |
| franquia | 226 | 9.0% | explicar franquia do `/planos`; comparar planos |
| concorrente | 652 | 26.1% | `price_negotiation` (cobrir concorrente) |
| vou_pensar | 441 | 17.6% | resumo + oferta de retomar; sem handoff |

- Menções a uso comercial (Uber, aplicativo, entregas): 0. O cenário existe nas regras (`commercial_use`) mas não no dataset: entra no golden set como caso sintético.

## 7. Preço nas conversas históricas

- Conversas com preço escrito pelo vendedor: 2500 (100.0%). Esses valores **não** seguem a fórmula do `/quote` e nunca entram em few-shot (reforça: preço só da API).
