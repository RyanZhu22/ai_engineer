"""RAG 评测资产的确定性单元测试（不调用真实 LLM）。"""
import asyncio
from argparse import Namespace
from pathlib import Path

import pytest

from app.evaluation import (
    EvaluationConfigurationError,
    GenerationResult,
    JudgeOutputValidationError,
    LLM_JUDGE_PROMPT_VERSION,
    RAGEvalCase,
    RetrievalResult,
    build_llm_judge_messages,
    build_evaluation_report,
    evidence_rank,
    evaluate_generation,
    evaluate_llm_judge,
    hit_contains_expected_evidence,
    is_grounded_refusal,
    load_eval_cases,
    parse_llm_judge_output,
    render_markdown_report,
    summarize_llm_judge,
    summarize_retrieval,
    summarize_generation,
    validate_retrieval_thresholds,
)
from evals.run_rag_eval import validate_args


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
                return "提供的资料未提及股票期权，因此无法确认公司是否提供。"
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


def test_grounded_refusal_accepts_common_source_based_variants_but_not_unsupported_denials():
    assert is_grounded_refusal("提供的资料未提及股票期权，因此无法确认公司是否提供。")
    assert is_grounded_refusal("资料中未明确提及晚餐报销额度的具体上限。")
    assert is_grounded_refusal("目前资料不足，无法判断晚餐报销上限。")
    assert is_grounded_refusal("现有资料无法确认公司是否提供股票期权。")
    assert is_grounded_refusal("暂无相关信息可以回答这个问题。")
    assert not is_grounded_refusal("我不知道。")
    assert not is_grounded_refusal("公司不提供股票期权。")


def test_generation_report_lists_concrete_answers_that_need_review():
    answerable = _generation_result()
    unanswerable = _generation_result(answerable=False, answer="我不知道。")
    unanswerable.refusal_detected = False
    report = build_evaluation_report(
        [answerable.retrieval, unanswerable.retrieval],
        dataset_path="evals/example.jsonl",
        corpus_path="sample_data/example.md",
        embedding_mode="mock",
        top_k=4,
        generation_results=[answerable, unanswerable],
    )
    markdown = render_markdown_report(report)
    review_cases = report["generation"]["review_cases"]

    assert review_cases[0]["id"] == "case-unanswerable"
    assert review_cases[0]["issues"] == ["未命中资料不足的拒答规则"]
    assert review_cases[0]["answer_preview"] == "我不知道。"
    assert "Generation cases requiring review（具体失败回答）" in markdown
    assert "未命中资料不足的拒答规则" in markdown
    assert "我不知道。" in markdown


def _generation_result(*, answerable: bool = True, answer: str | None = None) -> GenerationResult:
    case = _case(answerable=answerable)
    hit = {
        "document_title": "employee-handbook",
        "content": "全职员工入职满 1 年享 12 天。",
        "score": 0.91,
    }
    retrieval = RetrievalResult(
        case,
        [hit],
        latency_ms=2.0,
        evidence_rank=1 if answerable else None,
    )
    return GenerationResult(
        retrieval=retrieval,
        answer=answer or (
            "入职满一年可以享有 12 天年假。[资料1]"
            if answerable
            else "知识库中没有找到相关内容。"
        ),
        latency_ms=3.0,
        keyword_recall=1.0 if answerable else None,
        all_keywords_present=True if answerable else None,
        citation_indices=[1] if answerable else [],
        citation_valid=True if answerable else False,
        citation_supports_evidence=True if answerable else None,
        refusal_detected=None if answerable else True,
    )


