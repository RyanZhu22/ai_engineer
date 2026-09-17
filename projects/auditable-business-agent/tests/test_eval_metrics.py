import unittest

from app.eval_metrics import aggregate_retrieval_metrics, recall_at_k, reciprocal_rank


class RetrievalMetricTests(unittest.TestCase):
    def test_recall_and_reciprocal_rank(self) -> None:
        ranked = ["other", "target", "last"]
        self.assertEqual(recall_at_k(ranked, "target", 2), 1.0)
        self.assertEqual(recall_at_k(ranked, "target", 1), 0.0)
        self.assertEqual(reciprocal_rank(ranked, "target"), 0.5)

    def test_aggregate_metrics(self) -> None:
        metrics = aggregate_retrieval_metrics(
            [(["return-policy"], "return-policy"), (["other"], "missing")],
            k=1,
        )
        self.assertEqual(metrics, {"recall_at_1": 0.5, "mrr": 0.5})


if __name__ == "__main__":
    unittest.main()
