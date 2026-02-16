import argparse
import json
from pathlib import Path
from typing import Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check simple SLOs from Day3 request logs.")
    parser.add_argument(
        "--log_path",
        default="../day3/logs/rag_requests.jsonl",
        help="Path to day3 request log file",
    )
    parser.add_argument("--max_error_rate", type=float, default=0.02, help="Maximum allowed error rate")
    parser.add_argument("--max_p95_ms", type=float, default=3000.0, help="Maximum allowed P95 latency (ms)")
    parser.add_argument(
        "--ask_only",
        action="store_true",
        help="Only include /ask requests when evaluating SLOs",
    )
    return parser.parse_args()


def read_logs(path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def percentile(sorted_values: List[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if p <= 0:
        return sorted_values[0]
    if p >= 100:
        return sorted_values[-1]
    rank = (len(sorted_values) - 1) * (p / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


def main() -> None:
    args = parse_args()
    log_path = Path(args.log_path)
    if not log_path.exists():
        raise SystemExit(f"Log file not found: {log_path}")

    rows = read_logs(log_path)
    if args.ask_only:
        rows = [r for r in rows if str(r.get("endpoint", "")) == "/ask"]

    if not rows:
        raise SystemExit("No log rows available for SLO check")

    latencies = sorted(to_float(r.get("latency_ms")) for r in rows)
    total = len(rows)
    error_count = sum(1 for r in rows if to_int(r.get("status_code")) >= 400)
    error_rate = error_count / total
    p95_ms = percentile(latencies, 95)

    pass_error = error_rate <= args.max_error_rate
    pass_latency = p95_ms <= args.max_p95_ms
    passed = pass_error and pass_latency

    print("=== Day6 SLO Check ===")
    print(f"Rows checked : {total}")
    print(f"Error rate   : {error_rate:.2%} (threshold <= {args.max_error_rate:.2%})")
    print(f"P95 latency  : {p95_ms:.2f} ms (threshold <= {args.max_p95_ms:.2f} ms)")
    print(f"SLO result   : {'PASS' if passed else 'FAIL'}")

    if not pass_error:
        print("- Error-rate SLO failed")
    if not pass_latency:
        print("- Latency SLO failed")

    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
