import ast
import operator
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Dict[str, Any]]


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", text.lower())


def _load_docs(docs_dir: Path) -> List[Dict[str, str]]:
    docs: List[Dict[str, str]] = []
    for path in sorted(docs_dir.glob("*.txt")):
        content = path.read_text(encoding="utf-8").strip()
        docs.append({"doc_name": path.name, "text": content})
    return docs


def search_docs_tool(docs_dir: Path, query: str, top_k: int = 2) -> Dict[str, Any]:
    docs = _load_docs(docs_dir)
    if not docs:
        return {"ok": False, "error": f"No docs found in {docs_dir}"}

    query_tokens = _tokenize(query)
    scored: List[Dict[str, Any]] = []
    for doc in docs:
        doc_tokens = set(_tokenize(doc["text"]))
        score = sum(1 for token in query_tokens if token in doc_tokens)
        scored.append(
            {
                "doc_name": doc["doc_name"],
                "score": score,
                "snippet": doc["text"][:180].replace("\n", " "),
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[: max(1, top_k)]
    return {"ok": True, "query": query, "hits": top}


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return float(_UNARY_OPS[type(node.op)](_safe_eval(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return float(_BIN_OPS[type(node.op)](left, right))
    raise ValueError("Unsupported expression")


def calculator_tool(expression: str) -> Dict[str, Any]:
    expr = expression.strip()
    if not expr:
        return {"ok": False, "error": "expression is empty"}
    try:
        tree = ast.parse(expr, mode="eval")
        value = _safe_eval(tree)
    except Exception as exc:
        return {"ok": False, "error": f"invalid expression: {exc}"}
    return {"ok": True, "expression": expr, "value": value}


def build_tool_registry(docs_dir: Path) -> Dict[str, Tool]:
    return {
        "search_docs": Tool(
            name="search_docs",
            description="Search local docs and return top hits",
            fn=lambda query, top_k=2: search_docs_tool(docs_dir, query, top_k),
        ),
        "calculator": Tool(
            name="calculator",
            description="Evaluate arithmetic expression safely",
            fn=lambda expression: calculator_tool(expression),
        ),
    }
