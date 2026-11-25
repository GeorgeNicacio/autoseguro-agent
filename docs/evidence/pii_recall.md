# Recall do mascarador no dataset (SMART M-10)

Gerado por `analysis/pii_recall.py` em 2026-11-25 com o `pii.py` do agente. Só contagens.

Mensagens de texto de leads: 14681
| Tipo | Referência | Mascarados pelo agente | Recall |
|---|---|---|---|
| CPF | 2500 | 2500 | 100.0% |
| EMAIL | 1379 | 1379 | 100.0% |
| TEL | 1379 | 1379 | 100.0% |
| PLACA | 839 | 839 | 100.0% |
| CEP | 2500 | 2500 | 100.0% |

Mensagens com PII crua depois do mascaramento: 0
Idades preservadas (não confundidas com PII): 2500/2500

Ressalva (achado D6): o dataset só tem um formato por tipo; os formatos alternativos (CPF sem pontuação, telefone sem DDD, placa antiga) estão cobertos em `tests/unit/test_pii.py`.
