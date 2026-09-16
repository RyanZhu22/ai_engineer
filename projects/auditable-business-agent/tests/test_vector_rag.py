import unittest
from pathlib import Path

from app.models import RequestType
from app.vector_rag import LocalHashEmbeddings, VectorPolicyKnowledgeBase, _chunk_documents


class FakeVectorStore:
    def __init__(self) -> None:
        self.documents = {}

    def get_by_ids(self, ids):
        return [self.documents[item] for item in ids if item in self.documents]

    def add_documents(self, documents, **kwargs):
        for document in documents:
            self.documents[document.id] = document
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

    def test_ingestion_is_idempotent_and_search_returns_citation_metadata(self) -> None:
        store = FakeVectorStore()
        knowledge_base = VectorPolicyKnowledgeBase(store)
        directory = Path(__file__).parent.parent / "sample_data" / "policies"

        self.assertEqual(knowledge_base.ingest(directory), 3)
        self.assertEqual(knowledge_base.ingest(directory), 0)
        result = knowledge_base.search(request_type=RequestType.RETURN, query="申请退货")

        self.assertEqual(result[0].document_id, "return-policy")
        self.assertEqual(result[0].chunk_index, 0)
        self.assertIn("sample_data/policies/return-policy.md", result[0].source)

    def test_policy_documents_are_split_into_langchain_documents(self) -> None:
        chunks = _chunk_documents(Path(__file__).parent.parent / "sample_data" / "policies")
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(document.id and document.metadata["version"] == "2026.09" for document in chunks))


if __name__ == "__main__":
    unittest.main()
