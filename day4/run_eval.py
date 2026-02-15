import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Day3 RAG API with a CSV dataset.")
    parser.add_argument("--base_url", default="http://127.0.0.1:8001", help="RAG API base url")
    parser.add_argument("--dataset", default="eval_dataset.csv", help="Evaluation dataset CSV path")
    parser.add_argument("--top_k", type=int, default=3, help="Top-k for /search and /ask")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    parser.add_argument("--output_dir", default="results", help="Directory for output CSV")
    parser.add_argument("--skip_ask", action="store_true", help="Only run /search retrieval evaluation")
    return parser.parse_args()


def read_dataset(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_keywords(text: str) -> List[str]:
    if not text:
        return []
    return [item.strip() for item in text.split(";") if item.strip()]


def call_search(client: httpx.Client, base_url: str, query: str, top_k: int) -> Tuple[int, Dict[str, Any]]:
    resp = client.post(f"{base_url}/search", json={"query": query, "top_k": top_k})
    data: Dict[str, Any] = {}
    try:
        data = resp.json()
    except json.JSONDecodeError:
        pass
    return resp.status_code, data


def call_ask(client: httpx.Client, base_url: str, question: str, top_k: int) -> Tuple[int, Dict[str, Any]]:
    resp = client.post(f"{base_url}/ask", json={"question": question, "top_k": top_k})
    data: Dict[str, Any] = {}
    try:
        data = resp.json()
    except json.JSONDecodeError:
        pass
    return resp.status_code, data


def keyword_recall(answer: str, expected_keywords: List[str]) -> float:
    if not expected_keywords:
        return 0.0
    hits = 0
    for kw in expected_keywords:
        if kw in answer:
            hits += 1
    return hits / len(expected_keywords)


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")

    rows = read_dataset(dataset_path)
    if not rows:
        raise SystemExit("Dataset is empty")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"eval_results_{run_id}.csv"

    total = 0
    search_hits = 0
    ask_source_hits = 0
    ask_ok_count = 0
    keyword_recall_sum = 0.0

    result_rows: List[Dict[str, Any]] = []

    with httpx.Client(timeout=args.timeout) as client:
        for row in rows:
            total += 1
            qid = row.get("id", "").strip()
            query = row.get("query", "").strip()
            expected_doc = row.get("expected_doc", "").strip()
            expected_keywords = split_keywords(row.get("expected_keywords", ""))

            search_status, search_data = call_search(client, args.base_url, query, args.top_k)
            search_docs = [
                item.get("doc_name", "")
                for item in search_data.get("hits", [])
                if isinstance(item, dict)
            ]
            search_hit = expected_doc in search_docs
            if search_hit:
                search_hits += 1

            ask_status = -1
            ask_data: Dict[str, Any] = {}
            ask_docs: List[str] = []
            answer = ""
            ask_source_hit = False
            kw_recall = 0.0

            if not args.skip_ask:
                ask_status, ask_data = call_ask(client, args.base_url, query, args.top_k)
                ask_docs = [
                    item.get("doc_name", "")
                    for item in ask_data.get("sources", [])
                    if isinstance(item, dict)
                ]
                answer = str(ask_data.get("answer", ""))
                ask_source_hit = expected_doc in ask_docs
                if ask_source_hit:
                    ask_source_hits += 1

                if ask_status == 200:
                    ask_ok_count += 1
                    kw_recall = keyword_recall(answer, expected_keywords)
                    keyword_recall_sum += kw_recall

            result_rows.append(
                {
                    "id": qid,
                    "query": query,
                    "expected_doc": expected_doc,
                    "search_status": search_status,
                    "search_docs": "|".join(search_docs),
                    "search_hit_expected_doc": int(search_hit),
                    "ask_status": ask_status if not args.skip_ask else "",
                    "ask_source_docs": "|".join(ask_docs) if not args.skip_ask else "",
                    "ask_hit_expected_doc": int(ask_source_hit) if not args.skip_ask else "",
                    "keyword_recall": f"{kw_recall:.3f}" if not args.skip_ask else "",
                    "answer_preview": answer.replace("\n", " ")[:200] if not args.skip_ask else "",
                    "manual_answer_score_0_2": "",
                    "manual_source_score_0_2": "",
                    "manual_notes": row.get("notes", ""),
                }
            )

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(result_rows[0].keys()))
        writer.writeheader()
        writer.writerows(result_rows)

    search_hit_rate = (search_hits / total) if total else 0.0
    ask_source_hit_rate = (ask_source_hits / total) if (total and not args.skip_ask) else 0.0
    avg_keyword_recall = (keyword_recall_sum / ask_ok_count) if ask_ok_count else 0.0

    print("=== Day4 Eval Summary ===")
    print(f"Dataset: {dataset_path}")
    print(f"Base URL: {args.base_url}")
    print(f"Total questions: {total}")
    print(f"Search hit@{args.top_k}: {search_hits}/{total} ({search_hit_rate:.1%})")
    if args.skip_ask:
        print("Ask evaluation: skipped")
    else:
        print(f"Ask source hit@{args.top_k}: {ask_source_hits}/{total} ({ask_source_hit_rate:.1%})")
        print(f"Avg keyword recall: {avg_keyword_recall:.1%}")
    print(f"Detailed report: {out_path}")


if __name__ == "__main__":
    main()
