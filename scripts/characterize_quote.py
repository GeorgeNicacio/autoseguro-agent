"""Caracterização do POST /quote (tarefa T1.2, métrica SMART M-01).

Faz N chamadas com um payload válido e mede, com timeout de cliente LONGO (para
ver a lentidão real, não cortá-la): distribuição de status, taxa de falha 5xx,
taxa de respostas lentas e latências p50/p95/máx.

Só usa a biblioteca padrão, para rodar antes do scaffold do agente:

    py scripts/characterize_quote.py --n 200 --out docs/evidence/quote_characterization.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

PAYLOAD = {
    "plano_id": "completo",
    "idade": 35,
    "veiculo_ano": 2022,
    "cep": "01310-100",
    "data_inicio": "2026-12-15",
}
SLOW_THRESHOLD_S = 5.0  # a lentidão simulada é de 8 s; respostas normais levam ms


def call(url: str, timeout_s: float) -> dict:
    body = json.dumps(PAYLOAD).encode()
    req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = resp.status
            resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
    except TimeoutError:
        status = "client_timeout"
    return {"status": status, "latency_s": time.perf_counter() - t0}


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))
    return ordered[k]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/quote")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda _: call(args.url, args.timeout), range(args.n)))
    wall_s = time.perf_counter() - started

    statuses = Counter(str(r["status"]) for r in results)
    ok = [r for r in results if r["status"] == 200]
    slow = [r for r in ok if r["latency_s"] >= SLOW_THRESHOLD_S]
    fast_ok = [r["latency_s"] for r in ok if r["latency_s"] < SLOW_THRESHOLD_S]
    all_lat = [r["latency_s"] for r in results]
    errors_5xx = sum(v for k, v in statuses.items() if k.startswith("5"))

    summary = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n": args.n,
        "concurrency": args.concurrency,
        "client_timeout_s": args.timeout,
        "status_counts": dict(sorted(statuses.items())),
        "failure_rate_5xx": round(errors_5xx / args.n, 4),
        "slow_rate": round(len(slow) / args.n, 4),
        "success_rate_first_try_under_3s": round(sum(1 for r in ok if r["latency_s"] < 3) / args.n, 4),
        "latency_all_s": {
            "p50": round(pct(all_lat, 50), 3),
            "p95": round(pct(all_lat, 95), 3),
            "max": round(max(all_lat), 3),
        },
        "latency_fast_200_ms": {
            "p50": round(pct(fast_ok, 50) * 1000, 1),
            "p95": round(pct(fast_ok, 95) * 1000, 1),
            "mean": round(statistics.fmean(fast_ok) * 1000, 1) if fast_ok else None,
        },
        "slow_200_latency_s_min": round(min((r["latency_s"] for r in slow), default=0.0), 3),
        "wall_time_s": round(wall_s, 1),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
            f.write("\n")


if __name__ == "__main__":
    main()
