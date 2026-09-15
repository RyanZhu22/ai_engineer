from datetime import date
import unittest

from app.models import ActionType, Order, OrderStatus, RequestType, SupportRequest
from app.policy import PolicyEngine


class PolicyEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PolicyEngine()
        self.today = date(2026, 9, 15)
        self.order = Order(
            order_id="ORD-100",
            customer_id="customer-1",
            status=OrderStatus.DELIVERED,
            shipped_on=date(2026, 9, 7),
            delivered_on=date(2026, 9, 10),
        )

    def request(self, request_type: RequestType, order_id: str = "ORD-100") -> SupportRequest:
        return SupportRequest(
            case_id="CASE-100",
            customer_id="customer-1",
            order_id=order_id,
            request_type=request_type,
            summary="需要帮助",
            submitted_on=self.today,
        )

    def test_return_inside_window_requires_approval(self) -> None:
        decision = self.engine.evaluate(self.request(RequestType.RETURN), self.order, today=self.today)

        self.assertEqual(decision.action, ActionType.CREATE_RETURN_TICKET)
        self.assertEqual(decision.rule_id, "RETURN_WITHIN_WINDOW")
        self.assertTrue(decision.requires_approval)

    def test_return_outside_window_is_answer_only(self) -> None:
        expired_order = Order(
            order_id="ORD-100",
            customer_id="customer-1",
            status=OrderStatus.DELIVERED,
            shipped_on=date(2026, 8, 1),
            delivered_on=date(2026, 8, 2),
        )

        decision = self.engine.evaluate(self.request(RequestType.RETURN), expired_order, today=self.today)

        self.assertEqual(decision.action, ActionType.ANSWER_ONLY)
        self.assertEqual(decision.rule_id, "RETURN_OUTSIDE_WINDOW")
        self.assertFalse(decision.requires_approval)

    def test_defect_inside_warranty_creates_repair_proposal(self) -> None:
        decision = self.engine.evaluate(self.request(RequestType.DEFECT), self.order, today=self.today)

        self.assertEqual(decision.action, ActionType.CREATE_REPAIR_TICKET)
        self.assertEqual(decision.rule_id, "DEFECT_WITHIN_WARRANTY")
        self.assertTrue(decision.requires_approval)

    def test_missing_order_escalates(self) -> None:
        decision = self.engine.evaluate(self.request(RequestType.RETURN, "ORD-404"), None, today=self.today)

        self.assertEqual(decision.action, ActionType.ESCALATE_TO_SPECIALIST)
        self.assertEqual(decision.rule_id, "ORDER_NOT_FOUND")
        self.assertTrue(decision.requires_approval)


if __name__ == "__main__":
    unittest.main()
