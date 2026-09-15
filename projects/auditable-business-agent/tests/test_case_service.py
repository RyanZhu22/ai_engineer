from datetime import date, datetime, timezone
import unittest

from app.audit import AppendOnlyAuditLog
from app.models import Approval, ApprovalStatus, Order, OrderStatus, RequestType, SupportRequest
from app.service import CaseService
from app.tools import MockOrderService, MockTicketService


class CaseServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 9, 15)
        self.audit_log = AppendOnlyAuditLog()
        self.ticket_service = MockTicketService()
        self.service = CaseService(
            order_service=MockOrderService(
                [
                    Order(
                        order_id="ORD-100",
                        customer_id="customer-1",
                        status=OrderStatus.DELIVERED,
                        shipped_on=date(2026, 9, 7),
                        delivered_on=date(2026, 9, 10),
                    )
                ]
            ),
            ticket_service=self.ticket_service,
            audit_log=self.audit_log,
        )
        self.request = SupportRequest(
            case_id="CASE-100",
            customer_id="customer-1",
            order_id="ORD-100",
            request_type=RequestType.RETURN,
            summary="商品不适合，申请退货。",
            submitted_on=self.today,
        )

    def approval(self, status: ApprovalStatus = ApprovalStatus.APPROVED) -> Approval:
        return Approval(
            case_id="CASE-100",
            approver_id="reviewer-1",
            status=status,
            decided_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
            note="已核验订单信息。",
        )

    def test_assessment_writes_auditable_events(self) -> None:
        self.service.assess(self.request, request_id="req-1", today=self.today)

        self.assertEqual(
            [event.event_type for event in self.audit_log.events_for_case("CASE-100")],
            [
                "request_received",
                "knowledge_retrieved",
                "order_queried",
                "rule_evaluated",
                "reply_generated",
                "action_proposed",
            ],
        )

        event = self.audit_log.events_for_case("CASE-100")[0]
        with self.assertRaises(TypeError):
            event.payload["tampered"] = True  # type: ignore[index]

    def test_approved_action_creates_ticket_once(self) -> None:
        decision = self.service.assess(self.request, request_id="req-1", today=self.today)

        first = self.service.apply_approval(
            case_id="CASE-100",
            decision=decision,
            approval=self.approval(),
            request_id="req-2",
        )
        second = self.service.apply_approval(
            case_id="CASE-100",
            decision=decision,
            approval=self.approval(),
            request_id="req-3",
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.ticket.ticket_id, second.ticket.ticket_id)
        self.assertEqual(self.ticket_service.ticket_count, 1)
        self.assertEqual(
            [event.event_type for event in self.audit_log.events_for_case("CASE-100")][-2:],
            ["approval_approved", "action_execution_reused"],
        )

    def test_rejected_action_has_no_side_effect(self) -> None:
        decision = self.service.assess(self.request, request_id="req-1", today=self.today)

        result = self.service.apply_approval(
            case_id="CASE-100",
            decision=decision,
            approval=self.approval(ApprovalStatus.REJECTED),
            request_id="req-2",
        )

        self.assertIsNone(result)
        self.assertEqual(self.ticket_service.ticket_count, 0)
        self.assertEqual(self.audit_log.events_for_case("CASE-100")[-1].event_type, "approval_rejected")

    def test_approval_cannot_execute_a_different_case(self) -> None:
        decision = self.service.assess(self.request, request_id="req-1", today=self.today)
        mismatched = Approval(
            case_id="CASE-OTHER",
            approver_id="reviewer-1",
            status=ApprovalStatus.APPROVED,
            decided_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            self.service.apply_approval(
                case_id="CASE-100",
                decision=decision,
                approval=mismatched,
                request_id="req-2",
            )


if __name__ == "__main__":
    unittest.main()
