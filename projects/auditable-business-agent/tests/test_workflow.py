from datetime import date
import unittest

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db_models import Base, OrderRecord
from app.models import OrderStatus
from app.repositories import (
    SqlAlchemyAuditLog,
    SqlAlchemyCaseStore,
    SqlAlchemyOrderService,
    SqlAlchemyTicketService,
)
from app.service import CaseService
from app.workflow import build_workflow


class CaseWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory.begin() as session:
            session.add(
                OrderRecord(
                    order_id="ORD-100",
                    customer_id="customer-1",
                    status=OrderStatus.DELIVERED.value,
                    shipped_on=date(2026, 9, 7),
                    delivered_on=date(2026, 9, 10),
                )
            )
        self.audit_log = SqlAlchemyAuditLog(self.session_factory)
        service = CaseService(
            case_store=SqlAlchemyCaseStore(self.session_factory),
            order_service=SqlAlchemyOrderService(self.session_factory),
            ticket_service=SqlAlchemyTicketService(self.session_factory),
            audit_log=self.audit_log,
        )
        self.workflow = build_workflow(service, InMemorySaver())
        self.config = {"configurable": {"thread_id": "CASE-100"}}
        self.state = {
            "case_id": "CASE-100",
            "customer_id": "customer-1",
            "order_id": "ORD-100",
            "request_type": "return",
            "summary": "商品不适合，申请退货。",
            "submitted_on": "2026-09-15",
            "assessment_on": "2026-09-15",
            "request_id": "REQ-100",
        }

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_approval_workflow_pauses_then_resumes_to_create_ticket(self) -> None:
        paused = self.workflow.invoke(self.state, config=self.config)

        self.assertIn("__interrupt__", paused)
        self.assertEqual(paused["__interrupt__"][0].value["action"], "create_return_ticket")
        self.assertEqual(
            [event.event_type for event in self.audit_log.events_for_case("CASE-100")],
            [
                "request_received",
                "knowledge_retrieved",
                "order_queried",
                "rule_evaluated",
                "reply_generated",
                "action_proposed",
                "approval_requested",
            ],
        )

        completed = self.workflow.invoke(
            Command(
                resume={
                    "approver_id": "reviewer-1",
                    "status": "approved",
                    "note": "批准退货。",
                    "decided_at": "2026-09-15T00:00:00+00:00",
                }
            ),
            config=self.config,
        )

        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["ticket_id"].startswith("TKT-"))
        self.assertEqual(
            [event.event_type for event in self.audit_log.events_for_case("CASE-100")][-2:],
            ["approval_approved", "action_executed"],
        )


if __name__ == "__main__":
    unittest.main()
