from typing import Optional

import httpx

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)


class LLMError(RuntimeError):
    pass


async def generate(prompt: str) -> str:
    provider = LLM_PROVIDER

    if provider == "echo":
        return f"[echo] {prompt}"

    if provider == "ollama":
        return await _ollama_generate(prompt)

    if provider == "deepseek":
        return await _deepseek_generate(prompt)

    raise LLMError(f"Unsupported LLM_PROVIDER: {provider}")


async def _ollama_generate(prompt: str) -> str:
    if not OLLAMA_MODEL:
        raise LLMError("OLLAMA_MODEL is not set")

    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"Ollama request failed: {exc}") from exc

    data = resp.json()
    text: Optional[str] = data.get("response")
    if not text:
        raise LLMError("Ollama response missing 'response' field")

    return text


async def _deepseek_generate(prompt: str) -> str:
    if not DEEPSEEK_API_KEY:
        raise LLMError("DEEPSEEK_API_KEY is not set")

    url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"DeepSeek request failed: {exc}") from exc

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("DeepSeek response missing choices/message/content") from exc

    if not text:
        raise LLMError("DeepSeek response empty")

    return text
