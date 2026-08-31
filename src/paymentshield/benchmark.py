from __future__ import annotations

import argparse
import json
import time

from .api import PaymentInput, decide


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure in-process decision-engine latency without network claims")
    parser.add_argument("--decisions", type=int, default=10000)
    parser.add_argument("--max-p99-ms", type=float, default=10)
    args = parser.parse_args()
    latencies = []
    payload = PaymentInput(transaction_id="benchmark", account_id="a", device_id="d", beneficiary_id="b", amount_usd=125, account_age_days=90, velocity_10m=3, device_novel=False, beneficiary_novel=False, impossible_travel=False, shared_risky_device=False)
    for index in range(args.decisions):
        candidate = payload.model_copy(update={"transaction_id": f"benchmark-{index}"})
        started = time.perf_counter_ns()
        decide(candidate, 0.35, 0.08, "benchmark")
        latencies.append((time.perf_counter_ns() - started) / 1_000_000)
    latencies.sort()
    p99 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.99))]
    result = {"evidence_level": "local-in-process-no-network", "decisions": args.decisions, "p50_ms": round(latencies[len(latencies) // 2], 4), "p95_ms": round(latencies[int(len(latencies) * 0.95)], 4), "p99_ms": round(p99, 4), "passes": p99 <= args.max_p99_ms}
    print(json.dumps(result, indent=2))
    if not result["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
