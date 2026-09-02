"""RAG 评测：数据集校验、检索基线、可选生成质量与引用检查。

设计目标：
  - 默认只评检索，因此 CI 不需要真实 LLM、不会产生调用费用；
  - 使用明确的「问题 → 证据片段」标注，计算 Hit@K、MRR 和延迟；
  - 有真实 LLM 时可额外评回答关键词覆盖和引用是否指向正确证据；
  - 评测临时文档按 source 命名空间隔离，绝不删除用户上传的数据。

这不是 Ragas 的替代品：它提供一个可复现、零外部依赖的工程基线。后续可用
同一份 JSONL 数据集接入 LLM-as-a-judge / Ragas 做语义忠实度评分。
"""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Document
from .llm_client import LLMClient
from .rag import build_rag_prompt, index_document, search_chunks


_CITATION_RE = re.compile(r"\[资料\s*(\d+)\]")
_REFUSAL_MARKERS = (
    "知识库中没有找到",
    "未找到相关内容",
    "资料中没有",
    "没有相关信息",
    "无法从提供的资料",
)


class EvaluationConfigurationError(ValueError):
    """评测配置不完整或会生成误导性结果时抛出。"""


@dataclass(frozen=True)
class RAGEvalCase:
    """一条人工标注的 RAG 评测样本。"""

    id: str
    category: str
    question: str
    answerable: bool
    expected_document_title: str | None
    expected_evidence: tuple[str, ...]
    expected_answer_keywords: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any], line_number: int) -> "RAGEvalCase":
        def required_text(key: str) -> str:
            value = raw.get(key)
            if not isinstance(value, str) or not value.strip():
                raise EvaluationConfigurationError(
                    f"第 {line_number} 行的 {key!r} 必须是非空字符串"
                )
            return value.strip()

        def text_list(key: str) -> tuple[str, ...]:
            value = raw.get(key, [])
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise EvaluationConfigurationError(
                    f"第 {line_number} 行的 {key!r} 必须是字符串数组"
                )
            return tuple(item.strip() for item in value)

        answerable = raw.get("answerable")
        if not isinstance(answerable, bool):
            raise EvaluationConfigurationError(
                f"第 {line_number} 行的 'answerable' 必须是 true 或 false"
            )

        expected_title = raw.get("expected_document_title")
        if expected_title is not None and (
            not isinstance(expected_title, str) or not expected_title.strip()
        ):
            raise EvaluationConfigurationError(
                f"第 {line_number} 行的 'expected_document_title' 必须是字符串或 null"
            )

        evidence = text_list("expected_evidence")
        keywords = text_list("expected_answer_keywords")
        if answerable and (not expected_title or not evidence or not keywords):
            raise EvaluationConfigurationError(
                f"第 {line_number} 行是可回答问题，必须标注文档、证据和答案关键词"
            )
        if not answerable and (expected_title or evidence):
            raise EvaluationConfigurationError(
                f"第 {line_number} 行是不可回答问题，不应声明已有证据"
            )

        return cls(
            id=required_text("id"),
            category=required_text("category"),
            question=required_text("question"),
            answerable=answerable,
            expected_document_title=expected_title.strip() if expected_title else None,
            expected_evidence=evidence,
            expected_answer_keywords=keywords,
        )


@dataclass
class RetrievalResult:
    case: RAGEvalCase
    hits: list[dict[str, Any]]
    latency_ms: float
    evidence_rank: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "category": self.case.category,
            "question": self.case.question,
            "answerable": self.case.answerable,
            "expected_document_title": self.case.expected_document_title,
            "expected_evidence": list(self.case.expected_evidence),
            "latency_ms": round(self.latency_ms, 3),
            "evidence_rank": self.evidence_rank,
            "hits": [
                {
                    "document_title": hit["document_title"],
                    "score": hit["score"],
                    "content_preview": _preview(hit["content"], limit=160),
                }
                for hit in self.hits
            ],
        }


