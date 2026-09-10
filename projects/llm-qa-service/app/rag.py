"""RAG 链路：加载 → 切分 → 向量化 → 混合检索 → 生成。

对标 JD：SCMP/Buyandship 都明确要求 RAG 架构（vector databases + RAG）。
技术笔记 docs/technical-notes.md 第 2 节：chunks 表用 pgvector 向量检索。

流程：
  1. upload：解析文档（txt/md/pdf）→ 切分 → embedding → 写入 documents + chunks 表
  2. search：问题 embedding 的向量召回 + 中文 BM25 词法召回 → RRF 融合
  3. chat：检索结果拼入 system prompt → LLM 生成（见 main.py）
"""
import math
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import Chunk, Document
from .embedding_client import get_embedding_client


RetrievalMode = Literal["vector", "hybrid"]

# 没有强制引入中文分词依赖：连续中文文本拆为双字、三字词，英文/数字保留完整词。
# 相比把所有单字都当词，可减少「的、了、天」等泛词对制度类查询排序的干扰。
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_OR_NUMBER = re.compile(r"[a-z0-9]+(?:[._:/-][a-z0-9]+)*")

# ---------- 1. 文档解析 ----------

def parse_document(filename: str, data: bytes) -> str:
    """按扩展名解析文档内容。支持 txt/md/pdf。"""
    suffix = Path(filename).suffix.lower()
    if suffix in (".txt", ".md", ".markdown", ".text"):
        return data.decode("utf-8", errors="replace")
    if suffix == ".pdf":
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    raise ValueError(f"不支持的文档类型: {suffix}（支持 txt/md/pdf）")


# ---------- 2. 切分 ----------

_SENT_BOUNDARY = re.compile(r"(?<=[。！？!?；;.\n])")


