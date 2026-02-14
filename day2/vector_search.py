import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer


@dataclass
class Chunk:
    doc_name: str
    chunk_id: int
    text: str


def load_chunks(docs_dir: Path) -> List[Chunk]:
    chunks: List[Chunk] = []
    for path in sorted(docs_dir.glob("*.txt")):
        content = path.read_text(encoding="utf-8")
        parts = [p.strip() for p in content.split("\n\n") if p.strip()]
        for idx, part in enumerate(parts):
            chunks.append(Chunk(doc_name=path.name, chunk_id=idx, text=part))
    return chunks


def build_index(
    chunks: List[Chunk], model: SentenceTransformer, batch_size: int
) -> np.ndarray:
    texts = [c.text for c in chunks]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return embeddings


def search(
    query: str, model: SentenceTransformer, vectors: np.ndarray, top_k: int
) -> List[int]:
    q_vec = model.encode(
        [query],
        batch_size=1,
        show_progress_bar=False,
        normalize_embeddings=True,
    )[0]
    scores = np.dot(vectors, q_vec)
    top_idx = np.argsort(scores)[::-1][:top_k]
    return top_idx.tolist()


def main() -> None:
    parser = argparse.ArgumentParser(description="Vector search with embeddings.")
    parser.add_argument("--query", required=True, help="Search query text")
    parser.add_argument("--docs_dir", default="data/docs", help="Directory containing .txt docs")
    parser.add_argument("--top_k", type=int, default=3, help="Number of results to return")
    parser.add_argument("--max_chars", type=int, default=200, help="Max characters to show per result")
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="SentenceTransformer model name",
    )
    parser.add_argument("--batch_size", type=int, default=32, help="Embedding batch size")
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    if not docs_dir.exists():
        raise SystemExit(f"docs_dir not found: {docs_dir}")

    chunks = load_chunks(docs_dir)
    if not chunks:
        raise SystemExit("No .txt documents found in docs_dir")

    model = SentenceTransformer(args.model)
    vectors = build_index(chunks, model, args.batch_size)
    indices = search(args.query, model, vectors, args.top_k)

    print(f"Query: {args.query}")
    print("Top results:")
    for rank, idx in enumerate(indices, start=1):
        chunk = chunks[idx]
        text = chunk.text.replace("\n", " ")
        if len(text) > args.max_chars:
            text = text[: args.max_chars].rstrip() + "..."
        print(f"{rank}. {chunk.doc_name}#chunk{chunk.chunk_id} :: {text}")


if __name__ == "__main__":
    main()
