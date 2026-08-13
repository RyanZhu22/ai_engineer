"""MCP client adapter: expose allow-listed remote MCP tools to the local Agent.

The Agent only understands the local ``Tool`` abstraction.  This module connects
to deployment-configured MCP servers, discovers their tools, namespaces them, and
adapts calls back into that abstraction.  It intentionally does *not* accept a
server command or URL from an API request: starting a process or contacting a
remote service is an operator decision made through environment configuration.
"""
import asyncio
import hashlib
import json
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from .agent import Tool


MAX_MCP_CONFIG_BYTES = 16_000
MAX_MCP_SERVERS = 8
MAX_MCP_TOOLS_PER_SERVER = 30
MAX_MCP_TOOLS_TOTAL = 50
MAX_MCP_TIMEOUT_SECONDS = 120.0
_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_OPENAI_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class MCPConfigurationError(ValueError):
    """Raised when operator-supplied MCP configuration is invalid or unavailable."""


class MCPServerConfig(BaseModel):
    """One allow-listed MCP server, supplied in ``MCP_SERVERS_JSON``.

    ``allowed_tools`` is deliberately required and must list every exposed tool.
    An MCP server may offer side-effecting capabilities, so a new tool must not
    become callable merely because a remote server added it.
    """

    transport: Literal["stdio", "streamable_http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=MAX_MCP_TIMEOUT_SECONDS)

    @model_validator(mode="after")
    def validate_transport_settings(self):
        if self.transport == "stdio":
            if not self.command or not self.command.strip():
                raise ValueError("stdio transport requires a non-empty command")
            if self.url is not None:
                raise ValueError("stdio transport does not accept url")
        else:
            if not self.url or not self.url.startswith(("https://", "http://")):
                raise ValueError("streamable_http transport requires an http(s) url")
            if self.command is not None:
                raise ValueError("streamable_http transport does not accept command")
        if not self.allowed_tools:
            raise ValueError("allowed_tools must explicitly list at least one MCP tool")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("allowed_tools cannot contain duplicates")
        for value in [self.command, self.cwd, *self.args, *self.env.values(), *self.headers.values()]:
            if value is not None and "\x00" in value:
                raise ValueError("MCP configuration cannot contain NUL bytes")
        return self


@dataclass(frozen=True)
class ConfiguredMCPServer:
    name: str
    config: MCPServerConfig


def parse_mcp_servers(raw_config: str) -> list[ConfiguredMCPServer]:
    """Parse and validate ``MCP_SERVERS_JSON`` without exposing secrets in errors."""
    if not raw_config or not raw_config.strip():
        return []
    if len(raw_config.encode("utf-8")) > MAX_MCP_CONFIG_BYTES:
        raise MCPConfigurationError("MCP_SERVERS_JSON exceeds the maximum allowed size")
    try:
        data = json.loads(raw_config)
    except json.JSONDecodeError as exc:
        raise MCPConfigurationError("MCP_SERVERS_JSON must be valid JSON") from exc
    if not isinstance(data, dict):
        raise MCPConfigurationError("MCP_SERVERS_JSON must be an object keyed by server name")
    if len(data) > MAX_MCP_SERVERS:
        raise MCPConfigurationError(f"at most {MAX_MCP_SERVERS} MCP servers may be configured")

    servers: list[ConfiguredMCPServer] = []
    for name, values in data.items():
        if not isinstance(name, str) or not _SERVER_NAME_RE.fullmatch(name):
            raise MCPConfigurationError("MCP server names must contain only letters, digits, _ or -")
        if not isinstance(values, dict):
            raise MCPConfigurationError(f"MCP server '{name}' configuration must be an object")
        try:
            config = MCPServerConfig.model_validate(values)
        except ValidationError as exc:
            # Validation detail can contain the configuration value, including headers.
            raise MCPConfigurationError(f"MCP server '{name}' configuration is invalid") from exc
        servers.append(ConfiguredMCPServer(name=name, config=config))
    return servers


def _agent_tool_name(server_name: str, remote_tool_name: str) -> str:
    """Create an OpenAI-compatible, collision-resistant tool name."""
    candidate = f"mcp_{server_name}_{remote_tool_name}"
    if _OPENAI_TOOL_NAME_RE.fullmatch(candidate):
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", candidate)[:52]
    return f"{safe}_{digest}"


def _format_mcp_result(result: Any) -> str:
    """Turn MCP content into bounded text suitable for a language model.

    Binary payloads and protocol metadata are intentionally not fed into the
    model.  Text and structured JSON are preserved; the generic Agent output
    cap applies after this adapter returns.
    """
    chunks: list[str] = []
    for content in getattr(result, "content", []) or []:
        if getattr(content, "type", None) == "text":
            chunks.append(content.text)
        elif getattr(content, "type", None) == "resource":
            resource = content.resource
            if hasattr(resource, "text"):
                chunks.append(resource.text)
            else:
                chunks.append("[MCP 返回了非文本资源，未注入模型上下文]")
        else:
            chunks.append(f"[MCP 返回了 {getattr(content, 'type', '未知')} 内容，未注入模型上下文]")

    structured = getattr(result, "structured_content", None)
    if structured is not None:
        try:
            chunks.append("结构化结果：\n" + json.dumps(structured, ensure_ascii=False))
        except (TypeError, ValueError):
            chunks.append("[MCP 返回了无法序列化的结构化结果]")

    output = "\n".join(part for part in chunks if part).strip() or "MCP 工具未返回文本结果。"
    if getattr(result, "is_error", False):
        return "MCP 工具返回错误：\n" + output
    return output


class MCPToolProvider:
    """Owns live MCP sessions for exactly one Agent request.

    Opening it discovers allowed tools.  The same session stays open while the
    Agent loop runs, so stateful MCP servers and stdio subprocesses are not
    re-created for every tool call.
    """

    def __init__(self, servers: list[ConfiguredMCPServer], *, require_config: bool = False):
        self._servers = servers
        self._require_config = require_config
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, Any] = {}
        self.tools: list[Tool] = []
        self.server_tools: dict[str, list[str]] = {}

    @classmethod
    def from_settings(cls, *, enabled: bool) -> "MCPToolProvider":
        from .config import get_settings

        # MCP is opt-in per Agent request.  A malformed or temporarily unavailable
        # integration must never take down the normal local-tools-only Agent path.
        if not enabled:
            return cls([])
        return cls(parse_mcp_servers(get_settings().mcp_servers_json), require_config=True)

    async def __aenter__(self) -> "MCPToolProvider":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.aclose()

    async def open(self) -> None:
        if self._stack is not None:
            return
        if self._require_config and not self._servers:
            raise MCPConfigurationError("未配置 MCP server；请设置 MCP_SERVERS_JSON")

        self._stack = AsyncExitStack()
        try:
            for server in self._servers:
                await self._connect_server(server)
        except Exception:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        if self._stack is not None:
            stack, self._stack = self._stack, None
            self._sessions.clear()
            await stack.aclose()

    async def _connect_server(self, server: ConfiguredMCPServer) -> None:
        assert self._stack is not None
        try:
            read_stream, write_stream = await self._stack.enter_async_context(
                self._transport_for(server)
            )
            from mcp import ClientSession

            session = await self._stack.enter_async_context(
                ClientSession(read_stream, write_stream, read_timeout_seconds=server.config.timeout_seconds)
            )
            async with asyncio.timeout(server.config.timeout_seconds):
                await session.initialize()
                discovered = await session.list_tools()
        except Exception as exc:
            raise MCPConfigurationError(f"无法连接 MCP server '{server.name}'") from exc

        self._sessions[server.name] = session
        allowed = set(server.config.allowed_tools)
        remote_tools = [tool for tool in discovered.tools if tool.name in allowed]
        if len(remote_tools) != len(allowed):
            unavailable = sorted(allowed - {tool.name for tool in remote_tools})
            raise MCPConfigurationError(
                f"MCP server '{server.name}' did not expose allowed tool(s): {', '.join(unavailable)}"
            )
        if len(remote_tools) > MAX_MCP_TOOLS_PER_SERVER:
            raise MCPConfigurationError(f"MCP server '{server.name}' exposes too many allowed tools")
        if len(self.tools) + len(remote_tools) > MAX_MCP_TOOLS_TOTAL:
            raise MCPConfigurationError("configured MCP tools exceed the total allowed limit")

        self.server_tools[server.name] = []
        for remote_tool in remote_tools:
            agent_name = _agent_tool_name(server.name, remote_tool.name)
            if any(tool.name == agent_name for tool in self.tools):
                raise MCPConfigurationError(f"MCP tool name collision for '{agent_name}'")
            schema = remote_tool.input_schema
            if not isinstance(schema, dict):
                raise MCPConfigurationError(
                    f"MCP server '{server.name}' returned an invalid schema for '{remote_tool.name}'"
                )
            self.tools.append(
                Tool(
                    name=agent_name,
                    description=(
                        f"[MCP server: {server.name}; remote tool: {remote_tool.name}] "
                        f"{remote_tool.description or 'No description provided.'}"
                    ),
                    parameters=schema,
                    fn=self._make_tool_function(server.name, remote_tool.name),
                )
            )
            self.server_tools[server.name].append(agent_name)

    def _transport_for(self, server: ConfiguredMCPServer):
        if server.config.transport == "stdio":
            from mcp import StdioServerParameters, stdio_client

            return stdio_client(
                StdioServerParameters(
                    command=server.config.command or "",
                    args=server.config.args,
                    env=server.config.env or None,
                    cwd=server.config.cwd,
                )
            )

        from mcp.client.streamable_http import streamable_http_client

        # ``httpx2`` is the HTTP client used by the MCP SDK.  It is installed as
        # an MCP dependency and is only imported when Streamable HTTP is selected.
        import httpx2

        http_client = httpx2.AsyncClient(
            headers=server.config.headers,
            timeout=server.config.timeout_seconds,
        )
        assert self._stack is not None
        # The transport does not own a supplied client, so this provider owns it.
        async def managed_transport():
            async with http_client:
                async with streamable_http_client(server.config.url or "", http_client=http_client) as streams:
                    yield streams

        from contextlib import asynccontextmanager

        return asynccontextmanager(managed_transport)()

    def _make_tool_function(self, server_name: str, remote_tool_name: str):
        async def call_mcp_tool(**arguments: Any) -> str:
            session = self._sessions.get(server_name)
            if session is None:
                return f"错误：MCP server '{server_name}' 未连接。"
            timeout = next(s.config.timeout_seconds for s in self._servers if s.name == server_name)
            try:
                async with asyncio.timeout(timeout):
                    result = await session.call_tool(remote_tool_name, arguments=arguments)
                return _format_mcp_result(result)
            except TimeoutError:
                return f"错误：MCP 工具 '{remote_tool_name}' 调用超时。"
            except Exception as exc:
                return f"错误：MCP 工具 '{remote_tool_name}' 调用失败：{type(exc).__name__}"

        return call_mcp_tool
