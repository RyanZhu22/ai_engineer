from __future__ import annotations

from collections.abc import Sequence


def recall_at_k(ranked_document_ids: Sequence[str], expected_document_id: str, k: int) -> float:
    return float(expected_document_id in ranked_document_ids[:k])


def reciprocal_rank(ranked_document_ids: Sequence[str], expected_document_id: str) -> float:
    try:
        return 1 / (ranked_document_ids.index(expected_document_id) + 1)
    except ValueError:
        return 0.0


def aggregate_retrieval_metrics(results: Sequence[tuple[Sequence[str], str]], k: int) -> dict[str, float]:
    if not results:
        raise ValueError("At least one retrieval result is required")
    return {
        f"recall_at_{k}": sum(recall_at_k(ids, expected, k) for ids, expected in results) / len(results),
        "mrr": sum(reciprocal_rank(ids, expected) for ids, expected in results) / len(results),
    }
