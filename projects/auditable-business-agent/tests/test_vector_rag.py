import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import RequestType
from app.vector_rag import BgeEmbeddings, LocalHashEmbeddings, VectorPolicyKnowledgeBase, _chunk_documents


class FakeVectorStore:
    def __init__(self) -> None:
        self.documents = {}

    def get_by_ids(self, ids):
        return [self.documents[item] for item in ids if item in self.documents]

    def add_documents(self, documents, **kwargs):
        for document, document_id in zip(documents, kwargs["ids"], strict=True):
            document.id = document_id
            self.documents[document_id] = document
        return [str(item) for item in kwargs["ids"]]

    def similarity_search_with_score(self, query, k, filter=None):
        matches = [
            (document, 0.25)
            for document in self.documents.values()
            if filter is None or document.metadata.get("request_type") == filter.get("request_type")
        ]
        return matches[:k]


class VectorRagTests(unittest.TestCase):
    def test_local_embedding_is_deterministic_and_normalized(self) -> None:
        embeddings = LocalHashEmbeddings()
        first = embeddings.embed_query("申请退货")
        second = embeddings.embed_query("申请退货")

        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0)

    @patch("app.vector_rag.TextEmbedding")
    def test_bge_embeddings_convert_fastembed_vectors(self, text_embedding) -> None:
        text_embedding.return_value.embed.return_value = iter([[0.1, 0.2], [0.3, 0.4]])
        embeddings = BgeEmbeddings(model_name="BAAI/bge-small-zh-v1.5")

        self.assertEqual(embeddings.embed_documents(["第一条", "第二条"]), [[0.1, 0.2], [0.3, 0.4]])
        text_embedding.assert_called_once_with(model_name="BAAI/bge-small-zh-v1.5", cache_dir=None)

    def test_ingestion_is_idempotent_and_search_returns_citation_metadata(self) -> None:
        store = FakeVectorStore()
        knowledge_base = VectorPolicyKnowledgeBase(store)
        directory = Path(__file__).parent.parent / "sample_data" / "policies"

        self.assertEqual(knowledge_base.ingest(directory), 6)
        self.assertEqual(knowledge_base.ingest(directory), 0)
        result = knowledge_base.search(request_type=RequestType.RETURN, query="申请退货")

        self.assertIn("return-policy", [item.document_id for item in result])
        policy = next(item for item in result if item.document_id == "return-policy")
        self.assertEqual(policy.chunk_index, 0)
        self.assertIn("sample_data/policies/return-policy.md", policy.source)

    def test_non_local_collection_uses_namespaced_document_ids(self) -> None:
        store = FakeVectorStore()
        knowledge_base = VectorPolicyKnowledgeBase(store, id_prefix="bge_512_v2:")
        directory = Path(__file__).parent.parent / "sample_data" / "policies"

        self.assertEqual(knowledge_base.ingest(directory), 6)
        self.assertTrue(all(document_id.startswith("bge_512_v2:") for document_id in store.documents))
        self.assertEqual(knowledge_base.ingest(directory), 0)

    def test_policy_documents_are_split_into_langchain_documents(self) -> None:
        chunks = _chunk_documents(Path(__file__).parent.parent / "sample_data" / "policies")
        self.assertEqual(len(chunks), 6)
        self.assertTrue(all(document.id and document.metadata["version"] == "2026.09" for document in chunks))


if __name__ == "__main__":
    unittest.main()
