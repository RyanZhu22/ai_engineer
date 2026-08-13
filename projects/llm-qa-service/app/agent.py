"""Agent 循环 - tool calling（function calling）。

对标 JD 技能：Agent 开发、tool calling / function calling / MCP。

核心概念（面试可讲）：
  - function calling：LLM 不直接回答，而是返回「要调用哪个函数 + JSON 参数」
  - agent loop（ReAct 基础）：模型 → 判断是否调工具 → 执行工具 → 结果回喂 → 直到给出最终回答
  - 工具抽象：name / description / JSON Schema 参数，模型靠 description 理解何时调用
  - MCP（Model Context Protocol）本质是把工具标准化暴露给模型的协议；
    这里的 Tool 抽象就是本地版，以后接 MCP server 只需把远程工具包装成 Tool
"""
import ast
import json
import math
import operator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from . import rag


# ---------- 工具抽象 ----------

# 工具参数由模型生成，必须把资源消耗限制在可预期范围内。
MAX_SEARCH_QUERY_LENGTH = 1_000
MAX_SEARCH_TOP_K = 20
MAX_CALCULATOR_EXPRESSION_LENGTH = 200
MAX_CALCULATOR_ABS_VALUE = 10**15
MAX_CALCULATOR_EXPONENT = 12
MAX_TOOL_OUTPUT_CHARS = 12_000
MAX_TOOL_CALLS_PER_RUN = 12

