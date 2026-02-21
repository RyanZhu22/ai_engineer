from contextlib import asynccontextmanager
from time import perf_counter
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .ask_cache import AskCache
from .config import (
    LLM_PROVIDER,
    RAG_ASK_CACHE_ENABLED,
    RAG_ASK_CACHE_MAX_ITEMS,
    RAG_ASK_CACHE_TTL_SEC,
    RAG_BATCH_SIZE,
    RAG_DEFAULT_TOP_K,
    RAG_DOCS_DIR,
    RAG_EMBED_MODEL,
    RAG_LOG_PATH,
    RAG_METRICS_MAX_RECENT,
    RAG_PROMPT_STYLE_DEFAULT,
    RAG_SOURCE_MAX_CHARS,
)
from .llm import LLMError, generate_with_context
from .retriever import SearchHit, VectorRetriever
from .telemetry import TelemetryStore


def _to_hit_out(hit: SearchHit, max_chars: int) -> "HitOut":
    text = hit.chunk.text.replace("\n", " ")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "..."

    return HitOut(
        doc_name=hit.chunk.doc_name,
        chunk_id=hit.chunk.chunk_id,
        score=round(hit.score, 6),
        text=text,
    )


def _to_context_block(hit: SearchHit) -> str:
    return f"[{hit.chunk.doc_name}#chunk{hit.chunk.chunk_id}] {hit.chunk.text}"


def _ask_cache_key(question: str, top_k: int, prompt_style: str) -> str:
    return f"{LLM_PROVIDER}|{prompt_style}|{top_k}|{question.strip()}"


def _normalize_prompt_style(prompt_style: str | None) -> str:
    style = (prompt_style or RAG_PROMPT_STYLE_DEFAULT).strip().lower()
    return style if style in {"v1", "v2"} else RAG_PROMPT_STYLE_DEFAULT


def _citations_from_hits(hits: List[SearchHit]) -> List[str]:
    return [f"{hit.chunk.doc_name}#chunk{hit.chunk.chunk_id}" for hit in hits]


def _confidence_from_hits(hits: List[SearchHit]) -> str:
    if not hits:
        return "low"
    top_score = hits[0].score
    if top_score >= 0.75:
        return "high"
    if top_score >= 0.55:
        return "medium"
    return "low"


@asynccontextmanager
async def lifespan(app: FastAPI):
    retriever = VectorRetriever(
        docs_dir=RAG_DOCS_DIR,
        model_name=RAG_EMBED_MODEL,
        batch_size=RAG_BATCH_SIZE,
    )
    retriever.build()
    app.state.retriever = retriever
    app.state.telemetry = TelemetryStore(
        log_path=RAG_LOG_PATH,
        max_recent=RAG_METRICS_MAX_RECENT,
    )
    app.state.ask_cache = (
        AskCache(max_items=RAG_ASK_CACHE_MAX_ITEMS, ttl_sec=RAG_ASK_CACHE_TTL_SEC)
        if RAG_ASK_CACHE_ENABLED
        else None
    )
    yield


app = FastAPI(title="Day3 RAG API", version="0.1.0", lifespan=lifespan)


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=RAG_DEFAULT_TOP_K, ge=1, le=20)


class AskIn(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=RAG_DEFAULT_TOP_K, ge=1, le=20)
    prompt_style: str | None = Field(default=None)


class HitOut(BaseModel):
    doc_name: str
    chunk_id: int
    score: float
    text: str


class SearchOut(BaseModel):
    query: str
    hits: List[HitOut]


class AskOut(BaseModel):
    provider: str
    question: str
    prompt_style: str
    answer: str
    confidence: str
    grounded: bool
    citations: List[str]
    sources: List[HitOut]


@app.get("/health")
async def health():
    retriever: VectorRetriever = app.state.retriever
    ask_cache: AskCache | None = app.state.ask_cache
    return {
        "status": "ok",
        "provider": LLM_PROVIDER,
        "docs_dir": str(RAG_DOCS_DIR),
        "embed_model": RAG_EMBED_MODEL,
        "prompt_style_default": RAG_PROMPT_STYLE_DEFAULT,
        "doc_count": retriever.doc_count,
        "chunk_count": retriever.chunk_count,
        "ask_cache_enabled": bool(ask_cache),
    }


@app.get("/metrics/summary")
async def metrics_summary():
    telemetry: TelemetryStore = app.state.telemetry
    ask_cache: AskCache | None = app.state.ask_cache
    payload = telemetry.summary()
    payload["ask_cache_config"] = {
        "enabled": bool(ask_cache),
        "ttl_sec": RAG_ASK_CACHE_TTL_SEC if ask_cache else 0,
        "max_items": RAG_ASK_CACHE_MAX_ITEMS if ask_cache else 0,
    }
    payload["ask_cache_store"] = ask_cache.stats() if ask_cache else {"enabled": False}
    payload["prompt_style_default"] = RAG_PROMPT_STYLE_DEFAULT
    return payload