def split_sentences(text: str) -> list[str]:
    """按中文/英文句号切句（保留标点）。"""
    parts = [p.strip() for p in _SENT_BOUNDARY.split(text) if p.strip()]
    return parts


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """段落优先 → 句子 → 字符兜底的贪心切分，带 overlap。

    设计：
      - 按段落（空行/换行）切，段落合并到接近 chunk_size，保持语义完整
      - 超长段落按句子切
      - 单句超长按字符硬切（兜底，避免 chunk 无限大）
      - overlap：相邻 chunk 保留上一 chunk 尾部内容，减少检索时语义断裂
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0

    for para in paragraphs:
        if current_len + len(para) + 1 <= chunk_size:
            current.append(para)
            current_len += len(para) + 1
        else:
            flush()
            if len(para) <= chunk_size:
                current.append(para)
                current_len = len(para)
            else:
                # 超长段落：先按句子切，句子再超长就按字符硬切
                for sent in split_sentences(para):
                    if current_len + len(sent) + 1 <= chunk_size:
                        current.append(sent)
                        current_len += len(sent) + 1
                    else:
                        flush()
                        if len(sent) <= chunk_size:
                            current.append(sent)
                            current_len = len(sent)
                        else:
                            for i in range(0, len(sent), chunk_size):
                                chunks.append(sent[i:i + chunk_size])
    flush()

    # 应用 overlap：每个 chunk 开头拼上上一个 chunk 的尾部（除第一个）
    if overlap > 0 and len(chunks) > 1:
        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:]
            result.append(prev_tail + "\n" + chunks[i])
        return result
    return chunks


# ---------- 3. 入库 ----------

async def index_document(
    session: AsyncSession,
    filename: str,
    data: bytes,
    chunk_size: int,
    overlap: int,
    *,
    title: str | None = None,
) -> Document:
    """解析 → 切分 → embedding → 写入 documents + chunks。

    ``title`` 主要供评测等内部调用使用：可以保留人类可读的文档标题，
    同时用带命名空间的 ``filename`` 标记临时数据，避免与用户上传文件冲突。
    """
    import time
    content = parse_document(filename, data)
    chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        raise ValueError("文档没有可索引的内容")

    emb_client = get_embedding_client()
    vectors = await emb_client.embed(chunks)

    doc = Document(title=title or Path(filename).stem, source=filename, created_at=time.time())
    session.add(doc)
    await session.flush()  # 拿到 doc.id

    for i, (text, vec) in enumerate(zip(chunks, vectors)):
        session.add(Chunk(document_id=doc.id, chunk_index=i, content=text, embedding=vec))
    await session.commit()
    await session.refresh(doc)
    return doc


# ---------- 4. 检索 ----------

def tokenize_for_bm25(text: str) -> list[str]:
    """把中英文文本转换成无需外部字典的 BM25 token。

    中文没有空格，因此保留相邻双字、三字词；英文、数字、版本号等保留为完整 token。
    这不是替代专业中文分词器的通用方案，但对当前中小型企业制度库有稳定、零依赖的词法召回。
    """
    normalized = text.lower()
    tokens: list[str] = []
    for match in _CJK_RUN.finditer(normalized):
        run = match.group(0)
        if len(run) == 1:
            tokens.append(run)
            continue
        for width in (2, 3):
            tokens.extend(run[index:index + width] for index in range(len(run) - width + 1))
    tokens.extend(_LATIN_OR_NUMBER.findall(normalized))
    return tokens


def bm25_scores(
    query: str,
    documents: Sequence[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """计算 query 对每个文档的 Okapi BM25 分数。

    该实现留在进程内，便于当前项目在不额外部署搜索服务时获得词法召回；数据库规模
    明显增长后，应迁移到带中文分析器的 OpenSearch / Elasticsearch 或专用 BM25 索引。
    """
    if not documents:
        return []
    if k1 <= 0 or not 0 <= b <= 1:
        raise ValueError("BM25 参数要求 k1 > 0 且 0 <= b <= 1")

    query_terms = Counter(tokenize_for_bm25(query))
    if not query_terms:
        return [0.0] * len(documents)

    tokenized_documents = [tokenize_for_bm25(document) for document in documents]
    document_lengths = [len(tokens) for tokens in tokenized_documents]
    average_length = sum(document_lengths) / len(document_lengths)
    if average_length == 0:
        return [0.0] * len(documents)

    document_frequency: Counter[str] = Counter()
    for tokens in tokenized_documents:
        document_frequency.update(set(tokens))

    scores: list[float] = []
    total_documents = len(documents)
    for tokens, length in zip(tokenized_documents, document_lengths):
        frequencies = Counter(tokens)
        score = 0.0
        length_normalizer = k1 * (1 - b + b * length / average_length)
        for term, query_frequency in query_terms.items():
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            # Robertson / Sparck Jones IDF，log1p 保证极高频词也不会给出负分。
            idf = math.log1p(
                (total_documents - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            score += query_frequency * idf * (frequency * (k1 + 1)) / (frequency + length_normalizer)
        scores.append(score)
    return scores


def reciprocal_rank_fusion(
    vector_hits: Sequence[dict[str, Any]],
    bm25_hits: Sequence[dict[str, Any]],
    *,
    sentence_bm25_hits: Sequence[dict[str, Any]] = (),
    rrf_k: int = 60,
    vector_weight: float = 1.0,
    bm25_weight: float = 1.0,
    sentence_bm25_weight: float = 1.0,
) -> list[dict[str, Any]]:
    """用 Reciprocal Rank Fusion 融合向量、chunk BM25 与句级 BM25 三路候选。

    RRF 只使用排名，不直接混合余弦相似度和 BM25 的不可比数值范围；同时命中两路的
    chunk 会被提升。输入 hit 需含内部 ``chunk_id``，返回值仍保留该字段供调用方序列化。
    """
    if rrf_k < 1:
        raise ValueError("RRF 参数 rrf_k 必须至少为 1")
    if min(vector_weight, bm25_weight, sentence_bm25_weight) <= 0:
        raise ValueError("RRF 的各路权重必须大于 0")

    fused: dict[int, dict[str, Any]] = {}

    def add_hits(hits: Sequence[dict[str, Any]], source: str, weight: float) -> None:
        for rank, hit in enumerate(hits, start=1):
            chunk_id = int(hit["chunk_id"])
            entry = fused.get(chunk_id)
            if entry is None:
                entry = {
                    **hit,
                    "score": 0.0,
                    "vector_rank": None,
                    "bm25_rank": None,
                    "sentence_bm25_rank": None,
                    "vector_score": None,
                    "bm25_score": None,
                    "sentence_bm25_score": None,
                }
                fused[chunk_id] = entry
            entry["score"] += weight / (rrf_k + rank)
            if source == "vector":
                entry["vector_rank"] = rank
                entry["vector_score"] = float(hit["score"])
            elif source == "bm25":
                entry["bm25_rank"] = rank
                entry["bm25_score"] = float(hit["score"])
            else:
                entry["sentence_bm25_rank"] = rank
                entry["sentence_bm25_score"] = float(hit["score"])

    add_hits(vector_hits, "vector", vector_weight)
    add_hits(bm25_hits, "bm25", bm25_weight)
    add_hits(sentence_bm25_hits, "sentence_bm25", sentence_bm25_weight)

    missing_rank = float("inf")
    return sorted(
        fused.values(),
        key=lambda hit: (
            -float(hit["score"]),
            min(
                hit["vector_rank"] or missing_rank,
                hit["bm25_rank"] or missing_rank,
                hit["sentence_bm25_rank"] or missing_rank,
            ),
            hit["vector_rank"] or missing_rank,
            hit["bm25_rank"] or missing_rank,
            hit["sentence_bm25_rank"] or missing_rank,
            int(hit["chunk_id"]),
        ),
    )


async def apply_hnsw_search_settings(session: AsyncSession, ef_search: int | None = None) -> None:
    """在事务内覆盖 HNSW 查询参数（SET LOCAL，事务结束自动失效，不污染连接池）。

    应用正常请求路径依赖连接建立时设置的会话默认值（见 db._apply_vector_session_defaults），
    因此这个函数只给需要“同一批查询用不同参数对比”的场景用：检索调试端点与基准脚本。

    - ``ef_search``：候选队列大小，召回/延迟的运行时旋钮
    - ``iterative_scan``：带 WHERE 过滤时继续往下扫索引，修复“过滤后候选不足”
    """
    settings = get_settings()
    if ef_search is not None:
        if not 1 <= ef_search <= 1000:
            raise ValueError("ef_search 必须在 1 到 1000 之间")
    # 事务外的 SET LOCAL 会被 Postgres 忽略并告警，所以先确保处于事务中。
    if not session.in_transaction():
        await session.begin()
    # 参数已经过上面的范围校验 / 来自 Literal 配置，不存在注入面。
    if ef_search is not None:
        await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
    await session.execute(text(f"SET LOCAL hnsw.iterative_scan = {settings.rag_hnsw_iterative_scan}"))
    await session.execute(text(f"SET LOCAL hnsw.max_scan_tuples = {int(settings.rag_hnsw_max_scan_tuples)}"))


async def search_chunks(
    session: AsyncSession,
    query: str,
    top_k: int = 4,
    document_ids: Sequence[int] | None = None,
    retrieval_mode: RetrievalMode | None = None,
    ef_search: int | None = None,
) -> list[dict[str, Any]]:
    """检索知识库片段，支持 ``vector`` 与默认 ``hybrid`` 两种模式。

    ``hybrid`` 先各取向量和 BM25 候选，再用 RRF 融合，避免直接比较余弦相似度与 BM25
    分数。``document_ids`` 仅供内部调用限定范围（例如离线评测）；公开 API 不传时搜索
    全部文档。
    """
    if top_k < 1:
        raise ValueError("top_k 必须至少为 1")
    if document_ids is not None and not document_ids:
        return []

    settings = get_settings()
    mode = retrieval_mode or settings.rag_retrieval_mode
    if mode not in ("vector", "hybrid"):
        raise ValueError("retrieval_mode 必须是 vector 或 hybrid")

    scope = list(document_ids) if document_ids is not None else None
    # 正常路径不额外发 SET：会话默认值已在连接建立时设好，这里只处理显式覆盖。
    if ef_search is not None:
        await apply_hnsw_search_settings(session, ef_search)
    vector_limit = max(top_k, settings.rag_vector_candidate_k)
    vector_hits = await _search_vector_candidates(session, query, limit=vector_limit, document_ids=scope)
    if mode == "vector":
        return [_serialize_hit(hit, retrieval_mode="vector") for hit in vector_hits[:top_k]]

    bm25_limit = max(top_k, settings.rag_bm25_candidate_k)
    bm25_hits = await _search_bm25_candidates(session, query, limit=bm25_limit, document_ids=scope)
    sentence_bm25_hits = rerank_by_best_sentence_bm25(
        query,
        _merge_candidates(vector_hits, bm25_hits),
    )
    fused_hits = reciprocal_rank_fusion(
        vector_hits,
        bm25_hits,
        sentence_bm25_hits=sentence_bm25_hits,
        rrf_k=settings.rag_rrf_k,
        vector_weight=settings.rag_vector_weight,
        bm25_weight=settings.rag_bm25_weight,
        sentence_bm25_weight=settings.rag_sentence_bm25_weight,
    )
    return [_serialize_hit(hit, retrieval_mode="hybrid") for hit in fused_hits[:top_k]]


async def _search_vector_candidates(
    session: AsyncSession,
    query: str,
    *,
    limit: int,
    document_ids: Sequence[int] | None,
) -> list[dict[str, Any]]:
    q_vec = await get_embedding_client().embed_one(query)
    return await vector_candidates(session, q_vec, limit=limit, document_ids=document_ids)


async def vector_candidates(
    session: AsyncSession,
    q_vec: Sequence[float],
    *,
    limit: int,
    document_ids: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """用已有查询向量做 ANN 检索。

    单独抽出来是为了让基准脚本能把 embedding 耗时和“数据库检索耗时”分开度量——
    比较索引效果时，把模型推理时间混进来会污染结论。
    """
    # cosine_distance 越小越相似（pgvector 的 <=> 算子）；score 在 SQL 端计算。
    # 该 ORDER BY 与索引的 vector_cosine_ops 算子类匹配，HNSW 索引才会被使用。
    stmt = (
        select(Chunk, Document.title, (1 - Chunk.embedding.cosine_distance(q_vec)).label("score"))
        .join(Document, Chunk.document_id == Document.id)
        .order_by(Chunk.embedding.cosine_distance(q_vec))
        .limit(limit)
    )
    if document_ids is not None:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    rows = (await session.execute(stmt)).all()
    return _dedupe_candidates([
        {
            "chunk_id": chunk.id,
            "content": chunk.content,
            "document_id": chunk.document_id,
            "document_title": title,
            "score": float(score),
        }
        for chunk, title, score in rows
    ])


async def _search_bm25_candidates(
    session: AsyncSession,
    query: str,
    *,
    limit: int,
    document_ids: Sequence[int] | None,
) -> list[dict[str, Any]]:
    """读取当前知识库范围内的 chunk 并计算 BM25 候选。"""
    stmt = (
        select(Chunk, Document.title)
        .join(Document, Chunk.document_id == Document.id)
        .order_by(Chunk.id)
    )
    if document_ids is not None:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    rows = (await session.execute(stmt)).all()
    candidates = _dedupe_candidates([
        {
            "chunk_id": chunk.id,
            "content": chunk.content,
            "document_id": chunk.document_id,
            "document_title": title,
            "score": 0.0,
        }
        for chunk, title in rows
    ])
    scores = bm25_scores(query, [candidate["content"] for candidate in candidates])
    ranked = [
        {**candidate, "score": score}
        for candidate, score in zip(candidates, scores)
        if score > 0
    ]
    ranked.sort(key=lambda hit: (-float(hit["score"]), int(hit["chunk_id"])))
    return ranked[:limit]


def _dedupe_candidates(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """保持原始排序去除重叠/重复上传带来的相同内容。"""
    seen: set[str] = set()
    deduplicated: list[dict[str, Any]] = []
    for candidate in candidates:
        content = str(candidate["content"])
        if content in seen:
            continue
        seen.add(content)
        deduplicated.append(candidate)
    return deduplicated


def _merge_candidates(*candidate_lists: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 chunk ID 合并多路候选，保留首次出现时的完整元数据。"""
    merged: dict[int, dict[str, Any]] = {}
    for candidates in candidate_lists:
        for candidate in candidates:
            merged.setdefault(int(candidate["chunk_id"]), candidate)
    return list(merged.values())


