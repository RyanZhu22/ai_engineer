"""混合检索的无数据库单元测试。"""

import pytest

from app.rag import (
    bm25_scores,
    reciprocal_rank_fusion,
    rerank_by_best_sentence_bm25,
    tokenize_for_bm25,
)


def _hit(chunk_id: int, score: float) -> dict:
    return {
        "chunk_id": chunk_id,
        "content": f"chunk-{chunk_id}",
        "document_id": 1,
        "document_title": "handbook",
        "score": score,
    }


def test_chinese_bm25_promotes_exact_city_and_reimbursement_evidence():
    documents = [
        "一线城市每晚不超过 800 元。",
        "二线城市每晚不超过 500 元，适用于酒店住宿报销。",
        "离职时未休完年假按日薪折算发放。",
    ]

    scores = bm25_scores("二线城市的酒店报销上限是多少？", documents)

    assert "二线" in tokenize_for_bm25("二线城市")
    assert scores[1] == max(scores)
    assert scores[1] > scores[0]
    assert scores[1] > scores[2]


def test_rrf_promotes_a_chunk_supported_by_both_retrievers():
    # chunk 2 在向量与 BM25 两路都靠前，应比只在一路靠前的 chunk 1 排得更高。
    fused = reciprocal_rank_fusion(
        [_hit(1, 0.99), _hit(2, 0.91)],
        [_hit(2, 12.0), _hit(3, 8.0)],
    )

    assert [hit["chunk_id"] for hit in fused[:3]] == [2, 1, 3]
    assert fused[0]["vector_rank"] == 2
    assert fused[0]["bm25_rank"] == 1
    assert fused[0]["vector_score"] == 0.91
    assert fused[0]["bm25_score"] == 12.0


def test_sentence_bm25_reranker_uses_policy_sentence_not_markdown_heading():
    candidates = [
        {**_hit(1, 0.9), "content": "## 五、差旅报销\n出差住宿标准：一线城市每晚不超过 800 元。"},
        {**_hit(2, 0.8), "content": "报销需在行程结束后 14 天内提交，财务审批周期为 5 个工作日。"},
    ]

    ranked = rerank_by_best_sentence_bm25("报销在行程结束后几天内提交？", candidates)

    assert ranked[0]["chunk_id"] == 2


def test_bm25_and_rrf_reject_invalid_scoring_parameters():
    with pytest.raises(ValueError, match="k1"):
        bm25_scores("年假", ["年假 12 天"], k1=0)
    with pytest.raises(ValueError, match="rrf_k"):
        reciprocal_rank_fusion([], [], rrf_k=0)
    with pytest.raises(ValueError, match="权重"):
        reciprocal_rank_fusion([], [], bm25_weight=0)
