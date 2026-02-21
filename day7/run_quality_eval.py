import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Tuple

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day7 quality evaluation for /ask endpoint.")
    parser.add_argument("--base_url", default="http://127.0.0.1:8001", help="RAG API base url")
    parser.add_argument("--dataset", default="../day4/eval_dataset.csv", help="Evaluation dataset csv")
    parser.add_argument("--top_k", type=int, default=3, help="Top-k for ask")
    parser.add_argument("--prompt_style", default="v1", help="Prompt style: v1 or v2")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout sec")
    parser.add_argument("--output_dir", default="reports", help="Output directory")
    parser.add_argument("--tag", default="", help="Optional output file tag")
    return parser.parse_args()


def read_dataset(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_keywords(text: str) -> List[str]:
    if not text:
        return []
    return [item.strip() for item in text.split(";") if item.strip()]


def keyword_recall(answer: str, expected_keywords: List[str]) -> float:
    if not expected_keywords:
        return 0.0
    hits = sum(1 for kw in expected_keywords if kw in answer)
    return hits / len(expected_keywords)


def source_labels_from_sources(sources: List[Dict[str, Any]]) -> List[str]:
    labels: List[str] = []
    for item in sources:
        doc = str(item.get("doc_name", "")).strip()
        chunk_id = str(item.get("chunk_id", "")).strip()
        if doc and chunk_id:
            labels.append(f"{doc}#chunk{chunk_id}")
    return labels


def evaluate_row(
    response_json: Dict[str, Any],
    expected_doc: str,
    expected_keywords: List[str],
) -> Dict[str, Any]:
    answer = str(response_json.get("answer", ""))
    sources = response_json.get("sources", [])
    citations = response_json.get("citations", [])
    confidence = str(response_json.get("confidence", "")).lower().strip()
    grounded = bool(response_json.get("grounded", False))
    prompt_style = str(response_json.get("prompt_style", "")).strip()

    if not isinstance(sources, list):
        sources = []
    if not isinstance(citations, list):
        citations = []

    source_labels = source_labels_from_sources(sources)
    citation_set = {str(item).strip() for item in citations if str(item).strip()}
    source_set = set(source_labels)

    format_ok = bool(answer.strip()) and confidence in {"low", "medium", "high"} and grounded in {
        True,
        False,
    }
    citation_compliant = bool(citation_set) and citation_set.issubset(source_set)
    expected_doc_cited = any(label.startswith(f"{expected_doc}#") for label in citation_set)
    kw_recall = keyword_recall(answer, expected_keywords)

    return {
        "prompt_style_resp": prompt_style,
        "format_ok": int(format_ok),
        "citation_compliant": int(citation_compliant),
        "expected_doc_cited": int(expected_doc_cited),
        "keyword_recall": kw_recall,
        "confidence": confidence,
        "answer_preview": answer.replace("\n", " ")[:220],
        "source_labels": "|".join(source_labels),
        "citations": "|".join(sorted(citation_set)),
    }


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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"_{args.tag}" if args.tag else ""
    detail_path = out_dir / f"quality_detail_{args.prompt_style}{tag}_{timestamp}.csv"
    summary_path = out_dir / f"quality_summary_{args.prompt_style}{tag}_{timestamp}.json"

    total = 0
    ok_http = 0
    format_ok_count = 0
    citation_ok_count = 0
    expected_doc_cited_count = 0
    keyword_recall_sum = 0.0
    latency_sum = 0.0

    detail_rows: List[Dict[str, Any]] = []

    with httpx.Client(timeout=args.timeout) as client:
        for row in rows:
            total += 1
            qid = str(row.get("id", "")).strip()
            query = str(row.get("query", "")).strip()
            expected_doc = str(row.get("expected_doc", "")).strip()
            expected_keywords = split_keywords(str(row.get("expected_keywords", "")))

            start = perf_counter()
            status_code = 0
            resp_json: Dict[str, Any] = {}
            error = ""
            try:
                resp = client.post(
                    f"{args.base_url}/ask",
                    json={
                        "question": query,
                        "top_k": args.top_k,
                        "prompt_style": args.prompt_style,
                    },
                )
                status_code = resp.status_code
                if status_code == 200:
                    resp_json = resp.json()
                    ok_http += 1
                else:
                    try:
                        error = str(resp.json())
                    except json.JSONDecodeError:
                        error = resp.text[:300]
            except Exception as exc:
                error = str(exc)
            latency_ms = (perf_counter() - start) * 1000
            latency_sum += latency_ms

            evaluated = evaluate_row(resp_json, expected_doc, expected_keywords) if status_code == 200 else {
                "prompt_style_resp": "",
                "format_ok": 0,
                "citation_compliant": 0,
                "expected_doc_cited": 0,
                "keyword_recall": 0.0,
                "confidence": "",
                "answer_preview": "",
                "source_labels": "",
                "citations": "",
            }

            format_ok_count += int(evaluated["format_ok"])
            citation_ok_count += int(evaluated["citation_compliant"])
            expected_doc_cited_count += int(evaluated["expected_doc_cited"])
            keyword_recall_sum += float(evaluated["keyword_recall"])

            detail_rows.append(
                {
                    "id": qid,
                    "query": query,
                    "expected_doc": expected_doc,
                    "http_status": status_code,
                    "latency_ms": round(latency_ms, 3),
                    "format_ok": evaluated["format_ok"],
                    "citation_compliant": evaluated["citation_compliant"],
                    "expected_doc_cited": evaluated["expected_doc_cited"],
                    "keyword_recall": f"{float(evaluated['keyword_recall']):.3f}",
                    "confidence": evaluated["confidence"],
                    "prompt_style_resp": evaluated["prompt_style_resp"],
                    "citations": evaluated["citations"],
                    "source_labels": evaluated["source_labels"],
                    "answer_preview": evaluated["answer_preview"],
                    "error": error,
                }
            )

    http_success_rate = (ok_http / total) if total else 0.0
    format_ok_rate = (format_ok_count / total) if total else 0.0
    citation_ok_rate = (citation_ok_count / total) if total else 0.0
    expected_doc_cited_rate = (expected_doc_cited_count / total) if total else 0.0
    avg_keyword_recall = (keyword_recall_sum / total) if total else 0.0
    avg_latency_ms = (latency_sum / total) if total else 0.0

    with detail_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
        writer.writeheader()
        writer.writerows(detail_rows)

    summary = {
        "created_at": datetime.now().isoformat(),
        "base_url": args.base_url,
        "dataset": str(dataset_path),
        "prompt_style": args.prompt_style,
        "top_k": args.top_k,
        "total": total,
        "http_success_rate": round(http_success_rate, 4),
        "format_ok_rate": round(format_ok_rate, 4),
        "citation_compliance_rate": round(citation_ok_rate, 4),
        "expected_doc_cited_rate": round(expected_doc_cited_rate, 4),
        "avg_keyword_recall": round(avg_keyword_recall, 4),
        "avg_latency_ms": round(avg_latency_ms, 3),
        "detail_csv": str(detail_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== Day7 Quality Eval Complete ===")
    print(f"Prompt style             : {args.prompt_style}")
    print(f"HTTP success rate        : {http_success_rate:.1%}")
    print(f"Format OK rate           : {format_ok_rate:.1%}")
    print(f"Citation compliance rate : {citation_ok_rate:.1%}")
    print(f"Expected doc cited rate  : {expected_doc_cited_rate:.1%}")
    print(f"Avg keyword recall       : {avg_keyword_recall:.1%}")
    print(f"Avg latency (ms)         : {avg_latency_ms:.2f}")
    print(f"Summary JSON             : {summary_path}")
    print(f"Detail CSV               : {detail_path}")


if __name__ == "__main__":
    main()
