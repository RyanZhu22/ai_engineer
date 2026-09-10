"""向量检索基准：精确全表扫描 vs pgvector HNSW 近似检索。

回答四个会被追问的问题，每个都给出可复现的数字：

  1. **索引值不值**：同一批查询，精确扫描和 HNSW 的 P50/P95 相差多少？
  2. **扩展趋势**：数据量 ×10 时，精确扫描线性增长（O(N)）、HNSW 基本持平（≈O(log N)）？
  3. **召回损失多少**：HNSW 是近似检索，相对精确扫描的 Recall@K 是多少？
     ``ef_search`` 是查询时的召回/延迟旋钮，扫一遍就能画出这条曲线。
  4. **带过滤会怎样**：本项目每个查询都带 owner 过滤，HNSW 只取 ef_search 个候选
     再过滤，过滤性强时候选不够 → 召回塌陷。pgvector 0.8 的 ``hnsw.iterative_scan``
     让索引继续往下扫，脚本会对比 off / relaxed_order。

测量方法上的两个刻意设计：
  - **多轮取最小值**：本机 Docker VM 上有其他容器抢 CPU，单次采样会被 10ms 级噪声
    污染。同一个查询跑 ``--passes`` 轮，取每查询的最小值再算分位数，噪声只可能让
    结果偏慢、不会偏快，因此结论不会反向。
  - **延迟只统计数据库检索**：查询向量预先算好，embedding 推理不计入，否则模型耗时
    会淹没索引差异。

说明：这里的 Recall@K 是“ANN 结果与精确扫描结果的交集”，衡量**索引保真度**；
语义质量由 ``evals/run_rag_eval.py`` 的人工标注证据集衡量，两者互补，不要混用。

用法：
    # 默认 5000 切片 + 本地 bge（真实向量几何）
    .venv/bin/python -m evals.bench_retrieval --sizes 5000 --output evals/retrieval-bench.md

    # 看扩展趋势（会重复灌库，local embedding 较慢）
    .venv/bin/python -m evals.bench_retrieval --sizes 2000,10000,20000 --embedding-provider local

    # 快速冒烟（不下载模型，秒级）
    .venv/bin/python -m evals.bench_retrieval --sizes 2000 --embedding-provider mock
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from collections.abc import Callable
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]

from app.config import get_settings  # noqa: E402  （先定位项目根，再导入 app 包）
from app.db import (  # noqa: E402
    Chunk,
    Document,
    close_db,
    create_vector_index,
    drop_vector_index,
    get_session_factory,
    init_db,
)
from app.embedding_client import get_embedding_client, reset_embedding_client  # noqa: E402
from app.rag import chunk_text, vector_candidates  # noqa: E402
from sqlalchemy import delete, func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

BENCH_SOURCE = "__bench_retrieval__"
DEFAULT_CORPUS = PROJECT_DIR / "sample_data" / "employee-handbook.md"
DEFAULT_DATASET = PROJECT_DIR / "evals" / "rag_eval_dataset.jsonl"
MAX_BENCH_DOCUMENTS = 20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="pgvector 精确扫描 vs HNSW 基准")
    parser.add_argument(
        "--sizes",
        default="5000",
        help="逗号分隔的切片数，逐个灌库测量（看 O(N) vs O(log N) 扩展趋势）",
    )
    parser.add_argument("--queries", type=int, default=20, help="使用的查询条数")
    parser.add_argument("--top-k", type=int, default=10, help="Recall@K 的 K，也是检索 limit")
    parser.add_argument(
        "--ef-search",
        default="10,40,100,200",
        help="HNSW 查询候选队列大小，逗号分隔（只在最大规模上扫描）",
    )
    parser.add_argument(
        "--passes",
        type=int,
        default=3,
        help="每个配置重复轮数，取每查询最小值以抵抗本机噪声",
    )
    parser.add_argument(
        "--embedding-provider",
        choices=("mock", "local", "api", "auto"),
        default="local",
        help="mock 秒级冒烟；local 用真实 bge 向量几何（默认）",
    )
    parser.add_argument(
        "--filter-ratio",
        type=float,
        default=0.05,
        help="过滤场景保留的文档比例，用来模拟 owner/部门级权限过滤；1.0 表示跳过",
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=None, help="Markdown 报告输出路径")
    parser.add_argument("--keep", action="store_true", help="保留基准数据，便于手工排查")
    return parser.parse_args()


# ---------- 数据准备 ----------


def load_queries(dataset: Path, limit: int) -> list[str]:
    queries = [
        json.loads(line)["question"]
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not queries:
        raise SystemExit(f"评测集里没有查询：{dataset}")
    # 循环取样，允许 --queries 大于数据集条数
    return [queries[i % len(queries)] for i in range(limit)]


async def seed_corpus(corpus: Path, target: int, document_count: int, batch_size: int = 256) -> None:
    """把语料扩写成 ``document_count`` 个文档、共 ``target`` 条唯一切片。

    - 拆成多个文档，过滤场景才有真实选择性（模拟“只有一部分数据属于当前账号”）。
    - 每条切片追加唯一编号：内容必须唯一，否则检索侧的去重逻辑会把它们合并，
      Recall@K 就失去意义。
    """
    base_chunks = chunk_text(corpus.read_text(encoding="utf-8"))
    if not base_chunks:
        raise SystemExit(f"语料切分后为空：{corpus}")

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(Document).where(Document.source == BENCH_SOURCE))
        await session.commit()

    document_ids: list[int] = []
    for slot in range(document_count):
        async with factory() as session:
            doc = Document(title=f"bench corpus {slot}", source=BENCH_SOURCE, created_at=time.time())
            session.add(doc)
            await session.commit()
            document_ids.append(doc.id)

    per_document = max(1, target // document_count)
    texts = [
        (min(index // per_document, document_count - 1), f"{base_chunks[index % len(base_chunks)]}\n（条目 {index}）")
        for index in range(target)
    ]
    client = get_embedding_client()
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors = await client.embed([item[1] for item in batch])
        async with factory() as session:
            session.add_all([
                Chunk(document_id=document_ids[slot], chunk_index=start + offset, content=content, embedding=vector)
                for offset, ((slot, content), vector) in enumerate(zip(batch, vectors))
            ])
            await session.commit()


async def cleanup() -> None:
    async with get_session_factory()() as session:
        await session.execute(delete(Document).where(Document.source == BENCH_SOURCE))
        await session.commit()


async def bench_document_ids() -> list[int]:
    async with get_session_factory()() as session:
        return list((await session.execute(
            select(Document.id).where(Document.source == BENCH_SOURCE).order_by(Document.id)
        )).scalars().all())


# ---------- 度量工具 ----------


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(samples: list[float]) -> dict[str, float]:
    return {
        "min_ms": round(min(samples), 2),
        "p50_ms": round(percentile(samples, 0.50), 2),
        "p95_ms": round(percentile(samples, 0.95), 2),
        "mean_ms": round(statistics.fmean(samples), 2),
    }


async def run_queries(
    session: AsyncSession,
    query_vectors: list[list[float]],
    *,
    top_k: int,
    passes: int,
    document_ids: list[int] | None = None,
) -> tuple[list[list[int]], dict[str, float]]:
    """跑 ``passes`` 轮查询，返回最后一轮的结果顺序与“每查询最小延迟”的统计。

    多轮取最小值而不是平均值：本机还有其他容器争抢 CPU，偶发的慢查询只会抬高均值，
    取最小值反映的是“索引+数据库本身的成本”，不会让结论偏向任何一方。
    """
    best = [float("inf")] * len(query_vectors)
    last_hits: list[list[int]] = []
    for _ in range(passes):
        last_hits = []
        for index, vector in enumerate(query_vectors):
            started = time.perf_counter()
            hits = await vector_candidates(session, vector, limit=top_k, document_ids=document_ids)
            best[index] = min(best[index], (time.perf_counter() - started) * 1000)
            last_hits.append([hit["chunk_id"] for hit in hits])
    return last_hits, summarize(best)


def recall_at_k(approx: list[list[int]], exact: list[list[int]]) -> float:
    """ANN 结果命中精确扫描结果的条数占比（逐查询求平均）。"""
    if not exact:
        return 0.0
    return statistics.fmean(
        len(set(approx_ids) & set(exact_ids)) / len(exact_ids)
        for approx_ids, exact_ids in zip(approx, exact)
    )


async def apply_session_option(session: AsyncSession, name: str, value: str) -> None:
    """用 SET LOCAL 设置 HNSW 参数。

    刻意不用会话级 SET：连接归还池后 SET 仍然生效，会污染后续请求（回滚不会撤销 SET）。
    SET LOCAL 绑定当前事务，session 关闭即失效。连接建立时已执行过一次向量运算，
    pgvector 的 GUC 此时已注册，不会出现 “unrecognized parameter”。
    """
    if not session.in_transaction():
        await session.begin()
    await session.execute(text(f"SET LOCAL hnsw.{name} = {value}"))


async def measure(
    query_vectors: list[list[float]],
    *,
    top_k: int,
    passes: int,
    warmup_queries: int,
    prepare: Callable[[AsyncSession], object] | None = None,
    hnsw: tuple[int, str] | None = None,
    document_ids: list[int] | None = None,
) -> tuple[list[list[int]], dict[str, float]]:
    """一个测量单元：可选建/删索引、可选 HNSW 参数、先预热再计时。"""
    if prepare is not None:
        await prepare()
    async with get_session_factory()() as session:
        await session.execute(text("ANALYZE chunks"))
        if hnsw is not None:
            await apply_session_option(session, "ef_search", str(hnsw[0]))
            await apply_session_option(session, "iterative_scan", hnsw[1])
        # 预热：排除首次编译、连接建立、页缓存冷启动
        await run_queries(
            session, query_vectors[:warmup_queries], top_k=top_k, passes=1, document_ids=document_ids
        )
        return await run_queries(
            session, query_vectors, top_k=top_k, passes=passes, document_ids=document_ids
        )


# ---------- 单规模测量 ----------


async def measure_size(
    size: int, args: argparse.Namespace, ef_sweep: list[int], query_vectors: list[list[float]],
    *, run_ef_sweep: bool,
) -> dict:
    document_count = max(1, min(MAX_BENCH_DOCUMENTS, size // max(1, args.top_k * 2)))
    print(f"\n=== 规模 {size} 切片（{document_count} 文档，provider={args.embedding_provider}）===")
    await seed_corpus(args.corpus, size, document_count)

    async with get_session_factory()() as session:
        total_chunks = await session.scalar(select(func.count()).select_from(Chunk))
    print(f"  语料：{total_chunks} 切片")

    # ---- 精确扫描（删索引），同时作为 Recall 的 ground truth ----
    exact_hits, exact_stats = await measure(
        query_vectors, top_k=args.top_k, passes=args.passes, warmup_queries=2,
        prepare=drop_vector_index,
    )
    print(f"  精确扫描   P50={exact_stats['p50_ms']}ms P95={exact_stats['p95_ms']}ms min={exact_stats['min_ms']}ms")

    # ---- 带过滤的 ground truth（同样在无索引状态下测）----
    scoped_ids: list[int] | None = None
    exact_filtered_hits: list[list[int]] = []
    filtered_stats: dict[str, float] | None = None
    visible_chunks = total_chunks
    if args.filter_ratio < 1.0:
        ids = await bench_document_ids()
        keep = max(1, round(len(ids) * args.filter_ratio))
        scoped_ids = ids[:keep]
        async with get_session_factory()() as session:
            visible_chunks = await session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id.in_(scoped_ids))
            )
        exact_filtered_hits, filtered_stats = await measure(
            query_vectors, top_k=args.top_k, passes=args.passes, warmup_queries=2,
            document_ids=scoped_ids,
        )
        print(f"  带过滤精确 P50={filtered_stats['p50_ms']}ms（可见 {visible_chunks}/{total_chunks}）")

    # ---- 建 HNSW 索引 ----
    started = time.perf_counter()
    await create_vector_index()
    build_seconds = time.perf_counter() - started
    print(f"  建索引 {build_seconds:.2f}s")

    default_ef = ef_sweep[len(ef_sweep) // 2]
    sweep = ef_sweep if run_ef_sweep else [default_ef]
    hnsw_rows = []
    for ef in sweep:
        hits, stats = await measure(
            query_vectors, top_k=args.top_k, passes=args.passes, warmup_queries=2,
            hnsw=(ef, "off"),
        )
        row = {
            "size": total_chunks, "ef_search": ef, "recall": recall_at_k(hits, exact_hits),
            "build_seconds": build_seconds, **stats,
        }
        hnsw_rows.append(row)
        print(f"  HNSW ef={ef:<4} P50={row['p50_ms']}ms P95={row['p95_ms']}ms "
              f"Recall@{args.top_k}={row['recall']:.3f}")

    filtered_rows = []
    if scoped_ids is not None:
        for iterative in ("off", "relaxed_order"):
            hits, stats = await measure(
                query_vectors, top_k=args.top_k, passes=args.passes, warmup_queries=2,
                hnsw=(default_ef, iterative), document_ids=scoped_ids,
            )
            row = {
                "iterative_scan": iterative,
                "recall": recall_at_k(hits, exact_filtered_hits),
                "avg_hits": round(statistics.fmean(len(ids) for ids in hits), 2),
                **stats,
            }
            filtered_rows.append(row)
            print(f"  过滤 iterative_scan={iterative:<14} P50={row['p50_ms']}ms "
                  f"Recall@{args.top_k}={row['recall']:.3f} 平均返回={row['avg_hits']}/{args.top_k}")

    return {
        "size": total_chunks,
        "document_count": document_count,
        "exact": exact_stats,
        "exact_filtered": filtered_stats,
        "visible_chunks": visible_chunks,
        "build_seconds": build_seconds,
        "hnsw": hnsw_rows,
        "filtered": filtered_rows,
    }


# ---------- 主流程 ----------


async def main() -> None:
    args = parse_args()
    if not 0 < args.filter_ratio <= 1:
        raise SystemExit("--filter-ratio 必须在 (0, 1] 区间")
    sizes = [int(value) for value in args.sizes.split(",") if value.strip()]
    ef_sweep = [int(value) for value in args.ef_search.split(",") if value.strip()]
    if not sizes or not ef_sweep or args.passes < 1:
        raise SystemExit("--sizes / --ef-search 需要至少一个值，--passes 至少为 1")

    # embedding provider 通过环境变量驱动；settings 是 lru_cache，必须清缓存后重置单例
    os.environ["EMBEDDING_PROVIDER"] = args.embedding_provider
    get_settings.cache_clear()
    reset_embedding_client()

    queries = load_queries(args.dataset, args.queries)
    results = []
    try:
        await init_db()
        print(f"计算 {len(queries)} 条查询向量（一次性，不计入检索延迟）…")
        embedding = get_embedding_client()
        query_vectors = [await embedding.embed_one(question) for question in queries]

        largest = max(sizes)
        for size in sizes:
            results.append(await measure_size(
                size, args, ef_sweep, query_vectors, run_ef_sweep=(size == largest)
            ))

        report = render_report(args, ef_sweep, results)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
            print(f"\n报告已写入 {args.output}")
        else:
            print("\n" + report)
    finally:
        if not args.keep:
            await cleanup()
            print("基准数据已清理（--keep 可保留）")
        await close_db()


def render_report(args, ef_sweep: list[int], results: list[dict]) -> str:
    k = args.top_k
    settings = get_settings()
    default_ef = ef_sweep[len(ef_sweep) // 2]
    largest = max(results, key=lambda item: item["size"])
    lines = [
        "# 向量检索基准：精确扫描 vs pgvector HNSW",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 切片规模 | {', '.join(str(r['size']) for r in results)} |",
        f"| 查询数 | {args.queries}（来自 `evals/rag_eval_dataset.jsonl`） |",
        f"| embedding | `{args.embedding_provider}`（维度 {settings.embedding_dim}） |",
        f"| 索引参数 | m={settings.rag_hnsw_m}, ef_construction={settings.rag_hnsw_ef_construction} |",
        "| pgvector | 0.8+（`hnsw.iterative_scan` 需要 0.8.0） |",
        "",
        "> 延迟只统计数据库检索（查询向量预先算好，不含 embedding 推理）。",
        f"> 每个配置跑 {args.passes} 轮、取每查询最小值再算分位数：本机 Docker VM 有其他容器",
        "> 抢 CPU，单次采样会被 10ms 级噪声污染。噪声只会让结果偏慢，不会偏快。",
        "",
        f"## 1. 规模扩展：精确扫描 O(N) vs HNSW（ef_search={default_ef}）",
        "",
        f"| 切片数 | 精确 P50 (ms) | 精确 P95 (ms) | HNSW P50 (ms) | HNSW P95 (ms) | P95 加速 | Recall@{k} | 建索引 (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        hnsw = next((row for row in result["hnsw"] if row["ef_search"] == default_ef), result["hnsw"][0])
        speedup = result["exact"]["p95_ms"] / hnsw["p95_ms"] if hnsw["p95_ms"] else float("inf")
        lines.append(
            f"| {result['size']} | {result['exact']['p50_ms']} | {result['exact']['p95_ms']} | "
            f"{hnsw['p50_ms']} | {hnsw['p95_ms']} | {speedup:.1f}× | {hnsw['recall']:.3f} | "
            f"{result['build_seconds']:.2f} |"
        )
    lines += [
        "",
        "规模每 ×10，精确扫描延迟随之线性增长（全表顺序扫描 + 排序），HNSW 基本持平：",
        "索引查询代价主要跟图和候选队列有关，不随表大小线性增长。",
        "",
        f"## 2. ef_search 曲线（规模 {largest['size']}，Recall@{k}）",
        "",
        f"| ef_search | Recall@{k} | P50 (ms) | P95 (ms) | min (ms) |",
        "|---|---|---|---|---|",
    ]
    for row in largest["hnsw"]:
        lines.append(
            f"| {row['ef_search']} | {row['recall']:.3f} | {row['p50_ms']} | {row['p95_ms']} | {row['min_ms']} |"
        )
    if largest["filtered"]:
        lines += [
            "",
            f"## 3. 带过滤检索（模拟 owner / 权限过滤，ef_search={default_ef}）",
            "",
            f"可见切片 {largest['visible_chunks']}/{largest['size']}；"
            f"精确扫描基线 P50={largest['exact_filtered']['p50_ms']}ms",
            "",
            f"| iterative_scan | Recall@{k} | 平均返回 | P50 (ms) | P95 (ms) |",
            "|---|---|---|---|---|",
        ]
        for row in largest["filtered"]:
            lines.append(
                f"| {row['iterative_scan']} | {row['recall']:.3f} | {row['avg_hits']}/{k} | "
                f"{row['p50_ms']} | {row['p95_ms']} |"
            )
        lines += [
            "",
            "过滤性强时 HNSW 只取 `ef_search` 个候选再应用 WHERE，候选不足会让返回条数和召回",
            "一起下降；`hnsw.iterative_scan` 让索引继续往下扫，直到凑够 `LIMIT` 或达到",
            "`hnsw.max_scan_tuples`。",
        ]
    lines += [
        "",
        "## 复现命令",
        "",
        "```bash",
        f".venv/bin/python -m evals.bench_retrieval --sizes {args.sizes} --queries {args.queries} \\",
        f"  --top-k {args.top_k} --passes {args.passes} --embedding-provider {args.embedding_provider} \\",
        f"  --ef-search {args.ef_search} --filter-ratio {args.filter_ratio} \\",
        "  --output evals/retrieval-bench.md",
        "```",
        "",
        "> Recall@K 衡量索引保真度（与精确扫描结果的一致性），不衡量语义相关性；",
        "> 语义质量见 `evals/run_rag_eval.py` 的人工标注证据集。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(main())
