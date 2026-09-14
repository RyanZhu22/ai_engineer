"""LLM 客户端 - 支持任意 OpenAI 兼容 API，无 Key 时走 mock 模式。

对标 JD 技能：LLM API 调用（OpenAI/Anthropic/Gemini）
知识点：
  - OpenAI 兼容协议：base_url + api_key + model
  - 通过环境变量切换供应商，代码零改动
  - mock 模式：无 Key 也能完整跑通服务
  - 连接池复用：httpx.Limits 限制并发与保活连接，避免每次请求重新握手
  - 指数退避重试：429（限流）/ 5xx（服务端故障）/ 网络错误，尊重 Retry-After
"""
import asyncio
import json
import random
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from .config import get_settings

# 可重试状态码：429 = 限流（等一会就能好），5xx = 服务端瞬时故障
# 面试考点：4xx 客户端错误（400/401/403/422）重试无意义，必须直接失败
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Retry-After 等待上限（秒）：尊重上游建议，但防止被要求等过长时间
MAX_RETRY_AFTER_SECONDS = 60.0


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


class _RetryableStatusError(httpx.HTTPStatusError):
    """429/5xx 服务端瞬时错误。继承 HTTPStatusError，调用方按标准方式处理。"""

    def __init__(self, response: httpx.Response, retry_after: Optional[float] = None):
        super().__init__(
            f"HTTP {response.status_code} (retries exhausted)",
            request=response.request,
            response=response,
        )
        self.retry_after = retry_after


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """解析 Retry-After 头（秒数）。仅支持数字秒，简单可靠；失败则回退到指数退避。"""
    if not value:
        return None
    try:
        return min(max(float(value), 0.0), MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        return None


class LLMClient:
    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        *,
        # 以下参数便于测试注入与配置调优（生产值来自 config.py）
        transport: Optional[httpx.AsyncBaseTransport] = None,  # 测试注入 MockTransport
        timeout: float = 60.0,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 8.0,
    ):
        self.base_url = base_url or "https://api.openai.com/v1"
        self.api_key = api_key
        self.model = model
        self.mock = not api_key
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.pool_limits = (max_connections, max_keepalive_connections)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            ),
            transport=transport,
        )

    # ---------- 重试核心 ----------

    async def _post_with_retry(
        self,
        url: str,
        *,
        headers: dict,
        json: dict,
        stream: bool = False,
    ) -> httpx.Response:
        """POST JSON，带指数退避重试。

        重试策略（面试考点）：
          - 可重试：429（按 Retry-After 或退避）、5xx（500/502/503/504）、网络错误（TransportError）
          - 不重试：4xx 客户端错误（400/401/403/422）——重试也不会成功
          - 退避：1s → 2s → 4s ...（指数）+ 随机抖动（jitter），避免重试风暴同时打爆上游
          - 流式（stream=True）：只对"拿到响应头之前"的错误重试；
            一旦开始流式输出，中途断流不重试（重发会导致用户看到重复内容）
        """
        last_error: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            try:
                if stream:
                    req = self._client.build_request("POST", url, headers=headers, json=json)
                    resp = await self._client.send(req, stream=True)
                else:
                    resp = await self._client.post(url, headers=headers, json=json)

                if resp.status_code in RETRYABLE_STATUS:
                    retry_after = _parse_retry_after(resp.headers.get("retry-after"))
                    await resp.aclose()
                    raise _RetryableStatusError(resp, retry_after)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                # 4xx 客户端错误：重试无意义，直接抛给调用方
                if exc.response.status_code not in RETRYABLE_STATUS:
                    raise
                last_error = exc
            except httpx.TransportError as exc:
                # 网络层错误（连接重置/超时/DNS）：重试
                last_error = exc

            if attempt < self.max_retries:
                wait = getattr(last_error, "retry_after", None)
                await asyncio.sleep(wait if wait is not None else self._backoff_delay(attempt))

        assert last_error is not None
        raise last_error

    def _backoff_delay(self, attempt: int) -> float:
        """指数退避 + 随机抖动：base * 2^attempt，封顶后加少量抖动。"""
        base = min(self.retry_base_delay * (2**attempt), self.retry_max_delay)
        return base + random.uniform(0, min(base, 0.5))

    # ---------- 对外调用 ----------

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

        resp = await self._post_with_retry(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            },
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def stream_chat(self, messages: list[dict], temperature: float = 0.7) -> AsyncIterator[str]:
        """流式调用 Chat Completions API（SSE）。

        知识点（面试考点）：
          - OpenAI 兼容协议的流式格式：`data: {json}\n\n`，结尾 `data: [DONE]`
          - 每个 chunk 的 content 是增量片段，前端拼起来就是完整回答
          - 流式 = 更低的 first-token latency + 更好的用户体验
          - 重试只覆盖"请求阶段"：一旦开始产出 token 就不再重试（避免重复输出）
        """
        if self.mock:
            # mock 模式也流式输出，前端体验一致
            for ch in self._mock_reply(messages):
                yield ch
            return

        resp = await self._post_with_retry(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
            },
            stream=True,
        )
        try:
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
        finally:
            await resp.aclose()

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

        resp = await self._post_with_retry(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
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
            "配置 LLM_API_KEY 后即可获得真实回复。\n"
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
            timeout=s.llm_timeout_seconds,
            max_connections=s.llm_max_connections,
            max_keepalive_connections=s.llm_max_keepalive_connections,
            max_retries=s.llm_max_retries,
            retry_base_delay=s.llm_retry_base_delay,
            retry_max_delay=s.llm_retry_max_delay,
        )
    return _client
