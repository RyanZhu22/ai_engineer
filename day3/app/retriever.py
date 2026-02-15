from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer


@dataclass
class Chunk:
    doc_name: str
    chunk_id: int
    text: str


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


class VectorRetriever:
    def __init__(self, docs_dir: Path, model_name: str, batch_size: int = 32) -> None:
        self.docs_dir = docs_dir
        self.model_name = model_name
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name)
        self.chunks: List[Chunk] = []
        self.vectors: np.ndarray | None = None

    def build(self) -> None:
        self.chunks = self._load_chunks(self.docs_dir)
        if not self.chunks:
            raise ValueError(f"No .txt documents found in docs_dir: {self.docs_dir}")

        texts = [chunk.text for chunk in self.chunks]
        self.vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )

    def search(self, query: str, top_k: int) -> List[SearchHit]:
        if self.vectors is None or not self.chunks:
            raise RuntimeError("Retriever is not built. Call build() first.")
        if top_k <= 0:
            raise ValueError("top_k must be > 0")

        k = min(top_k, len(self.chunks))
        q_vec = self.model.encode(
            [query],
            batch_size=1,
            show_progress_bar=False,
            normalize_embeddings=True,
        )[0]
        scores = np.dot(self.vectors, q_vec)
        top_idx = np.argsort(scores)[::-1][:k]
        return [SearchHit(chunk=self.chunks[i], score=float(scores[i])) for i in top_idx]

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def doc_count(self) -> int:
        return len({chunk.doc_name for chunk in self.chunks})

    @staticmethod
    def _load_chunks(docs_dir: Path) -> List[Chunk]:
        chunks: List[Chunk] = []
        for path in sorted(docs_dir.glob("*.txt")):
            content = path.read_text(encoding="utf-8")
            parts = [part.strip() for part in content.split("\n\n") if part.strip()]
            for idx, part in enumerate(parts):
                chunks.append(Chunk(doc_name=path.name, chunk_id=idx, text=part))
        return chunks
