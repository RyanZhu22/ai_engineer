"""API 与 Agent 测试。

测试强制使用 mock LLM / embedding：
  - 不下载本地模型、不消耗真实模型额度，结果稳定可复现
  - 仍需要 PostgreSQL 在运行（docker compose up -d）
"""
import os
import asyncio
import json
import sys
from pathlib import Path

# 明确覆盖本机 .env 或 shell 中的真实密钥，避免单测意外调用真实供应商。
os.environ["LLM_API_KEY"] = ""
os.environ["EMBEDDING_PROVIDER"] = "mock"
os.environ["MCP_SERVERS_JSON"] = ""

import pytest
from fastapi.testclient import TestClient

import app.embedding_client as embedding_client_mod
import app.llm_client as llm_client_mod
from app.agent import Agent, Tool, _safe_eval, build_default_tools
from app.llm_client import ChatResult, ToolCall
from app.main import app
from app.mcp_client import MCPConfigurationError, MCPToolProvider, _format_mcp_result, parse_mcp_servers


@pytest.fixture
def client():
    # 重置单例，避免测试之间共享已关闭的 client / embedding 模型
    llm_client_mod._client = None
    embedding_client_mod._client = None
    with TestClient(app) as c:
        from app.auth import hash_password
        from app.db import User, get_session_factory
        import uuid
        username = uuid.uuid4().hex
        async def provision():
            async with get_session_factory()() as session:
                session.add(User(id=username, username=username, password_hash=hash_password("test-password-123"), can_use_mcp=True))
                await session.commit()
        c.portal.call(provision)
        response = c.post('/auth/login', json={'username': username, 'password': 'test-password-123'})
        assert response.status_code == 200
        c.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "UP"
    assert data["service"] == "llm-qa-service"


def test_chat_mock(client):
    """测试环境固定走 mock 模式。"""
    resp = client.post("/chat", json={"message": "香港AI工程师需要什么技能？"})
    assert resp.status_code == 200
    data = resp.json()
    assert "model" in data
    assert data["reply"].strip()  # 非空回复


def test_chat_invalid_empty(client):
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422  # pydantic 校验失败


# ---------- RAG 测试 ----------