@dataclass
class GenerationResult:
    retrieval: RetrievalResult
    answer: str
    latency_ms: float
    keyword_recall: float | None
    all_keywords_present: bool | None
    citation_indices: list[int]
    citation_valid: bool | None
    citation_supports_evidence: bool | None
    refusal_detected: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.retrieval.case.id,
            "latency_ms": round(self.latency_ms, 3),
            "answer_preview": _preview(self.answer, limit=260),
            "keyword_recall": _round_or_none(self.keyword_recall),
            "all_keywords_present": self.all_keywords_present,
            "citation_indices": self.citation_indices,
            "citation_valid": self.citation_valid,
            "citation_supports_evidence": self.citation_supports_evidence,
            "refusal_detected": self.refusal_detected,
        }


def load_eval_cases(path: str | Path, *, min_cases: int = 20) -> list[RAGEvalCase]:
    """读取 JSONL 数据集，并在运行前阻止空字段或重复 ID。"""
    dataset_path = Path(path)
    if not dataset_path.is_file():
        raise EvaluationConfigurationError(f"评测数据集不存在: {dataset_path}")

    cases: list[RAGEvalCase] = []
    ids: set[str] = set()
    for line_number, raw_line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationConfigurationError(
                f"第 {line_number} 行不是合法 JSON: {exc.msg}"
            ) from exc
        if not isinstance(raw, dict):
            raise EvaluationConfigurationError(f"第 {line_number} 行必须是 JSON 对象")
        case = RAGEvalCase.from_dict(raw, line_number)
        if case.id in ids:
            raise EvaluationConfigurationError(f"评测数据集存在重复 id: {case.id}")
        ids.add(case.id)
        cases.append(case)

    if len(cases) < min_cases:
        raise EvaluationConfigurationError(
            f"评测集至少需要 {min_cases} 条样本，当前只有 {len(cases)} 条"
        )
    return cases


def normalize_text(value: str) -> str:
    """用于人工标注短语匹配：忽略大小写、空白和中文标点差异。"""
    return re.sub(r"[^\w\u4e00-\u9fff]", "", value.lower())


def hit_contains_expected_evidence(case: RAGEvalCase, hit: dict[str, Any]) -> bool:
    """判断一个召回切片是否含该题的标注证据。"""
    if not case.answerable:
        return False
    if hit.get("document_title") != case.expected_document_title:
        return False
    content = normalize_text(str(hit.get("content", "")))
    return any(normalize_text(evidence) in content for evidence in case.expected_evidence)


def evidence_rank(case: RAGEvalCase, hits: Sequence[dict[str, Any]]) -> int | None:
    """返回第一条正确证据的 1-based 名次；不可回答问题不计入检索指标。"""
    if not case.answerable:
        return None
    for index, hit in enumerate(hits, start=1):
        if hit_contains_expected_evidence(case, hit):
            return index
    return None


async def evaluate_retrieval(
    session: AsyncSession,
    cases: Sequence[RAGEvalCase],
    *,
    top_k: int,
    document_ids: Sequence[int],
) -> list[RetrievalResult]:
    """对每条问题运行真实检索，并保留每条命中明细供报告排错。"""
    if top_k < 3:
        raise EvaluationConfigurationError("评测 top_k 必须至少为 3，才能计算 Hit@3")
    if not document_ids:
        raise EvaluationConfigurationError("评测必须限定至少一个文档 ID")

    results: list[RetrievalResult] = []
    for case in cases:
        started_at = time.perf_counter()
        hits = await search_chunks(
            session,
            case.question,
            top_k=top_k,
            document_ids=document_ids,
        )
        latency_ms = (time.perf_counter() - started_at) * 1000
        results.append(
            RetrievalResult(
                case=case,
                hits=hits,
                latency_ms=latency_ms,
                evidence_rank=evidence_rank(case, hits),
            )
        )
    return results


