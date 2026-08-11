"""RAG 链路：加载 → 切分 → 向量化 → 检索 → 生成。

对标 JD：SCMP/Buyandship 都明确要求 RAG 架构（vector databases + RAG）。
技术笔记 docs/technical-notes.md 第 2 节：chunks 表用 pgvector 向量检索。

流程：
  1. upload：解析文档（txt/md/pdf）→ 切分 → embedding → 写入 documents + chunks 表
  2. search：问题 embedding → pgvector 余弦距离 top-k 检索
  3. chat：检索结果拼入 system prompt → LLM 生成（见 main.py）
"""
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db import Chunk, Document
from .embedding_client import get_embedding_client

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
) -> Document:
    """解析 → 切分 → embedding → 写入 documents + chunks。"""
    import time
    content = parse_document(filename, data)
    chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        raise ValueError("文档没有可索引的内容")

    emb_client = get_embedding_client()
    vectors = await emb_client.embed(chunks)

    doc = Document(title=Path(filename).stem, source=filename, created_at=time.time())
    session.add(doc)
    await session.flush()  # 拿到 doc.id

    for i, (text, vec) in enumerate(zip(chunks, vectors)):
        session.add(Chunk(document_id=doc.id, chunk_index=i, content=text, embedding=vec))
    await session.commit()
    await session.refresh(doc)
    return doc


# ---------- 4. 检索 ----------

async def search_chunks(
    session: AsyncSession,
    query: str,
    top_k: int = 4,
) -> list[dict]:
    """pgvector 余弦距离检索，返回 [{content, document_id, document_title, score}]。"""
    emb_client = get_embedding_client()
    q_vec = await emb_client.embed_one(query)

    # cosine_distance 越小越相似（pgvector 的 <=> 算子）；score 在 SQL 端计算
    stmt = (
        select(Chunk, Document.title, (1 - Chunk.embedding.cosine_distance(q_vec)).label("score"))
        .join(Document, Chunk.document_id == Document.id)
        .order_by(Chunk.embedding.cosine_distance(q_vec))
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()
    # 按内容去重：同一文档重复上传/overlap 会导致检索到重复片段
    seen: set[str] = set()
    result = []
    for chunk, title, score in rows:
        if chunk.content in seen:
            continue
        seen.add(chunk.content)
        result.append({
            "content": chunk.content,
            "document_id": chunk.document_id,
            "document_title": title,
            "score": round(score, 4),
        })
    return result


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
