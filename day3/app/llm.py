from typing import List, Optional

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


def build_rag_prompt(question: str, context_blocks: List[str]) -> str:
    context = "\n\n".join(context_blocks)
    return (
        "你是一个严谨的AI助理。请只基于给定的上下文回答。\n"
        "如果上下文不足，请明确说“根据当前检索内容无法确定”。\n"
        "回答后请列出你使用到的来源标签。\n\n"
        f"问题：{question}\n\n"
        f"上下文：\n{context}\n\n"
        "请输出：\n"
        "1) 简明答案\n"
        "2) 来源标签列表"
    )


async def generate_with_context(question: str, context_blocks: List[str]) -> str:
    if LLM_PROVIDER == "echo":
        return _echo_generate(question, context_blocks)

    prompt = build_rag_prompt(question, context_blocks)

    if LLM_PROVIDER == "ollama":
        return await _ollama_generate(prompt)

    if LLM_PROVIDER == "deepseek":
        return await _deepseek_generate(prompt)

    raise LLMError(f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}")


def _echo_generate(question: str, context_blocks: List[str]) -> str:
    if not context_blocks:
        return "未检索到可用上下文，无法回答。"

    preview = []
    for item in context_blocks[:2]:
        _, _, text = item.partition("] ")
        preview.append(text.replace("\n", " ")[:80])

    joined = "；".join(preview)
    return (
        f"[echo-rag] 问题: {question}\n"
        f"基于检索片段的示例回答: {joined}\n"
        "提示: 这是调试模式。设置 LLM_PROVIDER=ollama 或 deepseek 获取真实生成回答。"
    )


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
