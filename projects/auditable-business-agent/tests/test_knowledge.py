import unittest

from app.knowledge import default_knowledge_base
from app.models import RequestType


class KnowledgeTests(unittest.TestCase):
    def test_retrieves_versioned_return_policy(self) -> None:
        evidence = default_knowledge_base().search(request_type=RequestType.RETURN, query="商品不适合，申请退货")
        self.assertEqual(evidence[0].document_id, "return-policy")
        self.assertEqual(evidence[0].version, "2026.09")
        self.assertIn("7 天", evidence[0].excerpt)


if __name__ == "__main__":
    unittest.main()