async def evaluate_generation(
    client: LLMClient,
    retrieval_results: Sequence[RetrievalResult],
    *,
    temperature: float = 0.0,
) -> list[GenerationResult]:
    """可选的真实 LLM 回答评测。

    mock 模式只有开发占位文案，并不具备回答能力；强制拒绝运行以免生成
    虚假的「模型质量」结论。
    """
    if client.mock:
        raise EvaluationConfigurationError(
            "--with-generation 需要真实 LLM_API_KEY；mock 回复不能代表回答质量"
        )

    results: list[GenerationResult] = []
    for retrieval in retrieval_results:
        case = retrieval.case
        messages = [
            {"role": "system", "content": build_rag_prompt(case.question, retrieval.hits)},
            {"role": "user", "content": case.question},
        ]
        started_at = time.perf_counter()
        answer = await client.chat(messages, temperature=temperature)
        latency_ms = (time.perf_counter() - started_at) * 1000

        citations = [int(value) for value in _CITATION_RE.findall(answer)]
        valid_citations = [index for index in citations if 1 <= index <= len(retrieval.hits)]

        if case.answerable:
            normalized_answer = normalize_text(answer)
            keyword_matches = [
                normalize_text(keyword) in normalized_answer
                for keyword in case.expected_answer_keywords
            ]
            matching_evidence_indices = {
                index
                for index, hit in enumerate(retrieval.hits, start=1)
                if hit_contains_expected_evidence(case, hit)
            }
            results.append(
                GenerationResult(
                    retrieval=retrieval,
                    answer=answer,
                    latency_ms=latency_ms,
                    keyword_recall=sum(keyword_matches) / len(keyword_matches),
                    all_keywords_present=all(keyword_matches),
                    citation_indices=citations,
                    citation_valid=bool(citations) and len(valid_citations) == len(citations),
                    citation_supports_evidence=bool(
                        matching_evidence_indices.intersection(valid_citations)
                    ),
                    refusal_detected=None,
                )
            )
        else:
            normalized_answer = normalize_text(answer)
            refusal_detected = any(
                normalize_text(marker) in normalized_answer for marker in _REFUSAL_MARKERS
            )
            results.append(
                GenerationResult(
                    retrieval=retrieval,
                    answer=answer,
                    latency_ms=latency_ms,
                    keyword_recall=None,
                    all_keywords_present=None,
                    citation_indices=citations,
                    citation_valid=bool(citations) and len(valid_citations) == len(citations),
                    citation_supports_evidence=None,
                    refusal_detected=refusal_detected,
                )
            )
    return results


async def prepare_evaluation_corpus(
    session: AsyncSession,
    corpus_path: str | Path,
    *,
    source_marker: str,
    chunk_size: int,
    overlap: int,
) -> Document:
    """索引专属临时评测文档。

    source marker 由调用方使用随机值生成；若意外重复，宁可失败也不删除
    已有文档。清理阶段再按本次创建的 document ID 精确删除。
    """
    path = Path(corpus_path)
    if not path.is_file():
        raise EvaluationConfigurationError(f"评测语料不存在: {path}")

    existing = (
        await session.execute(select(Document.id).where(Document.source == source_marker))
    ).scalar_one_or_none()
    if existing is not None:
        raise EvaluationConfigurationError("评测临时文档标识冲突；请重新运行")

    return await index_document(
        session,
        source_marker,
        path.read_bytes(),
        chunk_size=chunk_size,
        overlap=overlap,
        title=path.stem,
    )


async def cleanup_evaluation_corpus(session: AsyncSession, *, document_id: int) -> None:
    """仅按本次创建的文档 ID 清理，避免以文件名误删用户数据。"""
    doc = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if doc is None:
        return
    if not doc.source.startswith("__eval__"):
        raise EvaluationConfigurationError("拒绝清理非评测命名空间文档")
    await session.delete(doc)
    await session.commit()


