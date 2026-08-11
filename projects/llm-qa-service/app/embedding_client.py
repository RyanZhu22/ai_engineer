"""Embedding 客户端 - RAG 的向量化层，三模式可插拔。

对标 JD 技能：向量数据库 + RAG 架构、多供应商抽象。

模式（EMBEDDING_PROVIDER=auto 时自动选择）：
  local: fastembed + BAAI/bge-small-zh-v1.5（本地 ONNX，中文检索质量高，零 API key）
  api:   OpenAI 兼容 /embeddings 端点（OpenAI/SiliconFlow/智谱等）
  mock:  确定性 feature-hashing（无模型无 key 兜底，基于词重叠）

维度注意：数据库 chunks.embedding 列维度在建表时固定，
换模型/供应商时需保证 embedding_dim 与之一致（并重建表）。
"""
import asyncio
import hashlib
import re
from typing import Optional

import httpx

from .config import get_settings

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def _tokenize(text: str) -> list[str]:
    """中英文混合分词：英文按词，中文按单字（配合 n-gram 特征）。"""
    return _TOKEN_RE.findall(text.lower())


def _ngrams(tokens: list[str], n: int = 2) -> list[str]:
    """中文单字组合成 bigram，缓解单字稀疏问题。"""
    cjk = [t for t in tokens if re.fullmatch(r"[\u4e00-\u9fff]", t)]
    if len(cjk) >= 2:
        return tokens + ["".join(cjk[i:i + n]) for i in range(len(cjk) - n + 1)]
    return tokens


def hash_embedding(text: str, dim: int) -> list[float]:
    """feature hashing：token → (index, sign) 累加 → L2 归一化。

    mock 模式用：共享词汇的文本余弦相似度高，链路演示/测试可用；
    真实语义检索请用 local 或 api 模式。
    """
    vec = [0.0] * dim
    tokens = _ngrams(_tokenize(text))
    for tok in tokens:
        h = hashlib.md5(tok.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class EmbeddingClient:
    def __init__(
        self,
        provider: str = "auto",
        base_url: str = "",
        api_key: str = "",
        model: str = "text-embedding-3-small",
        local_model: str = "BAAI/bge-small-zh-v1.5",
        dim: int = 512,
    ):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.local_model = local_model
        self.dim = dim
        self._client = httpx.AsyncClient(timeout=30.0)
        self._local_model_obj: Optional[object] = None  # fastembed 模型懒加载

    @property
    def mode(self) -> str:
        """解析实际生效的模式：auto → api(有 key) → local(fastembed 可用) → mock"""
        if self.provider == "api":
            return "api" if self.api_key else "mock"
        if self.provider == "local":
            return "local"
        if self.provider == "mock":
            return "mock"
        # auto
        if self.api_key:
            return "api"
        try:
            import fastembed  # noqa: F401
            return "local"
        except ImportError:
            return "mock"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，返回与 texts 等长的向量列表。"""
        mode = self.mode
        if mode == "mock":
            return [hash_embedding(t, self.dim) for t in texts]
        if mode == "api":
            resp = await self._client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            by_index = {item["index"]: item["embedding"] for item in data["data"]}
            return [by_index[i] for i in range(len(texts))]
        # local：CPU 推理是同步阻塞操作，放线程池避免卡事件循环
        return await asyncio.to_thread(self._embed_local, texts)

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        if self._local_model_obj is None:
            from fastembed import TextEmbedding
            self._local_model_obj = TextEmbedding(model_name=self.local_model)
        return [list(v) for v in self._local_model_obj.embed(texts)]

    async def embed_one(self, text: str) -> list[float]:
        result = await self.embed([text])
        return result[0]

    async def aclose(self) -> None:
        await self._client.aclose()


# 单例：连接池 + 模型复用（同 llm_client 的模式）
_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = EmbeddingClient(
            provider=s.embedding_provider,
            base_url=s.embedding_base_url,
            api_key=s.embedding_api_key,
            model=s.embedding_model,
            local_model=s.embedding_local_model,
            dim=s.embedding_dim,
        )
    return _client


def reset_embedding_client() -> None:
    """测试用：重置单例。"""
    global _client
    _client = None
