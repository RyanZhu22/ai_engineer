from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .agent import run_agent
from .tools import build_tool_registry


BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "data" / "docs"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.registry = build_tool_registry(DOCS_DIR)
    yield


app = FastAPI(title="Day8 Agent API", version="0.1.0", lifespan=lifespan)


class AgentIn(BaseModel):
    query: str = Field(min_length=1)
    max_steps: int = Field(default=4, ge=1, le=8)


class ToolTrace(BaseModel):
    step: int
    tool: str
    reason: str
    args: Dict[str, Any]
    result: Dict[str, Any]


class AgentOut(BaseModel):
    query: str
    tool_calls: List[ToolTrace]
    used_tools: List[str]
    final_answer: str


@app.get("/health")
async def health():
    registry = app.state.registry
    return {
        "status": "ok",
        "docs_dir": str(DOCS_DIR),
        "tool_count": len(registry),
    }


@app.get("/tools")
async def tools():
    registry = app.state.registry
    return {
        "tools": [
            {"name": tool.name, "description": tool.description}
            for tool in registry.values()
        ]
    }


@app.post("/agent", response_model=AgentOut)
async def agent_endpoint(body: AgentIn):
    registry = app.state.registry
    result = run_agent(body.query, registry, max_steps=body.max_steps)
    return result
