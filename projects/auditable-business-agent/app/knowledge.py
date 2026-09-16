from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models import RequestType


@dataclass(frozen=True, slots=True)
class Evidence:
    document_id: str
    title: str
    version: str
    excerpt: str
    score: float
    chunk_index: int | None = None
    source: str | None = None


class KnowledgeBase(Protocol):
    def search(self, *, request_type: RequestType, query: str, limit: int = 3) -> tuple[Evidence, ...]: ...


@dataclass(frozen=True, slots=True)
class PolicyDocument:
    document_id: str
    title: str
    version: str
    request_types: frozenset[RequestType]
    content: str
    source: str = ""


class PolicyKnowledgeBase:
    """Local retrieval baseline over versioned policy documents.

    The business decision remains in PolicyEngine. Retrieval provides the
    human-reviewable policy evidence that supports that decision.
    """

    def __init__(self, documents: tuple[PolicyDocument, ...]) -> None:
        self._documents = documents

    @classmethod
    def from_directory(cls, directory: Path) -> PolicyKnowledgeBase:
        documents = load_policy_documents(directory)
        return cls(documents)

    def search(self, *, request_type: RequestType, query: str, limit: int = 3) -> tuple[Evidence, ...]:
        terms = set(_terms(query))
        candidates = []
        for document in self._documents:
            score = 10 if request_type in document.request_types else 0
            score += len(terms.intersection(_terms(document.content)))
            if score:
                candidates.append(
                    Evidence(
                        document_id=document.document_id,
                        title=document.title,
                        version=document.version,
                        excerpt=_excerpt(document.content),
                        score=float(score),
                        source=document.source,
                    )
                )
        return tuple(sorted(candidates, key=lambda item: (-item.score, item.document_id))[:limit])


def load_policy_documents(directory: Path) -> tuple[PolicyDocument, ...]:
    documents: list[PolicyDocument] = []
    for path in sorted(directory.glob("*.md")):
        metadata, content = _parse_document(path.read_text(encoding="utf-8"))
        documents.append(
            PolicyDocument(
                document_id=metadata["document_id"],
                title=metadata["title"],
                version=metadata["version"],
                request_types=frozenset(RequestType(value.strip()) for value in metadata["request_types"].split(",")),
                content=content,
                source=str(path),
            )
        )
    return tuple(documents)


def default_knowledge_base() -> PolicyKnowledgeBase:
    return PolicyKnowledgeBase.from_directory(Path(__file__).parent.parent / "sample_data" / "policies")


def _parse_document(raw: str) -> tuple[dict[str, str], str]:
    header, content = raw.split("---", 2)[1:]
    metadata = {key.strip(): value.strip() for key, value in (line.split(":", 1) for line in header.strip().splitlines())}
    required = {"document_id", "title", "version", "request_types"}
    if required.difference(metadata):
        raise ValueError("Policy document metadata is incomplete")
    return metadata, content.strip()


def _terms(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", value.lower()))


def _excerpt(content: str, maximum: int = 300) -> str:
    compact = " ".join(line.strip("# ") for line in content.splitlines() if line.strip())
    return compact[:maximum]
