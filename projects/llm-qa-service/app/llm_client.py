"""LLM 客户端 - 支持任意 OpenAI 兼容 API，无 Key 时走 mock 模式。

对标 JD 技能：LLM API 调用（OpenAI/Anthropic/Gemini）
知识点：
  - OpenAI 兼容协议：base_url + api_key + model
  - 通过环境变量切换供应商，代码零改动
  - mock 模式：无 Key 也能完整跑通服务
"""
import json
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from .config import get_settings


@dataclass
class ToolCall:
    """模型返回的单个工具调用：函数名 + JSON 参数。"""
    id: str
    name: str
    arguments: dict[str, Any]
    arguments_error: str | None = None


@dataclass
class ChatResult:
    """chat_with_tools 的返回值：正文（可能为空）+ 工具调用列表。"""
    content: str
    tool_calls: Optional[list[ToolCall]] = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


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

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: Optional[list] = None,
        temperature: float = 0.7,
    ) -> ChatResult:
        """支持 function calling 的对话调用（agent loop 的核心）。

        与 chat() 的区别：把 tools 以 OpenAI 格式传给模型，模型可能返回
        tool_calls（要调用的函数名 + JSON 参数）而不是直接回答。

        OpenAI 兼容协议的 function calling 格式（面试考点）：
          - 请求带 tools=[{"type":"function","function":{name,description,parameters}}]
          - 响应 message.tool_calls=[{id, function:{name, arguments(JSON 字符串)}}]
          - 执行完工具后，把结果以 role="tool" + tool_call_id 回填，再请求一次
        """
        if self.mock:
            return self._mock_chat_with_tools(messages, tools)

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = [t.to_openai_schema() for t in tools]
            payload["tool_choice"] = "auto"

        resp = await self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        tool_calls = []
        for index, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            arguments_error = None
            try:
                args = json.loads(raw_args)
            except (json.JSONDecodeError, TypeError):
                args = {}
                arguments_error = "模型返回的参数不是合法 JSON"
            if not isinstance(args, dict):
                args = {}
                arguments_error = "模型返回的参数必须是 JSON 对象"
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{index}",
                    name=fn.get("name") or "",
                    arguments=args,
                    arguments_error=arguments_error,
                )
            )
        return ChatResult(content=content, tool_calls=tool_calls or None)

    # ---------- mock 模式下的 agent 模拟 ----------
    def _mock_chat_with_tools(self, messages: list[dict], tools: Optional[list]) -> ChatResult:
        """mock 模式模拟 function calling，让 agent loop 无 Key 也能完整跑通。

        规则（确定性，便于测试）：
          1. 历史里已有 role="tool"（上一步已执行工具）→ 给出最终回答
          2. 有可用工具 → 按启发式挑选一个并返回 tool_call
          3. 否则 → 普通 mock 回复
        """
        if any(m.get("role") == "tool" for m in messages):
            return ChatResult(content=self._mock_agent_final(messages))

        if not tools:
            return ChatResult(content=self._mock_reply(messages))

        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m["content"]
                break

        tool = self._mock_pick_tool(last_user, tools)
        if tool is None:
            return ChatResult(content=self._mock_reply(messages))

        call_id = f"call_mock_{len(messages)}"
        return ChatResult(
            content="",
            tool_calls=[ToolCall(id=call_id, name=tool.name, arguments=self._mock_tool_args(tool.name, last_user))],
        )

    def _mock_pick_tool(self, text: str, tools: list):
        """启发式选工具：算式→calculator；时间词→get_current_time；否则→search_knowledge_base。"""
        by_name = {t.name: t for t in tools}
        if "calculator" in by_name and re.search(r"[0-9]\s*[+\-*/×÷^]", text):
            return by_name["calculator"]
        if "get_current_time" in by_name and any(k in text for k in ("时间", "几点", "现在", "日期", "time")):
            return by_name["get_current_time"]
        mcp_tools = [tool for name, tool in by_name.items() if name.startswith("mcp_")]
        if mcp_tools:
            return mcp_tools[0]
        if "search_knowledge_base" in by_name:
            return by_name["search_knowledge_base"]
        return None

    def _mock_tool_args(self, name: str, text: str) -> dict:
        if name == "calculator":
            m = re.search(r"([0-9]+(?:\.[0-9]+)?\s*[+\-*/×÷^]\s*[0-9.+\-*/×÷^() ]*)", text)
            return {"expression": m.group(1) if m else text}
        if name == "search_knowledge_base":
            return {"query": text, "top_k": 4}
        if name.startswith("mcp_"):
            # 演示 MCP 工具使用 topic；真实 LLM 会按 MCP 返回的 JSON Schema 决定参数。
            if "年假" in text or "annual" in text.lower():
                return {"topic": "annual_leave"}
            if "远程" in text or "remote" in text.lower():
                return {"topic": "remote_work"}
            if "培训" in text or "training" in text.lower():
                return {"topic": "training"}
            return {"topic": text}
        return {}

    def _mock_agent_final(self, messages: list[dict]) -> str:
        """mock 最终回答：把最后一条工具结果原样返回，链路可见。"""
        for m in reversed(messages):
            if m.get("role") == "tool":
                return f"[MOCK MODE] 已调用工具获取信息：\n{m.get('content', '')}"
        return self._mock_reply(messages)

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
