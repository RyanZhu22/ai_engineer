"""FastAPI 入口 - LLM QA Service。

功能：
  - /chat          普通聊天（完整回复，支持 RAG）
  - /chat/stream   流式聊天（SSE，支持 RAG）
  - /history       会话历史 CRUD（PostgreSQL 持久化）
  - /documents     RAG 文档管理：上传 / 列表 / 删除 / 检索
  - /health        健康检查
"""
import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import history, rag
from .config import get_settings
from .db import Document, close_db, get_db, init_db
from .embedding_client import get_embedding_client
from .llm_client import LLMClient, get_llm_client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
    except Exception as e:
        # 数据库不可用时不阻断启动，health 会暴露状态
        print(f"[WARN] 数据库初始化失败（先运行 docker compose up -d）: {e}")
    yield
    await get_llm_client().aclose()
    await get_embedding_client().aclose()
    await close_db()


app = FastAPI(
    title="LLM QA Service",
    description="企业知识库问答服务 - 对标香港 AI 工程师 JD",
    version="0.3.0",
    lifespan=lifespan,
)


# ---------- 请求/响应模型 ----------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="用户问题")
    system_prompt: str = Field(
        default="你是一个专业的中英文双语 AI 助手。回答要准确、简洁、结构清晰。",
        max_length=2000,
    )
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    conversation_id: str | None = Field(default=None, description="会话 ID，留空则新建")
    use_rag: bool = Field(default=False, description="是否检索知识库（RAG）")
    top_k: int = Field(default=4, ge=1, le=20, description="RAG 检索返回的切片数")


class ChatResponse(BaseModel):
    reply: str
    model: str
    conversation_id: str
    sources: list[dict] | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=4, ge=1, le=20)


# ---------- 健康检查 ----------
@app.get("/health")
async def health():
    """liveness/readiness 探针 - 面试必问的 production 概念"""
    settings = get_settings()
    return {
        "status": "UP",
        "service": "llm-qa-service",
        "env": settings.app_env,
        "mode": "mock" if settings.mock_mode else "live",
        "rag": {"documents": await _count_documents()},
    }


async def _count_documents() -> int:
    from .db import get_session_factory
    async with get_session_factory()() as session:
        return len((await session.execute(select(Document.id))).scalars().all())


# ---------- 构建消息上下文 ----------
def _build_messages(system_prompt: str, conv: dict) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    for m in conv["messages"]:
        messages.append({"role": m["role"], "content": m["content"]})
    return messages


# ---------- 普通聊天 ----------
@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    session: AsyncSession = Depends(get_db),
    client: LLMClient = Depends(get_llm_client),
):
    conv = await _get_or_create_conversation(req.conversation_id)
    await history.add_message(conv["id"], "user", req.message)

    system_prompt = req.system_prompt
    sources = None
    if req.use_rag:
        hits = await rag.search_chunks(session, req.message, req.top_k)
        sources = hits
        if hits:
            system_prompt = rag.build_rag_prompt(req.message, hits)

    messages = _build_messages(system_prompt, conv)
    reply = await client.chat(messages, temperature=req.temperature)
    await history.add_message(conv["id"], "assistant", reply)
    return ChatResponse(reply=reply, model=client.model, conversation_id=conv["id"], sources=sources)


# ---------- 流式聊天（SSE）----------
@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    session: AsyncSession = Depends(get_db),
    client: LLMClient = Depends(get_llm_client),
):
    conv = await _get_or_create_conversation(req.conversation_id)
    await history.add_message(conv["id"], "user", req.message)

    system_prompt = req.system_prompt
    sources = None
    if req.use_rag:
        hits = await rag.search_chunks(session, req.message, req.top_k)
        sources = hits
        if hits:
            system_prompt = rag.build_rag_prompt(req.message, hits)

    messages = _build_messages(system_prompt, conv)

    async def event_stream():
        """SSE 格式：data: {json}\n\n，结束时发 [DONE] 事件。"""
        yield f"data: {json.dumps({'type': 'conversation_id', 'id': conv['id']})}\n\n"
        if sources:
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        full_text = []
        async for chunk in client.stream_chat(messages, temperature=req.temperature):
            full_text.append(chunk)
            yield f"data: {json.dumps({'type': 'delta', 'content': chunk})}\n\n"

        await history.add_message(conv["id"], "assistant", "".join(full_text))
        yield f"data: {json.dumps({'type': 'done', 'content': ''.join(full_text)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _get_or_create_conversation(conv_id: str | None) -> dict:
    if conv_id:
        conv = await history.get_conversation(conv_id)
        if not conv:
            raise HTTPException(404, "会话不存在")
        return conv
    return await history.create_conversation()


# ---------- 历史记录 ----------
@app.get("/history")
async def list_history():
    return {"conversations": await history.list_conversations()}


@app.get("/history/{conv_id}")
async def get_history(conv_id: str):
    conv = await history.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    return conv


@app.delete("/history/{conv_id}")
async def delete_history(conv_id: str):
    ok = await history.delete_conversation(conv_id)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return {"deleted": conv_id}


class TruncateRequest(BaseModel):
    keep_messages: int = Field(..., ge=0, description="保留前 N 条消息")


@app.post("/history/{conv_id}/truncate")
async def truncate_history(conv_id: str, req: TruncateRequest):
    """截断会话到前 N 条消息。用于重发/重新生成时避免历史重复。"""
    ok = await history.truncate_conversation(conv_id, req.keep_messages)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return {"truncated": conv_id, "keep_messages": req.keep_messages}


# ---------- RAG：文档管理 ----------
@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
):
    """上传文档（txt/md/pdf），切分 + embedding 入库。"""
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件过大（上限 10MB）")
    try:
        settings = get_settings()
        doc = await rag.index_document(
            session, file.filename, data,
            chunk_size=settings.rag_chunk_size, overlap=settings.rag_chunk_overlap,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    # 重新查询并预加载 chunks（async 下避免 lazy load）
    doc = (
        await session.execute(
            select(Document).options(selectinload(Document.chunks)).where(Document.id == doc.id)
        )
    ).scalar_one()
    return {
        "id": doc.id,
        "title": doc.title,
        "source": doc.source,
        "chunks": len(doc.chunks),
        "embedding_mode": get_embedding_client().mode,
    }


@app.get("/documents")
async def list_documents(session: AsyncSession = Depends(get_db)):
    rows = (
        await session.execute(
            select(Document).options(selectinload(Document.chunks)).order_by(Document.created_at.desc())
        )
    ).scalars().all()
    return {"documents": [
        {"id": d.id, "title": d.title, "source": d.source, "chunks": len(d.chunks), "created_at": d.created_at}
        for d in rows
    ]}


@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: int, session: AsyncSession = Depends(get_db)):
    doc = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "文档不存在")
    await session.delete(doc)  # cascade 删除 chunks
    await session.commit()
    return {"deleted": doc_id}


@app.post("/documents/search")
async def search_documents(req: SearchRequest, session: AsyncSession = Depends(get_db)):
    """RAG 检索调试端点：看给定 query 能召回哪些切片。"""
    hits = await rag.search_chunks(session, req.query, req.top_k)
    return {"query": req.query, "hits": hits}


# ---------- 前端页面 ----------
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
async def index():
    from fastapi.responses import FileResponse
    return FileResponse("app/static/index.html")