def test_llm_judge_scores_answerable_and_unanswerable_and_records_prompt_metadata():
    class FakeJudgeClient:
        mock = False

        def __init__(self):
            self.messages = []

        async def chat(self, messages, temperature):
            self.messages.append((messages, temperature))
            if '"answerable": false' in messages[-1]["content"]:
                return """```json
{"faithful": true, "answer_correct": null, "refusal_appropriate": true, "reason": "资料没有股票期权信息，回答明确拒答。"}
```"""
            return '{"faithful": true, "answer_correct": true, "refusal_appropriate": null, "reason": "年假天数与检索资料一致。"}'

    candidate_results = [_generation_result(), _generation_result(answerable=False)]
    client = FakeJudgeClient()
    judge_results = asyncio.run(evaluate_llm_judge(client, candidate_results))
    metrics = summarize_llm_judge(judge_results)

    assert metrics["json_parse_success_rate"] == 1.0
    assert metrics["faithfulness_rate"] == 1.0
    assert metrics["answer_correct_rate"] == 1.0
    assert metrics["unanswerable_refusal_appropriate_rate"] == 1.0
    assert metrics["parsed_cases"] == 2
    assert client.messages[0][1] == 0.0
    assert "不可信数据" in client.messages[0][0][0]["content"]
    assert '"candidate_answer"' in client.messages[0][0][-1]["content"]

    report = build_evaluation_report(
        [item.retrieval for item in candidate_results],
        dataset_path="evals/example.jsonl",
        corpus_path="sample_data/example.md",
        embedding_mode="mock",
        top_k=4,
        generation_results=candidate_results,
        generation_model="candidate-model",
        generation_temperature=0.0,
        judge_results=judge_results,
        judge_model="judge-model",
        judge_temperature=0.0,
        judge_prompt_version=LLM_JUDGE_PROMPT_VERSION,
    )
    markdown = render_markdown_report(report)

    assert report["schema_version"] == 2
    assert report["generation"]["llm_judge"]["model"] == "judge-model"
    assert "LLM-as-a-judge metrics" in markdown
    assert "candidate-model" in markdown
    assert "judge-model" in markdown


def test_llm_judge_malformed_output_is_visible_and_never_counted_as_a_pass():
    class MalformedJudgeClient:
        mock = False

        async def chat(self, messages, temperature):
            return "结论：答案正确"

    generation = _generation_result()
    judge_results = asyncio.run(evaluate_llm_judge(MalformedJudgeClient(), [generation]))
    metrics = summarize_llm_judge(judge_results)
    report = build_evaluation_report(
        [generation.retrieval],
        dataset_path="evals/example.jsonl",
        corpus_path="sample_data/example.md",
        embedding_mode="mock",
        top_k=4,
        generation_results=[generation],
        judge_results=judge_results,
    )

    assert judge_results[0].faithful is None
    assert judge_results[0].parse_error is not None
    assert metrics["json_parse_success_rate"] == 0.0
    assert metrics["faithfulness_rate"] is None
    assert metrics["faithfulness_scored_cases"] == 0
    assert report["generation"]["review_cases"][0]["issues"] == ["LLM 裁判输出无法解析"]
    assert "裁判输出不是合法 JSON" in report["generation"]["review_cases"][0]["judge_note"]


def test_llm_judge_rejects_mock_client_to_avoid_fake_quality_scores():
    class MockJudgeClient:
        mock = True

        async def chat(self, messages, temperature):  # pragma: no cover - 不应被调用
            raise AssertionError("mock 裁判不应发起评测")

    with pytest.raises(EvaluationConfigurationError, match="真实 LLM_API_KEY"):
        asyncio.run(evaluate_llm_judge(MockJudgeClient(), [_generation_result()]))


def test_llm_judge_output_schema_rejects_wrong_case_specific_fields():
    with pytest.raises(JudgeOutputValidationError, match="refusal_appropriate"):
        parse_llm_judge_output(
            '{"faithful": true, "answer_correct": true, "refusal_appropriate": false, "reason": "x"}',
            answerable=True,
        )

    messages = build_llm_judge_messages(_generation_result())
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"


def test_llm_judge_cli_flags_require_real_generation_mode():
    with pytest.raises(ValueError, match="--with-generation"):
        validate_args(Namespace(with_generation=False, with_llm_judge=True, judge_model=None))
    with pytest.raises(ValueError, match="--with-llm-judge"):
        validate_args(Namespace(with_generation=True, with_llm_judge=False, judge_model="judge"))

    validate_args(Namespace(with_generation=True, with_llm_judge=True, judge_model="judge"))
