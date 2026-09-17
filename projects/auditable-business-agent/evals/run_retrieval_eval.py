from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.config import database_url
from app.eval_metrics import aggregate_retrieval_metrics
from app.models import RequestType
from app.vector_rag import VectorPolicyKnowledgeBase


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate policy retrieval with Recall@K and MRR")
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--provider", choices=["local", "bge", "openai"], default=None)
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1")
    if not 0 <= args.min_recall <= 1:
        parser.error("--min-recall must be between 0 and 1")
    ranked_k = max(args.k, 3)
    cases = json.loads((Path(__file__).parent / "retrieval_cases.json").read_text(encoding="utf-8"))
    try:
        kb = VectorPolicyKnowledgeBase.from_database(
            connection=database_url(),
            documents_directory=Path(__file__).parent.parent / "sample_data" / "policies",
            provider=args.provider,
        )
    except ValueError as error:
        raise SystemExit(f"Unable to initialize {args.provider or os.getenv('RAG_EMBEDDING_PROVIDER', 'local')} embeddings: {error}") from error
    results = []
    case_results = []
    for case in cases:
        evidence = kb.search(
            request_type=RequestType(case["request_type"]),
            query=case["query"],
            limit=ranked_k,
        )
        ranked_ids = [item.document_id for item in evidence]
        results.append((ranked_ids, case["expected_document_id"]))
        case_results.append(
            {
                "name": case["name"],
                "request_type": case["request_type"],
                "query": case["query"],
                "expected": case["expected_document_id"],
                "retrieved": ranked_ids,
            }
        )
        print(f"{case['name']}: expected={case['expected_document_id']} retrieved={ranked_ids}")
    metrics = aggregate_retrieval_metrics(results, 1)
    if args.k != 1:
        metrics.update(aggregate_retrieval_metrics(results, args.k))
    report = {
        "provider": args.provider or os.getenv("RAG_EMBEDDING_PROVIDER", "local"),
        "cases": len(cases),
        "ranked_k": ranked_k,
        "metrics": metrics,
        "results": case_results,
    }
    print(json.dumps(report, ensure_ascii=False))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if metrics[f"recall_at_{args.k}"] < args.min_recall:
        raise SystemExit("Retrieval quality gate failed")


if __name__ == "__main__":
    main()
