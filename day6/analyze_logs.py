import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Day3 RAG request logs.")
    parser.add_argument(
        "--log_path",
        default="../day3/logs/rag_requests.jsonl",
        help="Path to day3 request log file",
    )
    parser.add_argument(
        "--output",
        default="reports/log_report.md",
        help="Output markdown report path",
    )
    parser.add_argument("--top_n", type=int, default=5, help="Top N rows for rankings")
    return parser.parse_args()


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


def render_report(rows: List[Dict[str, object]], top_n: int) -> str:
    total = len(rows)
    if total == 0:
        return "# Day6 Log Report\n\nNo valid log entries found.\n"

    endpoint_counter: Counter[str] = Counter()
    provider_counter: Counter[str] = Counter()
    query_counter: Counter[str] = Counter()
    doc_counter: Counter[str] = Counter()

    latencies: List[float] = []
    error_rows: List[Dict[str, object]] = []
    timestamps: List[datetime] = []

    for row in rows:
        endpoint = str(row.get("endpoint", ""))
        provider = str(row.get("provider", ""))
        query = str(row.get("query", "")).strip()
        status_code = to_int(row.get("status_code"))
        latency_ms = to_float(row.get("latency_ms"))
        docs = row.get("source_docs", [])
        ts = str(row.get("ts", ""))

        if endpoint:
            endpoint_counter[endpoint] += 1
        if provider:
            provider_counter[provider] += 1
        if query:
            query_counter[query] += 1
        if isinstance(docs, list):
            for d in docs:
                if d:
                    doc_counter[str(d)] += 1

        latencies.append(latency_ms)
        if status_code >= 400:
            error_rows.append(row)

        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
            except ValueError:
                pass

    latencies_sorted = sorted(latencies)
    error_rate = len(error_rows) / total
    avg_latency = sum(latencies_sorted) / total
    p50 = percentile(latencies_sorted, 50)
    p95 = percentile(latencies_sorted, 95)

    slowest = sorted(rows, key=lambda r: to_float(r.get("latency_ms")), reverse=True)[:top_n]

    lines: List[str] = []
    lines.append("# Day6 Log Report")
    lines.append("")
    if timestamps:
        lines.append(f"- Time range: `{min(timestamps).isoformat()}` ~ `{max(timestamps).isoformat()}`")
    lines.append(f"- Total requests: **{total}**")
    lines.append(f"- Error requests: **{len(error_rows)}** ({error_rate:.1%})")
    lines.append(f"- Avg latency: **{avg_latency:.2f} ms**")
    lines.append(f"- P50 latency: **{p50:.2f} ms**")
    lines.append(f"- P95 latency: **{p95:.2f} ms**")
    lines.append("")

    lines.append("## Endpoint Distribution")
    lines.append("")
    lines.append("| endpoint | count |")
    lines.append("|---|---:|")
    for endpoint, count in endpoint_counter.most_common():
        lines.append(f"| {endpoint} | {count} |")
    lines.append("")

    lines.append("## Provider Distribution")
    lines.append("")
    lines.append("| provider | count |")
    lines.append("|---|---:|")
    for provider, count in provider_counter.most_common():
        lines.append(f"| {provider} | {count} |")
    lines.append("")

    lines.append(f"## Top {top_n} Queries")
    lines.append("")
    lines.append("| query | count |")
    lines.append("|---|---:|")
    for query, count in query_counter.most_common(top_n):
        lines.append(f"| {query} | {count} |")
    lines.append("")

    lines.append(f"## Top {top_n} Source Docs")
    lines.append("")
    lines.append("| doc_name | count |")
    lines.append("|---|---:|")
    for doc, count in doc_counter.most_common(top_n):
        lines.append(f"| {doc} | {count} |")
    lines.append("")

    lines.append(f"## Top {top_n} Slow Requests")
    lines.append("")
    lines.append("| ts | endpoint | status | latency_ms | query |")
    lines.append("|---|---|---:|---:|---|")
    for row in slowest:
        lines.append(
            "| {ts} | {endpoint} | {status} | {latency} | {query} |".format(
                ts=str(row.get("ts", "")),
                endpoint=str(row.get("endpoint", "")),
                status=to_int(row.get("status_code")),
                latency=f"{to_float(row.get('latency_ms')):.2f}",
                query=str(row.get("query", "")),
            )
        )
    lines.append("")

    if error_rows:
        lines.append(f"## Error Samples (Top {top_n})")
        lines.append("")
        lines.append("| ts | endpoint | status | error | query |")
        lines.append("|---|---|---:|---|---|")
        for row in error_rows[:top_n]:
            lines.append(
                "| {ts} | {endpoint} | {status} | {error} | {query} |".format(
                    ts=str(row.get("ts", "")),
                    endpoint=str(row.get("endpoint", "")),
                    status=to_int(row.get("status_code")),
                    error=str(row.get("error", "")).replace("|", "/"),
                    query=str(row.get("query", "")),
                )
            )
        lines.append("")

    lines.append("## Suggestions")
    lines.append("")
    lines.append("- If P95 is high, inspect slow query patterns and source document lengths.")
    lines.append("- If error rate is non-zero, triage by endpoint and error message frequency.")
    lines.append("- Use this report with Day4/Day5 metrics to decide optimization priority.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    log_path = Path(args.log_path)
    if not log_path.exists():
        raise SystemExit(f"Log file not found: {log_path}")

    rows = read_logs(log_path)
    report = render_report(rows, args.top_n)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print("=== Day6 Log Analysis Complete ===")
    print(f"Input log : {log_path}")
    print(f"Entries   : {len(rows)}")
    print(f"Report    : {output_path}")


if __name__ == "__main__":
    main()
