"""LLM 客户端 - 支持任意 OpenAI 兼容 API，无 Key 时走 mock 模式。

对标 JD 技能：LLM API 调用（OpenAI/Anthropic/Gemini）
知识点：
  - OpenAI 兼容协议：base_url + api_key + model
  - 通过环境变量切换供应商，代码零改动
  - mock 模式：无 Key 也能完整跑通服务
"""
import json
from typing import AsyncIterator, Optional

import httpx

from .config import get_settings


class LLMClient:
    def __init__(self, base_url: str = "", api_key: str = "", model: str = "gpt-4o-mini"):
        self.base_url = base_url or "https://api.openai.com/v1"
        self.api_key = api_key
        self.model = model
        self.mock = not api_key
        self._client = httpx.AsyncClient(timeout=60.0)

    async def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        """调用 Chat Completions API。

        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
            temperature: 0=确定性 1=创造性

        Returns:
            LLM 返回的文本
        """
        if self.mock:
            return self._mock_reply(messages)

        resp = await self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def stream_chat(self, messages: list[dict], temperature: float = 0.7) -> AsyncIterator[str]:
        """流式调用 Chat Completions API（SSE）。

        知识点（面试考点）：
          - OpenAI 兼容协议的流式格式：`data: {json}\n\n`，结尾 `data: [DONE]`
          - 每个 chunk 的 content 是增量片段，前端拼起来就是完整回答
          - 流式 = 更低的 first-token latency + 更好的用户体验
        """
        if self.mock:
            # mock 模式也流式输出，前端体验一致
            for ch in self._mock_reply(messages):
                yield ch
            return

        async with self._client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                chunk = json.loads(payload)
                # delta 里可能没有 content（如 role 变化时）
                delta = chunk["choices"][0].get("delta", {}).get("content", "")
                if delta:
                    yield delta

    def _mock_reply(self, messages: list[dict]) -> str:
        """无 Key 时的模拟回复，方便开发调试。"""
        last_user_msg = ""
        for m in reversed(messages):
            if m["role"] == "user":
                last_user_msg = m["content"]
                break
        return (
            f"[MOCK MODE] 收到你的问题：{last_user_msg}\n"
            "配置 OPENAI_API_KEY 后即可获得真实回复。\n"
            f"（当前模型：{self.model}，base_url：{self.base_url}）"
        )

    async def aclose(self) -> None:
        await self._client.aclose()


# 单例：应用生命周期内复用同一个 client（连接池复用）
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = LLMClient(
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            model=s.llm_model,
        )
    return _client
