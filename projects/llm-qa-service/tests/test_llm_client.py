"""LLMClient 重试 + 连接池测试。

用 httpx.MockTransport 模拟故障，不依赖真实 API：
  - 429（限流）/ 5xx（服务端故障）→ 应重试
  - 4xx（客户端错误）→ 不重试直接失败
  - 网络错误（TransportError）→ 应重试
  - 流式：请求阶段重试，成功后正常流式输出
  - Retry-After 头 → 尊重上游建议等待
"""
import asyncio
import json

import httpx
import pytest

from app.llm_client import LLMClient, RETRYABLE_STATUS


def _ok_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "ok", "role": "assistant"}}]},
        request=request,
    )


def _make_client(handler, **kwargs) -> LLMClient:
    """构造带 mock transport 的 client，重试间隔调小避免测试变慢。"""
    return LLMClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        retry_base_delay=0.01,
        retry_max_delay=0.05,
        **kwargs,
    )


# ---------- 重试：成功路径 ----------

def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, request=request)
        return _ok_response(request)

    async def check():
        client = _make_client(handler)
        try:
            reply = await client.chat([{"role": "user", "content": "hi"}])
            assert reply == "ok"
        finally:
            await client.aclose()

    asyncio.run(check())
    assert calls["n"] == 2, "429 应重试一次后成功"


def test_retries_on_5xx_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503, request=request)
        return _ok_response(request)

    async def check():
        client = _make_client(handler)
        try:
            reply = await client.chat([{"role": "user", "content": "hi"}])
            assert reply == "ok"
        finally:
            await client.aclose()

    asyncio.run(check())
    assert calls["n"] == 3, "连续 503 应重试到成功"


def test_retries_on_network_error_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return _ok_response(request)

    async def check():
        client = _make_client(handler)
        try:
            reply = await client.chat([{"role": "user", "content": "hi"}])
            assert reply == "ok"
        finally:
            await client.aclose()

    asyncio.run(check())
    assert calls["n"] == 2, "网络错误应重试"


# ---------- 重试：失败路径 ----------

def test_gives_up_after_max_retries():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, request=request)

    async def check():
        client = _make_client(handler, max_retries=2)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.chat([{"role": "user", "content": "hi"}])
        finally:
            await client.aclose()

    asyncio.run(check())
    assert calls["n"] == 3, "1 次初始 + 2 次重试 = 共 3 次请求"


def test_client_error_not_retried():
    """4xx 客户端错误（如 key 无效 401）重试无意义，必须立即失败。"""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": "unauthorized"}, request=request)

    async def check():
        client = _make_client(handler)
        try:
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await client.chat([{"role": "user", "content": "hi"}])
            assert exc_info.value.response.status_code == 401
        finally:
            await client.aclose()

    asyncio.run(check())
    assert calls["n"] == 1, "4xx 不重试"


# ---------- Retry-After ----------

def test_respects_retry_after_header():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, request=request)
        return _ok_response(request)

    async def check():
        client = _make_client(handler)
        try:
            reply = await client.chat([{"role": "user", "content": "hi"}])
            assert reply == "ok"
        finally:
            await client.aclose()

    asyncio.run(check())
    assert calls["n"] == 2, "429 带 Retry-After 应重试"


# ---------- 流式 ----------

def test_stream_retries_before_first_token():
    """流式端点：请求阶段 429 → 重试 → 正常流式输出。"""
    calls = {"n": 0}
    sse_body = (
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(200, content=sse_body, request=request)

    async def check():
        client = _make_client(handler)
        try:
            chunks = [chunk async for chunk in client.stream_chat([{"role": "user", "content": "hi"}])]
            assert "".join(chunks) == "hello"
        finally:
            await client.aclose()

    asyncio.run(check())
    assert calls["n"] == 2, "流式请求阶段 429 应重试"


# ---------- chat_with_tools 也走重试 ----------

def test_chat_with_tools_retries():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, request=request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "get_current_time", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            },
            request=request,
        )

    async def check():
        client = _make_client(handler)
        try:
            result = await client.chat_with_tools([{"role": "user", "content": "几点了"}], tools=[])
            assert result.tool_calls and result.tool_calls[0].name == "get_current_time"
        finally:
            await client.aclose()

    asyncio.run(check())
    assert calls["n"] == 2


# ---------- 连接池 ----------

def test_connection_pool_limits_configured():
    client = LLMClient(api_key="test-key", max_connections=5, max_keepalive_connections=2)
    try:
        # pool_limits 是公开属性（供测试与运维确认 httpx.Limits 传入正确）
        assert client.pool_limits == (5, 2)
    finally:
        asyncio.run(client.aclose())


def test_retryable_status_codes_are_expected():
    """可重试状态码集合必须是已知的限流/服务端错误。"""
    assert RETRYABLE_STATUS == {429, 500, 502, 503, 504}
