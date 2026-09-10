"""应用配置 - 从环境变量注入，对齐 production 最佳实践。"""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """读取 .env 或环境变量。优先级：环境变量 > .env 文件。"""

    # LLM 配置
    llm_base_url: str = ""  # 留空 = OpenAI 官方 API
    llm_api_key: str = ""   # 空 = mock 模式（无 Key 也能跑通全流程）
    llm_model: str = "gpt-4o-mini"
    # 仅供 evals/run_rag_eval.py 的可选 LLM 裁判使用；留空则复用 llm_model。
    eval_judge_model: str = ""

    # ---------- LLM 客户端（连接池 + 重试） ----------
    # 连接池：HTTP 连接 TCP 握手 + TLS 协商成本高，长连接复用是关键
    llm_timeout_seconds: float = 60.0
    llm_max_connections: int = 100        # 连接池上限（并发峰值）
    llm_max_keepalive_connections: int = 20  # 空闲保活连接上限
    # 重试：LLM API 偶发 429（限流）/ 5xx（服务端故障）/ 网络抖动，指数退避重试
    llm_max_retries: int = 3              # 最大重试次数（不含首次请求）
    llm_retry_base_delay: float = 1.0     # 退避基数（秒）：1s → 2s → 4s
    llm_retry_max_delay: float = 8.0      # 退避上限（秒），防止雪崩

    # 服务配置
    app_port: int = 8000
    app_env: str = "dev"

    # 数据库（PostgreSQL + pgvector，本地用 docker compose 起）
    database_url: str = "postgresql+psycopg://llmqa:llmqa_dev_only@localhost:5432/llmqa"

    # ---------- RAG / Embedding 配置 ----------
    # provider: auto（有 key 用 api，否则本地模型，再否则 mock）| local | api | mock
    embedding_provider: str = "auto"
    # embedding 维度必须与数据库 chunks.embedding 列一致（建表时固定）
    # 本地 bge-small-zh = 512；换 API（如 OpenAI 1536）时需改此项并重建表
    embedding_dim: int = 512
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    # 本地模型（fastembed，首次使用自动下载，~90MB）
    embedding_local_model: str = "BAAI/bge-small-zh-v1.5"

    # RAG 检索参数
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 50
    rag_top_k: int = 4
    # hybrid = vector 候选 + BM25 候选经 RRF 融合；vector 可用于对照和回归排查。
    rag_retrieval_mode: Literal["vector", "hybrid"] = "hybrid"
    # 候选数大于最终 top_k，避免两路融合时过早丢掉另一种检索器的强相关片段。
    rag_vector_candidate_k: int = Field(default=20, ge=1, le=200)
    rag_bm25_candidate_k: int = Field(default=20, ge=1, le=200)
    # Reciprocal Rank Fusion 常用平滑常数。只影响排序融合，不改变向量或 BM25 原始分数。
    rag_rrf_k: int = Field(default=60, ge=1, le=200)
    # 三路 RRF：向量、chunk BM25、候选 chunk 内的最佳事实句 BM25。
    rag_vector_weight: float = Field(default=1.0, gt=0, le=5)
    rag_bm25_weight: float = Field(default=1.0, gt=0, le=5)
    rag_sentence_bm25_weight: float = Field(default=1.0, gt=0, le=5)

    # ---------- 向量索引（pgvector HNSW） ----------
    # 没有索引时 `ORDER BY embedding <=> $1` 是精确全表扫描（O(N)，召回 100%）。
    # HNSW 是近似最近邻（ANN）：把召回换延迟，参数决定这条权衡曲线。
    # m / ef_construction 只在建索引时生效，改动后需要重建索引。
    rag_hnsw_m: int = Field(default=16, ge=2, le=100)
    rag_hnsw_ef_construction: int = Field(default=64, ge=4, le=1000)
    # ef_search 是“查询时”旋钮：每个请求都能调，越大召回越高、延迟越高。
    rag_hnsw_ef_search: int = Field(default=40, ge=1, le=1000)
    # 带 WHERE 过滤（本项目每个查询都带 owner 过滤）时，HNSW 只取 ef_search 个候选再过滤，
    # 过滤性强的时候会返回不足 top_k 条 → 召回塌陷。iterative_scan 让索引继续往下扫。
    # off | relaxed_order（更快，顺序可能不严格）| strict_order（严格按距离，稍慢）
    rag_hnsw_iterative_scan: Literal["off", "relaxed_order", "strict_order"] = "relaxed_order"
    # iterative_scan 单次查询最多扫描多少行，防止参数异常时拖垮数据库。
    rag_hnsw_max_scan_tuples: int = Field(default=20000, ge=100, le=1_000_000)

    # ---------- MCP（外部工具接入） ----------
    # JSON object。键为 server 名；每个 server 必须显式声明 allowed_tools。
    # 示例见 .env.example / README。留空时 Agent 只使用本地内置工具。
    mcp_servers_json: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def mock_mode(self) -> bool:
        """没有 API Key 时用 mock 模式，方便本地开发和测试。"""
        return not self.llm_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
