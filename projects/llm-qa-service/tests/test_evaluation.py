"""RAG 评测资产的确定性单元测试（不调用真实 LLM）。"""
import asyncio
from pathlib import Path

import pytest

from app.evaluation import (
    EvaluationConfigurationError,
    RAGEvalCase,
    RetrievalResult,
    build_evaluation_report,
    evidence_rank,
    evaluate_generation,
    hit_contains_expected_evidence,
    load_eval_cases,
    render_markdown_report,
    summarize_retrieval,
    summarize_generation,
    validate_retrieval_thresholds,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_DIR / "evals" / "rag_eval_dataset.jsonl"
CORPUS_PATH = PROJECT_DIR / "sample_data" / "employee-handbook.md"


def _case(*, answerable: bool = True) -> RAGEvalCase:
    return RAGEvalCase(
        id="case-1" if answerable else "case-unanswerable",
        category="annual_leave" if answerable else "unanswerable",
        question="年假有多少天？" if answerable else "公司有股票期权吗？",
        answerable=answerable,
        expected_document_title="employee-handbook" if answerable else None,
        expected_evidence=("入职满 1 年享 12 天",) if answerable else (),
        expected_answer_keywords=("12天",) if answerable else (),
    )


def test_eval_dataset_has_labeled_answerable_and_unanswerable_cases():
    cases = load_eval_cases(DATASET_PATH)

    assert len(cases) == 31
    assert len({case.id for case in cases}) == len(cases)
    assert sum(case.answerable for case in cases) == 29
    assert sum(not case.answerable for case in cases) == 2
    assert {case.category for case in cases} >= {
        "annual_leave", "sick_leave", "overtime", "travel", "remote_work", "training", "offboarding"
    }


def test_labeled_evidence_exists_in_the_versioned_evaluation_corpus():
    corpus = CORPUS_PATH.read_text(encoding="utf-8")

    missing = [
        (case.id, evidence)
        for case in load_eval_cases(DATASET_PATH)
        for evidence in case.expected_evidence
        if evidence not in corpus
    ]

    assert missing == []


def test_evidence_rank_requires_the_labeled_document_and_evidence_text():
    case = _case()
    wrong_document = {
        "document_title": "other-policy",
        "content": "入职满 1 年享 12 天",
        "score": 0.99,
    }
    correct_evidence = {
        "document_title": "employee-handbook",
        "content": "全职员工入职满 1 年享 12天 年假。",
        "score": 0.88,
    }

    assert not hit_contains_expected_evidence(case, wrong_document)
    assert hit_contains_expected_evidence(case, correct_evidence)
    assert evidence_rank(case, [wrong_document, correct_evidence]) == 2
    assert evidence_rank(_case(answerable=False), [correct_evidence]) is None


def test_retrieval_summary_and_markdown_report_expose_baseline_metrics():
    hit = {
        "document_title": "employee-handbook",
        "content": "入职满 1 年享 12 天。",
        "score": 0.91,
    }
    answerable = _case()
    missed = RAGEvalCase(
        id="case-2",
        category="annual_leave",
        question="三年年假多少？",
        answerable=True,
        expected_document_title="employee-handbook",
        expected_evidence=("满 3 年享 15 天",),
        expected_answer_keywords=("15天",),
    )
    unanswerable = _case(answerable=False)
    results = [
        RetrievalResult(answerable, [hit], latency_ms=2.0, evidence_rank=1),
        RetrievalResult(missed, [hit], latency_ms=6.0, evidence_rank=None),
        RetrievalResult(unanswerable, [hit], latency_ms=3.0, evidence_rank=None),
    ]

    summary = summarize_retrieval(results, top_k=4)
    assert summary["evidence_hit_rate_at_1"] == 0.5
    assert summary["mrr"] == 0.5
    assert summary["unanswerable_cases"] == 1

    report = build_evaluation_report(
        results,
        dataset_path="evals/example.jsonl",
        corpus_path="sample_data/example.md",
        embedding_mode="mock",
        top_k=4,
        retrieval_mode="hybrid",
    )
    markdown = render_markdown_report(report)
    assert "Evidence Hit@1" in markdown
    assert "检索模式：`hybrid`" in markdown
    assert report["cases"][0]["hits"][0]["document_title"] == "employee-handbook"
    assert "case-2" in markdown
    assert "--with-generation" in markdown


def test_retrieval_thresholds_turn_baseline_into_a_regression_gate():
    case = _case()
    hit = {
        "document_title": "employee-handbook",
        "content": "入职满 1 年享 12 天。",
        "score": 0.91,
    }
    report = build_evaluation_report(
        [RetrievalResult(case, [hit], latency_ms=2.0, evidence_rank=1)],
        dataset_path="evals/example.jsonl",
        corpus_path="sample_data/example.md",
        embedding_mode="mock",
        top_k=4,
    )

    validate_retrieval_thresholds(report, min_hit_at_1=1.0, min_hit_at_k=1.0)
    with pytest.raises(EvaluationConfigurationError, match="Evidence Hit@1"):
        validate_retrieval_thresholds(report, min_hit_at_1=1.01)


def test_generation_metrics_check_keywords_citations_and_no_answer_refusal():
    class FakeLiveClient:
        mock = False

        async def chat(self, messages, temperature):
            if "股票期权" in messages[-1]["content"]:
                return "知识库中没有找到相关内容。"
            return "入职满一年可以享有 12 天年假。[资料1]"

    hit = {
        "document_title": "employee-handbook",
        "content": "全职员工入职满 1 年享 12 天。",
        "score": 0.91,
    }
    answerable = _case()
    unanswerable = _case(answerable=False)
    retrieval_results = [
        RetrievalResult(answerable, [hit], latency_ms=2.0, evidence_rank=1),
        RetrievalResult(unanswerable, [hit], latency_ms=2.0, evidence_rank=None),
    ]

    results = asyncio.run(evaluate_generation(FakeLiveClient(), retrieval_results))
    metrics = summarize_generation(results)

    assert metrics["answer_keyword_recall"] == 1.0
    assert metrics["citation_valid_rate"] == 1.0
    assert metrics["citation_supports_evidence_rate"] == 1.0
    assert metrics["no_answer_refusal_rate"] == 1.0
