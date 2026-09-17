from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Iterable
from pathlib import Path

from fastembed import TextEmbedding
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.knowledge import Evidence, KnowledgeBase, load_policy_documents
from app.models import RequestType


LOCAL_EMBEDDING_DIMENSIONS = 256
BGE_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
VECTOR_COLLECTION_SCHEMA_VERSION = 2


class LocalHashEmbeddings(Embeddings):
    """Deterministic offline embedding for demos and tests.

    It makes the vector pipeline runnable without an API key. Production
    retrieval should use ``RAG_EMBEDDING_PROVIDER=openai``.
    """

    def __init__(self, dimensions: int = LOCAL_EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for feature in _features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class BgeEmbeddings(Embeddings):
    """Local BGE embeddings backed by FastEmbed and ONNX Runtime."""

    def __init__(self, model_name: str = BGE_DEFAULT_MODEL, cache_dir: str | None = None) -> None:
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(value) for value in vector] for vector in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class VectorPolicyKnowledgeBase(KnowledgeBase):
    def __init__(self, store: PGVector, *, id_prefix: str = "") -> None:
        self._store = store
        self._id_prefix = id_prefix

    @classmethod
    def from_database(
        cls,
        *,
        connection: str,
        documents_directory: Path,
        provider: str | None = None,
    ) -> VectorPolicyKnowledgeBase:
        embeddings, dimensions, provider_name = _build_embeddings(provider)
        store = PGVector(
            embeddings=embeddings,
            connection=connection,
            # Keep the shared LangChain table unconstrained. Collections encode
            # the provider and dimensions, so local, BGE, and API embeddings
            # can coexist without rewriting each other's vectors.
            # ponytail: this prevents one shared vector index; split storage by
            # dimension or add partial HNSW indexes once the corpus grows.
            embedding_length=None,
            collection_name=f"policy_documents_{provider_name}_{dimensions}_v{VECTOR_COLLECTION_SCHEMA_VERSION}",
            collection_metadata={
                "purpose": "auditable-business-agent-policy-rag",
                "provider": provider_name,
                "dimensions": dimensions,
            },
            use_jsonb=True,
            create_extension=True,
        )
        knowledge_base = cls(
            store,
            id_prefix=f"{provider_name}_{dimensions}_v{VECTOR_COLLECTION_SCHEMA_VERSION}:",
        )
        knowledge_base.ingest(documents_directory)
        return knowledge_base

    def ingest(self, documents_directory: Path) -> int:
        chunks = _chunk_documents(documents_directory)
        ids = [self._store_id(document) for document in chunks]
        existing = {str(document.id): document for document in self._store.get_by_ids(ids)}
        changed = [
            document
            for document in chunks
            if self._store_id(document) not in existing
            or existing[self._store_id(document)].page_content != document.page_content
            or existing[self._store_id(document)].metadata != document.metadata
        ]
        if changed:
            self._store.add_documents(changed, ids=[self._store_id(document) for document in changed])
        return len(changed)

    def _store_id(self, document: Document) -> str:
        return f"{self._id_prefix}{document.id}"

    def search(self, *, request_type: RequestType, query: str, limit: int = 3) -> tuple[Evidence, ...]:
        matches = self._store.similarity_search_with_score(
            query,
            k=limit,
            filter={"request_type": request_type.value},
        )
        results = []
        for document, distance in matches:
            if document.metadata.get("request_type") != request_type.value:
                continue
            results.append(
                Evidence(
                    document_id=str(document.metadata["document_id"]),
                    title=str(document.metadata["title"]),
                    version=str(document.metadata["version"]),
                    excerpt=_excerpt(document.page_content),
                    score=round(1 / (1 + float(distance)), 6),
                    chunk_index=int(document.metadata["chunk_index"]),
                    source=str(document.metadata["source"]),
                )
            )
            if len(results) == limit:
                break
        return tuple(results)


def _build_embeddings(provider: str | None) -> tuple[Embeddings, int, str]:
    selected = (provider or os.getenv("RAG_EMBEDDING_PROVIDER", "local")).lower()
    if selected == "local":
        return LocalHashEmbeddings(), LOCAL_EMBEDDING_DIMENSIONS, "local"
    if selected == "bge":
        model_name = os.getenv("BGE_EMBEDDING_MODEL", BGE_DEFAULT_MODEL)
        return BgeEmbeddings(model_name=model_name, cache_dir=os.getenv("BGE_CACHE_DIR")), TextEmbedding.get_embedding_size(model_name), "bge"
    if selected != "openai":
        raise ValueError("RAG_EMBEDDING_PROVIDER must be local, bge, or openai")

    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("EMBEDDING_API_KEY or OPENAI_API_KEY is required for openai embeddings")
    dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    kwargs: dict[str, object] = {
        "model": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        "api_key": api_key,
    }
    base_url = os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAIEmbeddings(**kwargs), dimensions, "openai"


def _chunk_documents(directory: Path) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=180,
        chunk_overlap=30,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    chunks: list[Document] = []
    for policy in load_policy_documents(directory):
        pieces = splitter.split_text(policy.content)
        for index, piece in enumerate(pieces):
            chunks.append(
                Document(
                    id=f"{policy.document_id}:v{policy.version}:chunk-{index}",
                    page_content=piece,
                    metadata={
                        "document_id": policy.document_id,
                        "title": policy.title,
                        "version": policy.version,
                        "request_type": next(iter(policy.request_types)).value,
                        "chunk_index": index,
                        "source": policy.source,
                    },
                )
            )
    return chunks


def _features(value: str) -> Iterable[str]:
    for token in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", value.lower()):
        yield token
        if any("\u4e00" <= char <= "\u9fff" for char in token):
            yield from (token[index : index + 2] for index in range(len(token) - 1))


def _excerpt(content: str, maximum: int = 300) -> str:
    return " ".join(content.split())[:maximum]
