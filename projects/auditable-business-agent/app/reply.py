from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.request import Request, urlopen

from app.knowledge import Evidence
from app.models import Decision


class ReplyGenerator:
    def generate(self, *, summary: str, decision: Decision, evidence: Sequence[Evidence]) -> tuple[str, str]:
        raise NotImplementedError


class TemplateReplyGenerator(ReplyGenerator):
    def generate(self, *, summary: str, decision: Decision, evidence: Sequence[Evidence]) -> tuple[str, str]:
        sources = "、".join(f"{item.title}（{item.version}）" for item in evidence) or "未检索到匹配政策"
        return f"关于“{summary}”：{decision.reason} 参考：{sources}。", "template"


@dataclass(frozen=True, slots=True)
class OpenAICompatibleReplyGenerator(ReplyGenerator):
    endpoint: str
    api_key: str
    model: str

    def generate(self, *, summary: str, decision: Decision, evidence: Sequence[Evidence]) -> tuple[str, str]:
        sources = "\n".join(f"- {item.title}（{item.version}）：{item.excerpt}" for item in evidence)
        payload = {"model": self.model, "temperature": 0, "messages": [{"role": "system", "content": "你是客服文案助手。不得改变系统决定、不得承诺退款。用中文写不超过120字的客服回复，并列出政策标题。"}, {"role": "user", "content": f"客户请求：{summary}\n系统决定：{decision.reason}\n政策证据：\n{sources}"}]}
        request = Request(self.endpoint, data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=15) as response:  # noqa: S310 - endpoint is operator-configured.
            body = json.load(response)
        return str(body["choices"][0]["message"]["content"]).strip(), f"openai-compatible:{self.model}"


def configured_reply_generator() -> ReplyGenerator:
    endpoint = os.getenv("LLM_CHAT_COMPLETIONS_URL")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL")
    if endpoint and api_key and model:
        return OpenAICompatibleReplyGenerator(endpoint=endpoint, api_key=api_key, model=model)
    return TemplateReplyGenerator()