@app.post("/search", response_model=SearchOut)
async def search_endpoint(body: SearchIn):
    telemetry: TelemetryStore = app.state.telemetry
    start_ts = perf_counter()
    status_code = 200
    error = ""
    hits: List[SearchHit] = []

    try:
        hits = app.state.retriever.search(body.query, body.top_k)
    except ValueError as exc:
        status_code = 400
        error = str(exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        latency_ms = (perf_counter() - start_ts) * 1000
        telemetry.record(
            endpoint="/search",
            status_code=status_code,
            latency_ms=latency_ms,
            provider=LLM_PROVIDER,
            query=body.query,
            top_k=body.top_k,
            source_docs=[hit.chunk.doc_name for hit in hits],
            prompt_style="",
            cache_hit=False,
            error=error,
        )

    return {
        "query": body.query,
        "hits": [_to_hit_out(hit, RAG_SOURCE_MAX_CHARS) for hit in hits],
    }


@app.post("/ask", response_model=AskOut)
async def ask_endpoint(body: AskIn):
    telemetry: TelemetryStore = app.state.telemetry
    ask_cache: AskCache | None = app.state.ask_cache
    effective_prompt_style = _normalize_prompt_style(body.prompt_style)
    start_ts = perf_counter()
    status_code = 200
    error = ""
    cache_hit = False
    hits: List[SearchHit] = []
    source_docs_for_log: List[str] = []
    response_payload: Dict[str, object] = {}

    try:
        if ask_cache:
            key = _ask_cache_key(body.question, body.top_k, effective_prompt_style)
            cached_payload = ask_cache.get(key)
            if cached_payload:
                cache_hit = True
                response_payload = cached_payload
                source_docs_for_log = [
                    str(item.get("doc_name", ""))
                    for item in cached_payload.get("sources", [])
                    if isinstance(item, dict)
                ]
                response_payload.setdefault("prompt_style", effective_prompt_style)
                response_payload.setdefault("confidence", "medium")
                response_payload.setdefault("grounded", bool(response_payload.get("sources")))
                response_payload.setdefault(
                    "citations",
                    [
                        f"{str(item.get('doc_name', ''))}#chunk{int(item.get('chunk_id', 0))}"
                        for item in response_payload.get("sources", [])
                        if isinstance(item, dict)
                    ],
                )
            else:
                hits = app.state.retriever.search(body.question, body.top_k)
                context_blocks = [_to_context_block(hit) for hit in hits]
                answer = await generate_with_context(
                    body.question,
                    context_blocks,
                    effective_prompt_style,
                )
                sources = [_to_hit_out(hit, RAG_SOURCE_MAX_CHARS).model_dump() for hit in hits]
                source_docs_for_log = [hit.chunk.doc_name for hit in hits]
                citations = _citations_from_hits(hits)
                response_payload = {
                    "provider": LLM_PROVIDER,
                    "question": body.question,
                    "prompt_style": effective_prompt_style,
                    "answer": answer,
                    "confidence": _confidence_from_hits(hits),
                    "grounded": bool(citations),
                    "citations": citations,
                    "sources": sources,
                }
                ask_cache.set(key, response_payload)
        else:
            hits = app.state.retriever.search(body.question, body.top_k)
            context_blocks = [_to_context_block(hit) for hit in hits]
            answer = await generate_with_context(
                body.question,
                context_blocks,
                effective_prompt_style,
            )
            sources = [_to_hit_out(hit, RAG_SOURCE_MAX_CHARS).model_dump() for hit in hits]
            source_docs_for_log = [hit.chunk.doc_name for hit in hits]
            citations = _citations_from_hits(hits)
            response_payload = {
                "provider": LLM_PROVIDER,
                "question": body.question,
                "prompt_style": effective_prompt_style,
                "answer": answer,
                "confidence": _confidence_from_hits(hits),
                "grounded": bool(citations),
                "citations": citations,
                "sources": sources,
            }
    except (ValueError, LLMError) as exc:
        status_code = 400
        error = str(exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        latency_ms = (perf_counter() - start_ts) * 1000
        telemetry.record(
            endpoint="/ask",
            status_code=status_code,
            latency_ms=latency_ms,
            provider=LLM_PROVIDER,
            query=body.question,
            top_k=body.top_k,
            source_docs=source_docs_for_log,
            prompt_style=effective_prompt_style,
            cache_hit=cache_hit,
            error=error,
        )

    return response_payload
