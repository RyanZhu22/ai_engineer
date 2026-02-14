from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import LLM_PROVIDER
from .llm import LLMError, generate

app = FastAPI(title="Hello LLM API", version="0.1.0")


class PromptIn(BaseModel):
    prompt: str


class PromptOut(BaseModel):
    provider: str
    output: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/llm", response_model=PromptOut)
async def llm_endpoint(body: PromptIn):
    try:
        text = await generate(body.prompt)
    except LLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"provider": LLM_PROVIDER, "output": text}
