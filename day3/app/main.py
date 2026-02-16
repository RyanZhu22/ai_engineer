from contextlib import asynccontextmanager
from time import perf_counter
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import (
    LLM_PROVIDER,
    RAG_BATCH_SIZE,
    RAG_DEFAULT_TOP_K,
    RAG_DOCS_DIR,
    RAG_EMBED_MODEL,
    RAG_LOG_PATH,
    RAG_METRICS_MAX_RECENT,
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
    yield


app = FastAPI(title="Day3 RAG API", version="0.1.0", lifespan=lifespan)


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=RAG_DEFAULT_TOP_K, ge=1, le=20)


class AskIn(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=RAG_DEFAULT_TOP_K, ge=1, le=20)


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
    answer: str
    sources: List[HitOut]


@app.get("/health")
async def health():
    retriever: VectorRetriever = app.state.retriever
    return {
        "status": "ok",
        "provider": LLM_PROVIDER,
        "docs_dir": str(RAG_DOCS_DIR),
        "embed_model": RAG_EMBED_MODEL,
        "doc_count": retriever.doc_count,
        "chunk_count": retriever.chunk_count,
    }


@app.get("/metrics/summary")
async def metrics_summary():
    telemetry: TelemetryStore = app.state.telemetry
    return telemetry.summary()


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
            error=error,
        )

    return {
        "query": body.query,
        "hits": [_to_hit_out(hit, RAG_SOURCE_MAX_CHARS) for hit in hits],
    }


@app.post("/ask", response_model=AskOut)
async def ask_endpoint(body: AskIn):
    telemetry: TelemetryStore = app.state.telemetry
    start_ts = perf_counter()
    status_code = 200
    error = ""
    hits: List[SearchHit] = []

    try:
        hits = app.state.retriever.search(body.question, body.top_k)
    except ValueError as exc:
        status_code = 400
        error = str(exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    context_blocks = [_to_context_block(hit) for hit in hits]
    try:
        answer = await generate_with_context(body.question, context_blocks)
    except LLMError as exc:
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
            source_docs=[hit.chunk.doc_name for hit in hits],
            error=error,
        )

    return {
        "provider": LLM_PROVIDER,
        "question": body.question,
        "answer": answer,
        "sources": [_to_hit_out(hit, RAG_SOURCE_MAX_CHARS) for hit in hits],
    }