@dataclass
class Tool:
    """一个可供 LLM 调用的工具。parameters 是 JSON Schema（OpenAI function calling 格式）。"""
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Awaitable[str]]

    def to_openai_schema(self) -> dict:
        """转成 OpenAI 兼容协议的 tools 元素格式（面试考点）。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------- 内置工具 ----------

# 只允许算术运算的"安全 eval"：用 ast 白名单，绝不执行任意代码
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _safe_eval(expr: str) -> int | float:
    """安全计算受限的四则运算表达式（ast 白名单，替代危险的 eval()）。

    除了禁止属性访问、函数调用等任意代码执行风险外，还限制表达式长度、
    中间结果和指数，避免模型生成超大整数或异常复杂计算耗尽服务资源。
    """
    if len(expr) > MAX_CALCULATOR_EXPRESSION_LENGTH:
        raise ValueError(f"表达式过长（最多 {MAX_CALCULATOR_EXPRESSION_LENGTH} 个字符）")

    node_count = 0

    def _validate_value(value: int | float) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("表达式只支持数字")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("计算结果不是有限数字")
        if abs(value) > MAX_CALCULATOR_ABS_VALUE:
            raise ValueError("计算结果过大")
        return value

    def _walk(node):
        nonlocal node_count
        node_count += 1
        if node_count > 100:
            raise ValueError("表达式过于复杂")
        if isinstance(node, ast.Expression):
            return _walk(node.body)
        if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
            return _validate_value(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left, right = _walk(node.left), _walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_CALCULATOR_EXPONENT:
                raise ValueError(f"指数绝对值不能超过 {MAX_CALCULATOR_EXPONENT}")
            try:
                return _validate_value(_BIN_OPS[type(node.op)](left, right))
            except (ArithmeticError, OverflowError) as exc:
                raise ValueError(f"无法计算该表达式：{exc}") from exc
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _validate_value(_UNARY_OPS[type(node.op)](_walk(node.operand)))
        raise ValueError("表达式包含不支持的操作")

    return _walk(ast.parse(expr.strip(), mode="eval"))


def build_default_tools(session: AsyncSession) -> list[Tool]:
    """构造内置工具集。session 通过闭包传入（每个请求一个 DB session）。

    三个工具覆盖 Agent 最常见的三类能力：
      - search_knowledge_base：对接已有 RAG（检索 + 来源）
      - calculator：确定性计算（LLM 不擅长算数，交给工具）
      - get_current_time：实时信息（LLM 训练数据有截止时间，不知道"现在几点"）
    """

    async def search_knowledge_base(query: str, top_k: int = 4) -> str:
        """检索企业知识库，返回最相关的片段（含来源标题与相似度）。"""
        if not isinstance(query, str) or not (query := query.strip()):
            return "错误：检索关键词不能为空。"
        if len(query) > MAX_SEARCH_QUERY_LENGTH:
            return f"错误：检索关键词不能超过 {MAX_SEARCH_QUERY_LENGTH} 个字符。"
        if isinstance(top_k, bool) or not isinstance(top_k, int):
            return "错误：top_k 必须是整数。"
        if not 1 <= top_k <= MAX_SEARCH_TOP_K:
            return f"错误：top_k 必须在 1 到 {MAX_SEARCH_TOP_K} 之间。"
        hits = await rag.search_chunks(session, query, top_k)
        if not hits:
            return "知识库中没有找到相关内容。"
        return json.dumps(hits, ensure_ascii=False)

    async def calculator(expression: str) -> str:
        """安全计算四则运算（支持 + - * / ^ 括号）。"""
        if not isinstance(expression, str) or not expression.strip():
            return "计算失败：表达式不能为空"
        expr = expression.replace("×", "*").replace("÷", "/").replace("x", "*")
        try:
            return str(_safe_eval(expr))
        except Exception as e:
            return f"计算失败：{e}"

    async def get_current_time() -> str:
        """返回香港当前时间。"""
        return datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M:%S %Z")

    return [
        Tool(
            name="search_knowledge_base",
            description=(
                "在企业知识库中检索与问题相关的文档片段。"
                "当用户问题可能涉及公司制度、政策、手册、流程等内容时使用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词或问题"},
                    "top_k": {
                        "type": "integer",
                        "description": "返回片段数量",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_TOP_K,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            fn=search_knowledge_base,
        ),
        Tool(
            name="calculator",
            description="计算数学表达式（四则运算、幂、括号）。当用户需要算数时使用。",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "如 '12*8+4' 或 '(1+2)*3'"},
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            fn=calculator,
        ),
        Tool(
            name="get_current_time",
            description="查询当前日期时间。当用户问'现在几点/今天几号'等实时信息时使用。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            fn=get_current_time,
        ),
    ]


# ---------- Agent 循环 ----------

@dataclass
class AgentResult:
    """一次 agent 运行的最终结果。"""
    answer: str
    tool_calls: list[dict]   # trace：依次调用了哪些工具、参数、结果摘要
    iterations: int


class Agent:
    """ReAct 风格的 agent 循环：模型决策 → 执行工具 → 回喂结果 → 直到最终回答。"""

    def __init__(self, client, tools: list[Tool]):
        self.client = client
        self.tools = tools
        self._by_name = {t.name: t for t in tools}

    async def run(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_iterations: int = 5,
    ) -> AgentResult:
        """完整跑一遍 agent 循环，返回最终结果。"""
        final = None
        async for step in self.iter_steps(messages, temperature, max_iterations):
            final = step
        # iter_steps 保证最后一步一定是 final（真实回答或 max_iterations 兜底）
        return AgentResult(
            answer=final["answer"],
            tool_calls=final["tool_calls"],
            iterations=final["iterations"],
        )

    async def iter_steps(self, messages: list[dict], temperature: float = 0.7, max_iterations: int = 5):
        """异步生成器：逐步产出 agent 循环事件，供流式端点逐条推送。

        产出两种 dict：
          - {"kind": "tool_call", "name", "arguments", "result"}  中间过程
          - {"kind": "final", "answer", "tool_calls", "iterations"}  最终回答
        """
        msgs = list(messages)   # 复制列表，不污染调用方
        trace: list[dict] = []
        executed_tool_calls = 0

        for i in range(max_iterations):
            if executed_tool_calls >= MAX_TOOL_CALLS_PER_RUN:
                yield {
                    "kind": "final",
                    "answer": "达到单次请求的工具调用上限，未能得到最终回答。",
                    "tool_calls": trace,
                    "iterations": i,
                }
                return
            result = await self.client.chat_with_tools(msgs, self.tools, temperature)

            if not result.tool_calls:
                yield {
                    "kind": "final",
                    "answer": result.content or "（模型未返回内容）",
                    "tool_calls": trace,
                    "iterations": i + 1,
                }
                return

            # 把 assistant 的 tool_calls 消息追加进上下文（OpenAI 兼容协议格式）
            msgs.append({
                "role": "assistant",
                "content": result.content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in result.tool_calls
                ],
            })

            # 逐个执行工具，并把结果以 role="tool" 回填（tool_call_id 必须对应）
            for tc in result.tool_calls:
                if executed_tool_calls >= MAX_TOOL_CALLS_PER_RUN:
                    yield {
                        "kind": "final",
                        "answer": "达到单次请求的工具调用上限，未能得到最终回答。",
                        "tool_calls": trace,
                        "iterations": i + 1,
                    }
                    return
                executed_tool_calls += 1
                output = await self._execute(tc)
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": output})
                trace.append({"name": tc.name, "arguments": tc.arguments, "result": output[:500]})
                yield {"kind": "tool_call", "name": tc.name, "arguments": tc.arguments, "result": output[:500]}

        yield {
            "kind": "final",
            "answer": "达到最大工具调用次数，未能得到最终回答。",
            "tool_calls": trace,
            "iterations": max_iterations,
        }

    async def _execute(self, tool_call) -> str:
        """执行单个工具调用，统一处理未知工具 / 参数错误。"""
        if getattr(tool_call, "arguments_error", None):
            return f"错误：工具参数无效 - {tool_call.arguments_error}"
        if not isinstance(tool_call.arguments, dict):
            return "错误：工具参数必须是 JSON 对象"
        tool = self._by_name.get(tool_call.name)
        if tool is None:
            return f"错误：未知工具 {tool_call.name}"
        try:
            result = await tool.fn(**tool_call.arguments)
            output = str(result)
            if len(output) > MAX_TOOL_OUTPUT_CHARS:
                return output[:MAX_TOOL_OUTPUT_CHARS] + "\n[工具结果已截断]"
            return output
        except TypeError as e:
            return f"错误：工具参数不匹配 - {e}"
        except Exception as e:
            return f"错误：工具执行失败 - {e}"
