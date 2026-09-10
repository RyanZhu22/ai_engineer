"""FastAPI 入口 - LLM QA Service。

功能：
  - /auth          密码登录、当前账号和退出登录
  - /chat          普通聊天（完整回复，支持 RAG）
  - /chat/stream   流式聊天（SSE，支持 RAG）
  - /history       会话历史 CRUD（PostgreSQL 持久化）
  - /documents     RAG 文档管理：上传 / 列表 / 删除 / 检索
  - /health        健康检查
"""
import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, Request
from .auth import AuthenticationMiddleware, router as auth_router, require_mcp
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, history, rag
from .config import get_settings
from .db import Document, close_db, get_db, init_db
from .embedding_client import get_embedding_client
from .llm_client import LLMClient, get_llm_client
from .mcp_client import MCPConfigurationError, MCPToolProvider
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
    version="0.5.0",
    lifespan=lifespan,
)
app.add_middleware(AuthenticationMiddleware)
app.include_router(auth_router)


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
    # 调试用：临时覆盖 HNSW 候选队列大小，对比不同 ef_search 下的召回与延迟。
    # 留空则用服务端配置的默认值（rag_hnsw_ef_search）。
    ef_search: int | None = Field(default=None, ge=1, le=1000)


# ---------- Agent（tool calling）----------
AGENT_SYSTEM_PROMPT = (
    "你是一个企业 AI 助手，能自主决定是否调用工具来准确回答问题。"
    "可用工具包括：检索知识库、计算器、查询当前时间，以及在启用时由 MCP server 提供的已批准工具。"
    "优先用工具获取准确信息，再基于结果回答；回答要简洁、注明依据。"
)


class AgentRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="用户问题")
    conversation_id: str | None = Field(default=None, description="会话 ID，留空则新建")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    max_iterations: int = Field(default=5, ge=1, le=10, description="工具调用最大轮数")
    use_mcp: bool = Field(default=False, description="是否接入已配置且允许的 MCP 工具")


class AgentResponse(BaseModel):
    reply: str
    model: str
    conversation_id: str
    tool_calls: list[dict]
    iterations: int
    mcp_tools: list[str] = []


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
    }


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
    conv = await _add_user_message(conv["id"], req.message)

    system_prompt = req.system_prompt
    sources = None
    if req.use_rag:
        hits = await rag.search_chunks(session, req.message, req.top_k)
        sources = hits
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
    conv = await _add_user_message(conv["id"], req.message)

    system_prompt = req.system_prompt
    sources = None
    if req.use_rag:
        hits = await rag.search_chunks(session, req.message, req.top_k)
        sources = hits
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


async def _add_user_message(conv_id: str, message: str) -> dict:
    """写入用户消息并重新读取会话（返回含最新消息的 dict）。

    原因：create_conversation() 返回的是无消息的快照，直接 add_message 后
    conv['messages'] 仍是旧数据，会导致新会话的第一条用户消息没传给 LLM。
    """
    await history.add_message(conv_id, "user", message)
    return await history.get_conversation(conv_id)


# ---------- Agent 问答 ----------
@app.post("/agent", response_model=AgentResponse)
async def agent_chat(
    req: AgentRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    client: LLMClient = Depends(get_llm_client),
):
    """Agent 问答：模型自主决定是否调用工具（检索/计算/查时间），循环直到给出最终回答。"""
    require_mcp(request, req.use_mcp)
    conv = await _get_or_create_conversation(req.conversation_id)
    conv = await _add_user_message(conv["id"], req.message)

    messages = _build_messages(AGENT_SYSTEM_PROMPT, conv)
    try:
        async with MCPToolProvider.from_settings(enabled=req.use_mcp) as mcp_provider:
            runner = agent.Agent(client, agent.build_default_tools(session) + mcp_provider.tools)
            result = await runner.run(messages, temperature=req.temperature, max_iterations=req.max_iterations)
            mcp_tools = [tool.name for tool in mcp_provider.tools]
    except MCPConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    await history.add_message(conv["id"], "assistant", result.answer)

    return AgentResponse(
        reply=result.answer,
        model=client.model,
        conversation_id=conv["id"],
        tool_calls=result.tool_calls,
        iterations=result.iterations,
        mcp_tools=mcp_tools,
    )


@app.post("/agent/stream")
async def agent_stream(
    req: AgentRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    client: LLMClient = Depends(get_llm_client),
):
    """Agent 问答（SSE）：逐事件推送工具调用过程 + 最终回答。

    事件类型：
      - conversation_id：会话 ID
      - tool_call：模型决定调用某个工具（name/arguments/result）
      - delta：最终回答（agent 循环结束后一次性给出）
      - done：结束
    """
    require_mcp(request, req.use_mcp)
    conv = await _get_or_create_conversation(req.conversation_id)
    conv = await _add_user_message(conv["id"], req.message)
    messages = _build_messages(AGENT_SYSTEM_PROMPT, conv)

    async def event_stream():
        yield f"data: {json.dumps({'type': 'conversation_id', 'id': conv['id']})}\n\n"
        try:
            async with MCPToolProvider.from_settings(enabled=req.use_mcp) as mcp_provider:
                if mcp_provider.tools:
                    yield f"data: {json.dumps({'type': 'mcp_tools', 'tools': [tool.name for tool in mcp_provider.tools]}, ensure_ascii=False)}\n\n"
                runner = agent.Agent(client, agent.build_default_tools(session) + mcp_provider.tools)
                async for step in runner.iter_steps(messages, temperature=req.temperature, max_iterations=req.max_iterations):
                    if step["kind"] == "tool_call":
                        yield f"data: {json.dumps({'type': 'tool_call', 'name': step['name'], 'arguments': step['arguments'], 'result': step['result']}, ensure_ascii=False)}\n\n"
                    else:
                        answer = step["answer"]
                        await history.add_message(conv["id"], "assistant", answer)
                        yield f"data: {json.dumps({'type': 'delta', 'content': answer}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'type': 'done', 'content': answer}, ensure_ascii=False)}\n\n"
        except MCPConfigurationError as exc:
            message = f"MCP 不可用：{exc}"
            yield f"data: {json.dumps({'type': 'error', 'content': message}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'content': message}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/mcp/tools")
async def list_mcp_tools(request: Request):
    """列出部署者 allow-list 中可被 Agent 使用的 MCP 工具（不执行工具）。"""
    require_mcp(request, True)
    try:
        async with MCPToolProvider.from_settings(enabled=True) as provider:
            return {
                "servers": provider.server_tools,
                "tools": [
                    {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
                    for tool in provider.tools
                ],
            }
    except MCPConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc


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
    """RAG 检索调试端点：看给定 query 能召回哪些切片。

    传 ``ef_search`` 可以现场对比不同 HNSW 候选队列大小的效果，返回体会带实际生效值。
    """
    hits = await rag.search_chunks(session, req.query, req.top_k, ef_search=req.ef_search)
    settings = get_settings()
    return {
        "query": req.query,
        "hits": hits,
        "hnsw": {
            "ef_search": req.ef_search or settings.rag_hnsw_ef_search,
            "iterative_scan": settings.rag_hnsw_iterative_scan,
        },
    }


# ---------- 前端页面 ----------
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
async def index():
    from fastapi.responses import FileResponse
    return FileResponse("app/static/index.html")