def rerank_by_best_sentence_bm25(
    query: str,
    candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按候选 chunk 内最相关的事实句进行轻量 rerank。

    chunk 往往包含章节标题和多个制度条目。若只对整块计算 BM25，短标题如“差旅报销”
    容易压过真正包含金额或时限的句子。这里仅在向量/BM25 的候选并集内重算，不扫描
    全库，因此是低成本的第二阶段排序，而不是额外的在线模型依赖。
    """
    sentence_pairs: list[tuple[int, str]] = []
    for candidate_index, candidate in enumerate(candidates):
        sentences = [
            sentence
            for sentence in split_sentences(str(candidate["content"]))
            if not sentence.lstrip().startswith("#")
        ]
        # 极端情况下一个 chunk 只有标题，保留全文作为兜底，避免静默丢掉候选。
        if not sentences:
            sentences = [str(candidate["content"])]
        sentence_pairs.extend((candidate_index, sentence) for sentence in sentences)

    sentence_scores = bm25_scores(query, [sentence for _, sentence in sentence_pairs])
    best_scores: dict[int, float] = {}
    for (candidate_index, _), score in zip(sentence_pairs, sentence_scores):
        best_scores[candidate_index] = max(best_scores.get(candidate_index, 0.0), score)

    ranked = [
        {**candidate, "score": best_scores.get(index, 0.0)}
        for index, candidate in enumerate(candidates)
        if best_scores.get(index, 0.0) > 0
    ]
    ranked.sort(key=lambda hit: (-float(hit["score"]), int(hit["chunk_id"])))
    return ranked


def _serialize_hit(hit: dict[str, Any], *, retrieval_mode: RetrievalMode) -> dict[str, Any]:
    """移除内部 chunk ID，并显式说明当前分数语义。"""
    result: dict[str, Any] = {
        "content": hit["content"],
        "document_id": hit["document_id"],
        "document_title": hit["document_title"],
        "score": round(float(hit["score"]), 6),
        "retrieval_mode": retrieval_mode,
    }
    if retrieval_mode == "hybrid":
        result.update({
            "vector_rank": hit.get("vector_rank"),
            "bm25_rank": hit.get("bm25_rank"),
            "sentence_bm25_rank": hit.get("sentence_bm25_rank"),
            "vector_score": _round_or_none(hit.get("vector_score")),
            "bm25_score": _round_or_none(hit.get("bm25_score")),
            "sentence_bm25_score": _round_or_none(hit.get("sentence_bm25_score")),
        })
    return result


def _round_or_none(value: Any, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


# ---------- 5. 生成 ----------

def build_rag_prompt(query: str, hits: list[dict]) -> str:
    """把检索结果拼成 system prompt 的知识上下文。

    提示词设计（面试可讲）：
      - 明确"仅基于资料回答"：防止模型用训练记忆编造
      - 附上来源标题：可追溯（cite）
      - 找不到答案要明说：避免幻觉
    """
    context = "\n\n".join(
        f"[资料{i + 1}]（来自《{h['document_title']}》）\n{h['content']}"
        for i, h in enumerate(hits)
    )
    return (
        "你是一个企业知识库问答助手。请**仅基于下面的资料**回答用户问题，"
        "回答时在末尾用 [资料1] [资料2] 标注依据来源。\n"
        "如果资料中没有相关信息，直接说明'知识库中没有找到相关内容'，不要编造。\n\n"
        f"【知识库资料】\n{context}\n"
    )
