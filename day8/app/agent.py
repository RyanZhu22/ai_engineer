import re
from dataclasses import dataclass
from typing import Any, Dict, List

from .tools import Tool


@dataclass
class ToolCall:
    tool_name: str
    args: Dict[str, Any]
    reason: str


def _extract_expression(query: str) -> str:
    text = query.strip()
    m = re.search(r"[-+/*()0-9.\s]+", text)
    if m:
        candidate = m.group(0).strip()
        if any(ch.isdigit() for ch in candidate):
            return candidate
    return text


def _needs_math(query: str) -> bool:
    math_keywords = ("计算", "算一下", "加", "减", "乘", "除", "平方", "表达式")
    if any(k in query for k in math_keywords):
        return True
    return bool(re.search(r"\d+\s*[-+/*]\s*\d+", query))


def _needs_search(query: str) -> bool:
    keywords = ("rag", "fastapi", "ai engineer", "ai工程师", "检索", "文档", "流程", "能力")
    q = query.lower()
    return any(k in q for k in keywords)


def plan_tool_calls(query: str) -> List[ToolCall]:
    calls: List[ToolCall] = []
    if _needs_math(query):
        calls.append(
            ToolCall(
                tool_name="calculator",
                args={"expression": _extract_expression(query)},
                reason="query contains arithmetic intent",
            )
        )
    if _needs_search(query):
        calls.append(
            ToolCall(
                tool_name="search_docs",
                args={"query": query, "top_k": 2},
                reason="query asks domain knowledge",
            )
        )
    return calls


def _summarize_result(tool_name: str, result: Dict[str, Any]) -> str:
    if not result.get("ok", False):
        return f"{tool_name} failed: {result.get('error', 'unknown error')}"

    if tool_name == "calculator":
        return f"calculation result: {result.get('value')}"

    if tool_name == "search_docs":
        hits = result.get("hits", [])
        if not hits:
            return "no matching docs found"
        lines = []
        for item in hits:
            lines.append(f"{item.get('doc_name')} (score={item.get('score')})")
        return "top docs: " + ", ".join(lines)

    return f"{tool_name} executed"


def run_agent(query: str, registry: Dict[str, Tool], max_steps: int = 4) -> Dict[str, Any]:
    planned_calls = plan_tool_calls(query)
    trace: List[Dict[str, Any]] = []
    summaries: List[str] = []

    for step, call in enumerate(planned_calls[: max(1, max_steps)], start=1):
        tool = registry.get(call.tool_name)
        if not tool:
            result = {"ok": False, "error": f"tool not found: {call.tool_name}"}
        else:
            try:
                result = tool.fn(**call.args)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}

        trace.append(
            {
                "step": step,
                "tool": call.tool_name,
                "reason": call.reason,
                "args": call.args,
                "result": result,
            }
        )
        summaries.append(_summarize_result(call.tool_name, result))

    if not trace:
        final_answer = (
            "未触发任何工具。请明确你是要计算问题，还是查询 RAG/FastAPI/AI 工程师相关知识。"
        )
    else:
        final_answer = "；".join(summaries)

    return {
        "query": query,
        "tool_calls": trace,
        "used_tools": [item["tool"] for item in trace],
        "final_answer": final_answer,
    }
