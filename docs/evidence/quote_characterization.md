# Caracterização do `POST /quote` (T1.2 · SMART M-01)

Medido em 2026-11-25 com `py scripts/characterize_quote.py --n 200` contra o
`docker compose` padrão (`QUOTE_FAILURE_RATE=0.20`, `QUOTE_SLOW_RATE=0.10`, sem seed),
10 chamadas em paralelo, timeout de cliente de 15 s (longo de propósito, para medir a
lentidão inteira). Dados brutos: [`quote_characterization.json`](quote_characterization.json).

| Medida | Valor |
|---|---|
| Respostas 200 | 159 / 200 |
| Falhas 5xx (500 / 502 / 503) | 41 (11 / 14 / 16) → **20,5%** |
| Respostas lentas (200 após ~8 s) | 16 → **8,0%** |
| Sucesso rápido na 1ª tentativa (< 3 s) | **71,5%** |
| Latência das 200 rápidas | p50 6,5 ms · p95 127 ms · média 17 ms |
| Latência das lentas | ≥ 8,002 s (o `sleep(8)` do serviço) |

## O que isso decide

1. **Timeout de 3 s é seguro:** fica ~23× acima do p95 das respostas normais e corta a lentidão de 8 s com folga. Sem timeout, 8% das conversas travariam 8 s.
2. **Retry paga:** com 28,5% de chance de uma tentativa falhar ou ficar lenta, e tentativas independentes, a chance de sucesso é de **~91,9% com 2 tentativas** e **~97,7% com 3**. Por isso escolhemos 3 tentativas (meta SMART M-08 ≥ 97%).
3. **Orçamento de 12 s cabe:** o pior caso é 3 timeouts (9 s) + backoff (~0,5 s + ~1 s) ≈ 10,5 s.
4. **Mensagem de espera:** com 3 s de timeout, só passamos de 4 s quando a 1ª tentativa falha, ou seja, em ~28% das cotações o lead veria a mensagem de espera.
5. **Confere com a configuração:** a taxa medida (20,5% / 8%) bate com a configuração (20% / 10%), então o teste de caos pode confiar nas variáveis de ambiente para simular cenários piores.
