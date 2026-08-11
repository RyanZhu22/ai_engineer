"""应用配置 - 从环境变量注入，对齐 production 最佳实践。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """读取 .env 或环境变量。优先级：环境变量 > .env 文件。"""

    # LLM 配置
    llm_base_url: str = ""  # 留空 = OpenAI 官方 API
    llm_api_key: str = ""   # 空 = mock 模式（无 Key 也能跑通全流程）
    llm_model: str = "gpt-4o-mini"

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
