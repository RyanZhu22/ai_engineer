"""A tiny stdio MCP server for local verification of the MCP client adapter.

It is intentionally not enabled by default.  Set ``MCP_SERVERS_JSON`` to the
configuration documented in README to expose it to the Agent, then replace it
with a real allow-listed MCP server for an application integration.
"""
import asyncio

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server


async def list_tools(_ctx, _params) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="lookup_demo_policy",
                description="Look up a deterministic demo company policy by topic.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "One of annual_leave, remote_work or training",
                        }
                    },
                    "required": ["topic"],
                    "additionalProperties": False,
                },
            )
        ]
    )


async def call_tool(_ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    if params.name != "lookup_demo_policy":
        return types.CallToolResult(
            isError=True,
            content=[types.TextContent(text=f"Unknown tool: {params.name}")],
        )
    topic = (params.arguments or {}).get("topic", "")
    policies = {
        "annual_leave": "[演示 MCP 数据] 员工每年享有 12 天年假。",
        "remote_work": "[演示 MCP 数据] 每周可申请最多 2 天远程办公。",
        "training": "[演示 MCP 数据] 每年培训预算为 5,000 港币。",
    }
    result = policies.get(str(topic), "[演示 MCP 数据] 未找到该政策主题。")
    return types.CallToolResult(content=[types.TextContent(text=result)])


server = Server(
    "llm-qa-demo-mcp",
    version="0.1.0",
    description="LLM QA Service MCP integration demo server",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
