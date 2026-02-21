import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Set

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate day8 agent tool-calling behavior.")
    parser.add_argument("--base_url", default="http://127.0.0.1:8002", help="Agent API base url")
    parser.add_argument("--dataset", default="eval_dataset.csv", help="Evaluation dataset CSV")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout sec")
    parser.add_argument("--output_dir", default="reports", help="Output directory")
    return parser.parse_args()


def read_dataset(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_tools(text: str) -> Set[str]:
    if not text:
        return set()
    return {item.strip() for item in text.split("|") if item.strip()}


def split_keywords(text: str) -> List[str]:
    if not text:
        return []
    return [item.strip() for item in text.split(";") if item.strip()]


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")
    rows = read_dataset(dataset_path)
    if not rows:
        raise SystemExit("Dataset is empty")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_path = out_dir / f"tool_eval_detail_{run_id}.csv"
    summary_path = out_dir / f"tool_eval_summary_{run_id}.json"

    total = 0
    ok_http = 0
    tool_match_count = 0
    keyword_hit_count = 0
    latency_sum = 0.0

    detail_rows: List[Dict[str, Any]] = []

    with httpx.Client(timeout=args.timeout) as client:
        for row in rows:
            total += 1
            qid = str(row.get("id", "")).strip()
            query = str(row.get("query", "")).strip()
            expected_tools = split_tools(str(row.get("expected_tools", "")))
            expected_keywords = split_keywords(str(row.get("expected_keywords", "")))

            status = 0
            payload: Dict[str, Any] = {}
            error = ""
            start = perf_counter()
            try:
                resp = client.post(f"{args.base_url}/agent", json={"query": query, "max_steps": 4})
                status = resp.status_code
                if status == 200:
                    payload = resp.json()
                    ok_http += 1
                else:
                    error = resp.text[:300]
            except Exception as exc:
                error = str(exc)
            latency_ms = (perf_counter() - start) * 1000
            latency_sum += latency_ms

            used_tools = set(payload.get("used_tools", [])) if status == 200 else set()
            tool_match = expected_tools.issubset(used_tools) if expected_tools else False
            if tool_match:
                tool_match_count += 1

            final_answer = str(payload.get("final_answer", ""))
            keyword_hit = any(kw in final_answer for kw in expected_keywords) if expected_keywords else False
            if keyword_hit:
                keyword_hit_count += 1

            detail_rows.append(
                {
                    "id": qid,
                    "query": query,
                    "expected_tools": "|".join(sorted(expected_tools)),
                    "used_tools": "|".join(sorted(used_tools)),
                    "tool_match": int(tool_match),
                    "keyword_hit": int(keyword_hit),
                    "http_status": status,
                    "latency_ms": round(latency_ms, 3),
                    "final_answer": final_answer[:220].replace("\n", " "),
                    "error": error,
                }
            )

    with detail_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
        writer.writeheader()
        writer.writerows(detail_rows)

    summary = {
        "created_at": datetime.now().isoformat(),
        "base_url": args.base_url,
        "dataset": str(dataset_path),
        "total": total,
        "http_success_rate": round((ok_http / total) if total else 0.0, 4),
        "tool_match_rate": round((tool_match_count / total) if total else 0.0, 4),
        "keyword_hit_rate": round((keyword_hit_count / total) if total else 0.0, 4),
        "avg_latency_ms": round((latency_sum / total) if total else 0.0, 3),
        "detail_csv": str(detail_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== Day8 Tool Eval Complete ===")
    print(f"HTTP success rate : {summary['http_success_rate']:.1%}")
    print(f"Tool match rate   : {summary['tool_match_rate']:.1%}")
    print(f"Keyword hit rate  : {summary['keyword_hit_rate']:.1%}")
    print(f"Avg latency (ms)  : {summary['avg_latency_ms']}")
    print(f"Summary JSON      : {summary_path}")
    print(f"Detail CSV        : {detail_path}")


if __name__ == "__main__":
    main()
