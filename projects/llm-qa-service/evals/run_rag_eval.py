"""运行项目内置的 RAG 评测集。

示例：
    .venv/bin/python -m evals.run_rag_eval --embedding-provider mock
    .venv/bin/python -m evals.run_rag_eval --embedding-provider local --output evals/baseline.md
    LLM_API_KEY=... .venv/bin/python -m evals.run_rag_eval --with-generation
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_DIR / "evals" / "rag_eval_dataset.jsonl"
DEFAULT_CORPUS = PROJECT_DIR / "sample_data" / "employee-handbook.md"


def rate(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("指标阈值必须在 0 到 1 之间")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行可复现的 RAG 检索评测；默认不调用真实 LLM。"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="JSONL 评测集路径")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="评测知识库文档路径")
    parser.add_argument(
        "--embedding-provider",
        choices=("mock", "local", "api", "auto"),
        default="mock",
        help="默认 mock，保证 CI/本地基线无模型下载且结果可复现",
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=("vector", "hybrid"),
        default="hybrid",
        help="检索模式：hybrid（默认，BM25 + 向量 RRF）或 vector（旧基线对照）",
    )
    parser.add_argument("--top-k", type=int, default=4, help="每题检索结果数量（至少 3，默认 4）")
    parser.add_argument(
        "--min-hit-at-1",
        type=rate,
        help="若 Evidence Hit@1 低于此值则以非零状态退出（适合 CI）",
    )
    parser.add_argument(
        "--min-hit-at-k",
        type=rate,
        help="若 Evidence Hit@K 低于此值则以非零状态退出（适合 CI）",
    )
    parser.add_argument("--chunk-size", type=int, default=None, help="覆盖 RAG_CHUNK_SIZE")
    parser.add_argument("--overlap", type=int, default=None, help="覆盖 RAG_CHUNK_OVERLAP")
    parser.add_argument(
        "--with-generation",
        action="store_true",
        help="调用真实 LLM，额外评估答案关键词、引用与拒答；mock 模式会拒绝运行",
    )
    parser.add_argument("--output", type=Path, help="将 Markdown 报告写入指定路径")
    parser.add_argument("--json-output", type=Path, help="将完整明细 JSON 写入指定路径")
    parser.add_argument(
        "--keep-corpus",
        action="store_true",
        help="保留 source 以 __eval__ 开头的临时评测文档，便于手工调试",
    )
    return parser.parse_args()


def configure_environment(args: argparse.Namespace) -> None:
    """在导入 app 前设置 embedding 配置，避免配置缓存或单例污染。"""
    os.environ["EMBEDDING_PROVIDER"] = args.embedding_provider
    os.environ["RAG_RETRIEVAL_MODE"] = args.retrieval_mode
    if args.chunk_size is not None:
        os.environ["RAG_CHUNK_SIZE"] = str(args.chunk_size)
    if args.overlap is not None:
        os.environ["RAG_CHUNK_OVERLAP"] = str(args.overlap)


async def run(args: argparse.Namespace) -> dict:
    # 延迟导入：configure_environment 必须先于 Settings / Vector 列定义执行。
    from app.config import get_settings
    from app.db import close_db, get_session_factory, init_db
    from app.embedding_client import get_embedding_client, reset_embedding_client
    from app.evaluation import (
        build_evaluation_report,
        cleanup_evaluation_corpus,
        evaluate_generation,
        evaluate_retrieval,
        load_eval_cases,
        prepare_evaluation_corpus,
        render_markdown_report,
        validate_retrieval_thresholds,
    )
    from app.llm_client import get_llm_client

    get_settings.cache_clear()
    reset_embedding_client()
    cases = load_eval_cases(args.dataset)
    settings = get_settings()
    source_marker = f"__eval__{uuid4().hex}_{args.corpus.name}"
    document = None
    generation_results = None
    client = None

    try:
        await init_db()
        async with get_session_factory()() as session:
            try:
                document = await prepare_evaluation_corpus(
                    session,
                    args.corpus,
                    source_marker=source_marker,
                    chunk_size=settings.rag_chunk_size,
                    overlap=settings.rag_chunk_overlap,
                )
                retrieval_results = await evaluate_retrieval(
                    session,
                    cases,
                    top_k=args.top_k,
                    document_ids=[document.id],
                    retrieval_mode=args.retrieval_mode,
                )
                if args.with_generation:
                    client = get_llm_client()
                    generation_results = await evaluate_generation(client, retrieval_results)

                report = build_evaluation_report(
                    retrieval_results,
                    dataset_path=_display_path(args.dataset),
                    corpus_path=_display_path(args.corpus),
                    embedding_mode=get_embedding_client().mode,
                    top_k=args.top_k,
                    retrieval_mode=args.retrieval_mode,
                    generation_results=generation_results,
                )
                validate_retrieval_thresholds(
                    report,
                    min_hit_at_1=args.min_hit_at_1,
                    min_hit_at_k=args.min_hit_at_k,
                )
            finally:
                if document is not None and not args.keep_corpus:
                    await cleanup_evaluation_corpus(session, document_id=document.id)
    finally:
        if client is not None:
            await client.aclose()
        await get_embedding_client().aclose()
        await close_db()

    markdown = render_markdown_report(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return {"report": report, "markdown": markdown}


def _display_path(path: Path) -> str:
    """报告中优先使用相对项目路径，避免提交本机绝对路径。"""
    try:
        return str(path.resolve().relative_to(PROJECT_DIR))
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    configure_environment(args)
    try:
        result = asyncio.run(run(args))
    except Exception as exc:
        print(f"RAG eval failed: {exc}", file=sys.stderr)
        return 1
    print(result["markdown"])
    if args.output:
        print(f"Markdown report written to {args.output}")
    if args.json_output:
        print(f"JSON report written to {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