def summarize_retrieval(
    results: Sequence[RetrievalResult],
    *,
    top_k: int,
) -> dict[str, Any]:
    """汇总可回答样本的 Hit@1 / Hit@3 / Hit@K / MRR 和延迟。"""
    answerable = [result for result in results if result.case.answerable]
    if not answerable:
        raise EvaluationConfigurationError("评测集没有可回答样本，无法计算检索指标")

    def hit_rate(k: int) -> float:
        return sum(
            result.evidence_rank is not None and result.evidence_rank <= k
            for result in answerable
        ) / len(answerable)

    ranks = [result.evidence_rank for result in answerable]
    reciprocal_ranks = [1 / rank if rank is not None else 0.0 for rank in ranks]
    latencies = [result.latency_ms for result in results]
    return {
        "total_cases": len(results),
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(results) - len(answerable),
        "evidence_hit_rate_at_1": _round(hit_rate(1)),
        "evidence_hit_rate_at_3": _round(hit_rate(min(3, top_k))),
        f"evidence_hit_rate_at_{top_k}": _round(hit_rate(top_k)),
        "mrr": _round(fmean(reciprocal_ranks)),
        "latency_ms": _latency_summary(latencies),
    }


def summarize_generation(results: Sequence[GenerationResult]) -> dict[str, Any]:
    """汇总真实 LLM 的关键词、引用和拒答指标。"""
    answerable = [result for result in results if result.retrieval.case.answerable]
    unanswerable = [result for result in results if not result.retrieval.case.answerable]
    if not answerable:
        raise EvaluationConfigurationError("没有可回答样本，无法计算回答质量指标")

    return {
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(unanswerable),
        "answer_keyword_recall": _round(
            fmean(result.keyword_recall or 0.0 for result in answerable)
        ),
        "all_answer_keywords_present_rate": _round(
            sum(bool(result.all_keywords_present) for result in answerable) / len(answerable)
        ),
        "citation_format_rate": _round(
            sum(bool(result.citation_indices) for result in answerable) / len(answerable)
        ),
        "citation_valid_rate": _round(
            sum(bool(result.citation_valid) for result in answerable) / len(answerable)
        ),
        "citation_supports_evidence_rate": _round(
            sum(bool(result.citation_supports_evidence) for result in answerable) / len(answerable)
        ),
        "no_answer_refusal_rate": _round(
            sum(bool(result.refusal_detected) for result in unanswerable) / len(unanswerable)
        ) if unanswerable else None,
        "latency_ms": _latency_summary([result.latency_ms for result in results]),
    }


def build_evaluation_report(
    retrieval_results: Sequence[RetrievalResult],
    *,
    dataset_path: str | Path,
    corpus_path: str | Path,
    embedding_mode: str,
    top_k: int,
    generation_results: Sequence[GenerationResult] | None = None,
) -> dict[str, Any]:
    """构造可写入 JSON、可渲染 Markdown 的评测结果对象。"""
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "corpus": str(corpus_path),
        "embedding_mode": embedding_mode,
        "top_k": top_k,
        "retrieval": summarize_retrieval(retrieval_results, top_k=top_k),
        "cases": [result.to_dict() for result in retrieval_results],
    }
    if generation_results is not None:
        report["generation"] = {
            "metrics": summarize_generation(generation_results),
            "cases": [result.to_dict() for result in generation_results],
        }
    return report


def validate_retrieval_thresholds(
    report: dict[str, Any],
    *,
    min_hit_at_1: float | None = None,
    min_hit_at_k: float | None = None,
) -> None:
    """在 CI 中将基线变成可执行的回归门槛。"""
    retrieval = report["retrieval"]
    top_k = report["top_k"]
    checks = {
        "Evidence Hit@1": (retrieval["evidence_hit_rate_at_1"], min_hit_at_1),
        f"Evidence Hit@{top_k}": (
            retrieval[f"evidence_hit_rate_at_{top_k}"],
            min_hit_at_k,
        ),
    }
    failures = [
        f"{name}={actual:.4f} < required {minimum:.4f}"
        for name, (actual, minimum) in checks.items()
        if minimum is not None and actual < minimum
    ]
    if failures:
        raise EvaluationConfigurationError("RAG evaluation threshold failed: " + "; ".join(failures))