def test_upload_document(client):
    resp = client.post(
        "/documents/upload",
        files={"file": ("年假政策.md", "# 年假政策\n员工每年享有12天年假。", "text/markdown")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] > 0
    assert data["chunks"] >= 1
    assert data["embedding_mode"] == "mock"
    # 清理
    client.delete(f"/documents/{data['id']}")


def test_search_retrieves_relevant_chunk(client):
    doc = client.post(
        "/documents/upload",
        files={"file": ("员工手册.md", "## 年假\n员工每年享有12天年假。\n## 培训\n每年5000元培训预算。", "text/markdown")},
    ).json()
    resp = client.post("/documents/search", json={"query": "年假有几天", "top_k": 3})
    assert resp.status_code == 200
    hits = resp.json()["hits"]
    assert hits, "mock 模式应能基于词重叠检索到内容"
    assert any("年假" in h["content"] for h in hits)
    assert all(h["retrieval_mode"] == "hybrid" for h in hits)
    assert all(
        "vector_rank" in h and "bm25_rank" in h and "sentence_bm25_rank" in h
        for h in hits
    )
    client.delete(f"/documents/{doc['id']}")


def test_chat_with_rag_returns_sources(client):
    doc = client.post(
        "/documents/upload",
        files={"file": ("预算政策.md", "每位员工每年享有5000元培训预算。", "text/markdown")},
    ).json()
    resp = client.post("/chat", json={"message": "培训预算是多少？", "use_rag": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"].strip()
    assert data["sources"], "RAG 模式应返回检索来源"
    client.delete(f"/documents/{doc['id']}")


def test_delete_document(client):
    doc = client.post(
        "/documents/upload",
        files={"file": ("临时.md", "临时内容", "text/markdown")},
    ).json()
    resp = client.delete(f"/documents/{doc['id']}")
    assert resp.status_code == 200
    resp = client.delete(f"/documents/{doc['id']}")
    assert resp.status_code == 404


# ---------- Agent（tool calling）测试 ----------

def test_agent_search_tool(client):
    """agent 模式下问知识库问题，应自动调用 search_knowledge_base。"""
    doc = client.post(
        "/documents/upload",
        files={"file": ("手册.md", "员工每年享有12天年假。", "text/markdown")},
    ).json()
    resp = client.post("/agent", json={"message": "年假有几天？"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"].strip()
    assert data["tool_calls"], "agent 应调用工具"
    assert data["tool_calls"][0]["name"] == "search_knowledge_base"
    client.delete(f"/documents/{doc['id']}")


def test_agent_calculator_tool(client):
    """agent 模式下问算术，应自动调用 calculator 并算出结果。"""
    resp = client.post("/agent", json={"message": "帮我算 12*8+4"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_calls"], "agent 应调用 calculator"
    assert data["tool_calls"][0]["name"] == "calculator"
    assert "100" in data["reply"]  # 12*8+4 = 100


def test_agent_time_tool(client):
    """agent 模式下问当前时间，应调用 get_current_time。"""
    resp = client.post("/agent", json={"message": "现在香港几点？"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_calls"]
    assert data["tool_calls"][0]["name"] == "get_current_time"
    assert data["reply"].strip()


def test_agent_stream(client):
    """agent 流式端点：应推送 tool_call 事件和最终回答。"""
    resp = client.post("/agent/stream", json={"message": "帮我算 2+3"})
    assert resp.status_code == 200
    body = resp.text
    assert '"type": "tool_call"' in body
    assert "5" in body


def test_agent_request_validates_iteration_limit(client):
    resp = client.post("/agent", json={"message": "你好", "max_iterations": 11})
    assert resp.status_code == 422


def test_agent_rejects_mcp_when_not_configured(client):
    resp = client.post("/agent", json={"message": "你好", "use_mcp": True})
    assert resp.status_code == 503
    assert "未配置 MCP server" in resp.json()["detail"]


def test_mcp_tool_listing_requires_configuration(client):
    resp = client.get("/mcp/tools")
    assert resp.status_code == 503


def test_agent_uses_configured_mcp_tool_end_to_end(client, monkeypatch):
    """API 层应将 MCP tool 发现、调用和 Agent loop 串起来。"""
    from app.config import get_settings

    monkeypatch.setenv("MCP_SERVERS_JSON", _demo_mcp_config())
    get_settings.cache_clear()
    llm_client_mod._client = None
    try:
        resp = client.post("/agent", json={"message": "请查询年假政策", "use_mcp": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mcp_tools"] == ["mcp_demo_lookup_demo_policy"]
        assert data["tool_calls"][0]["name"] == "mcp_demo_lookup_demo_policy"
        assert "12 天年假" in data["reply"]
    finally:
        get_settings.cache_clear()


# ---------- Agent 内核安全与异常测试 ----------

def test_calculator_rejects_unsafe_or_resource_intensive_expression():
    assert _safe_eval("(1 + 2) * 3") == 9
    with pytest.raises(ValueError):
        _safe_eval("__import__('os').system('echo unsafe')")
    with pytest.raises(ValueError):
        _safe_eval("10 ** 99")
    with pytest.raises(ValueError):
        _safe_eval("1" * 201)


def test_search_tool_enforces_top_k_bounds():
    async def check():
        tools = build_default_tools(None)
        search = next(tool for tool in tools if tool.name == "search_knowledge_base")
        return await search.fn(query="年假", top_k=999)

    assert "top_k 必须在 1 到 20 之间" in asyncio.run(check())


def test_agent_returns_unknown_tool_error_then_final_answer():
    class UnknownToolClient:
        def __init__(self):
            self.calls = 0

        async def chat_with_tools(self, messages, tools, temperature):
            self.calls += 1
            if self.calls == 1:
                return ChatResult("", [ToolCall("call_unknown", "not_available", {})])
            assert messages[-1]["role"] == "tool"
            assert "未知工具" in messages[-1]["content"]
            return ChatResult("已处理未知工具")

    result = asyncio.run(Agent(UnknownToolClient(), []).run([{"role": "user", "content": "测试"}]))
    assert result.answer == "已处理未知工具"
    assert result.tool_calls[0]["name"] == "not_available"


def test_agent_returns_invalid_tool_arguments_error_then_final_answer():
    class InvalidArgumentsClient:
        def __init__(self):
            self.calls = 0

        async def chat_with_tools(self, messages, tools, temperature):
            self.calls += 1
            if self.calls == 1:
                return ChatResult(
                    "",
                    [ToolCall("call_invalid", "echo", {}, arguments_error="模型返回的参数不是合法 JSON")],
                )
            assert "参数无效" in messages[-1]["content"]
            return ChatResult("已处理错误参数")

    async def echo():
        return "should not run"

    tool = Tool("echo", "测试工具", {"type": "object"}, echo)
    result = asyncio.run(
        Agent(InvalidArgumentsClient(), [tool]).run([{"role": "user", "content": "测试"}])
    )
    assert result.answer == "已处理错误参数"
    assert "参数无效" in result.tool_calls[0]["result"]


def test_agent_stops_at_max_iterations():
    class LoopClient:
        async def chat_with_tools(self, messages, tools, temperature):
            return ChatResult("", [ToolCall("call_loop", "echo", {})])

    async def echo():
        return "ok"

    tool = Tool("echo", "测试工具", {"type": "object"}, echo)
    result = asyncio.run(Agent(LoopClient(), [tool]).run([{"role": "user", "content": "测试"}], max_iterations=2))
    assert result.iterations == 2
    assert "最大工具调用次数" in result.answer
    assert len(result.tool_calls) == 2


# ---------- MCP 测试 ----------

def _demo_mcp_config() -> str:
    project_dir = Path(__file__).resolve().parents[1]
    return json.dumps(
        {
            "demo": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "app.demo_mcp_server"],
                "cwd": str(project_dir),
                "allowed_tools": ["lookup_demo_policy"],
            }
        }
    )


def test_mcp_stdio_discovers_and_calls_allowlisted_tool():
    async def check():
        async with MCPToolProvider(parse_mcp_servers(_demo_mcp_config()), require_config=True) as provider:
            assert [tool.name for tool in provider.tools] == ["mcp_demo_lookup_demo_policy"]
            return await provider.tools[0].fn(topic="annual_leave")

    assert "12 天年假" in asyncio.run(check())


def test_mcp_configuration_requires_allowlist_and_does_not_leak_headers():
    bad_config = json.dumps(
        {
            "bad": {
                "transport": "streamable_http",
                "url": "https://example.test/mcp",
                "headers": {"Authorization": "Bearer secret-value"},
            }
        }
    )
    with pytest.raises(MCPConfigurationError) as exc_info:
        parse_mcp_servers(bad_config)
    assert "secret-value" not in str(exc_info.value)
    assert "invalid" in str(exc_info.value)


def test_mcp_configuration_rejects_missing_allowlisted_remote_tool():
    config = json.dumps(
        {
            "demo": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "app.demo_mcp_server"],
                "cwd": str(Path(__file__).resolve().parents[1]),
                "allowed_tools": ["does_not_exist"],
            }
        }
    )

    async def check():
        async with MCPToolProvider(parse_mcp_servers(config), require_config=True):
            pass

    with pytest.raises(MCPConfigurationError, match="did not expose allowed tool"):
        asyncio.run(check())


def test_mcp_result_formatter_keeps_text_and_marks_non_text_content():
    class Text:
        type = "text"
        text = "useful result"

    class Image:
        type = "image"

    class Result:
        content = [Text(), Image()]
        structured_content = {"source": "demo"}
        is_error = False

    output = _format_mcp_result(Result())
    assert "useful result" in output
    assert "image" in output
    assert '"source": "demo"' in output