def render_markdown_report(report: dict[str, Any]) -> str:
    """将报告渲染为便于提交、面试展示和人工排错的 Markdown。"""
    retrieval = report["retrieval"]
    top_k = report["top_k"]
    lines = [
        "# RAG Evaluation Baseline",
        "",
        f"- 生成时间（UTC）：{report['generated_at']}",
        f"- 数据集：`{report['dataset']}`",
        f"- 语料：`{report['corpus']}`",
        f"- Embedding：`{report['embedding_mode']}`",
        f"- 检索 top_k：{top_k}",
        "",
        "## Retrieval metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Answerable cases | {retrieval['answerable_cases']} |",
        f"| Unanswerable cases | {retrieval['unanswerable_cases']} |",
        f"| Evidence Hit@1 | {_percentage(retrieval['evidence_hit_rate_at_1'])} |",
        f"| Evidence Hit@3 | {_percentage(retrieval['evidence_hit_rate_at_3'])} |",
        f"| Evidence Hit@{top_k} | {_percentage(retrieval[f'evidence_hit_rate_at_{top_k}'])} |",
        f"| MRR | {retrieval['mrr']:.4f} |",
        f"| Mean latency | {retrieval['latency_ms']['mean']:.2f} ms |",
        f"| P95 latency | {retrieval['latency_ms']['p95']:.2f} ms |",
        "",
    ]

    generation = report.get("generation")
    if generation:
        metrics = generation["metrics"]
        lines.extend([
            "## Generation and citation metrics",
            "",
            "| Metric | Result |",
            "|---|---:|",
            f"| Answer keyword recall | {_percentage(metrics['answer_keyword_recall'])} |",
            f"| All answer keywords present | {_percentage(metrics['all_answer_keywords_present_rate'])} |",
            f"| Citation format present | {_percentage(metrics['citation_format_rate'])} |",
            f"| Citation index valid | {_percentage(metrics['citation_valid_rate'])} |",
            f"| Citation supports expected evidence | {_percentage(metrics['citation_supports_evidence_rate'])} |",
        ])
        if metrics["no_answer_refusal_rate"] is not None:
            lines.append(
                f"| Unanswerable refusal rate | {_percentage(metrics['no_answer_refusal_rate'])} |"
            )
        lines.extend([
            f"| Mean generation latency | {metrics['latency_ms']['mean']:.2f} ms |",
            f"| P95 generation latency | {metrics['latency_ms']['p95']:.2f} ms |",
            "",
        ])
    else:
        lines.extend([
            "## Generation and citation metrics",
            "",
            "未执行。使用真实 `LLM_API_KEY` 后加 `--with-generation`，才会测回答关键词、引用与拒答。",
            "",
        ])

    misses = [
        item for item in report["cases"]
        if item["answerable"] and item["evidence_rank"] != 1
    ]
    lines.extend([
        "## Retrieval cases requiring review",
        "",
    ])
    if not misses:
        lines.extend([
            "所有可回答样本都在第一名命中标注证据。",
            "",
        ])
    else:
        lines.extend([
            "| ID | Category | Evidence rank | Question |",
            "|---|---|---:|---|",
        ])
        for item in misses:
            rank = item["evidence_rank"] if item["evidence_rank"] is not None else "miss"
            lines.append(
                f"| {item['id']} | {item['category']} | {rank} | {item['question']} |"
            )
        lines.append("")

    lines.extend([
        "## Interpretation",
        "",
        "- 检索指标以人工标注的证据短语为准；它衡量的是正确片段是否被召回，而不是文风。",
        "- 默认评测不调用 LLM，适合 CI 和模型/检索参数变更前后的可重复比较。",
        "- 回答质量和引用指标只在真实 LLM 模式下有效；mock 模式的占位回复不会计入。",
        "",
    ])
    return "\n".join(lines)


def _latency_summary(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
    ordered = sorted(values)
    return {
        "mean": _round(fmean(values), 3),
        "p50": _round(_percentile(ordered, 0.50), 3),
        "p95": _round(_percentile(ordered, 0.95), 3),
    }


def _percentile(sorted_values: Sequence[float], percentile: float) -> float:
    """nearest-rank percentile；小数据集的 P95 不会产生虚假插值精度。"""
    index = max(0, math.ceil(percentile * len(sorted_values)) - 1)
    return sorted_values[index]


def _preview(value: str, *, limit: int) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else _round(value)


def _percentage(value: float) -> str:
    return f"{value * 100:.1f}%"
