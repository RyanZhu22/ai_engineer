from datetime import date, datetime, timezone
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db_models import AuditEventRecord, Base, OrderRecord, SupportCaseRecord, TicketRecord
from app.models import Approval, ApprovalStatus, OrderStatus, RequestType, SupportRequest
from app.auth import hash_password, verify_password
from app.repositories import (
    SqlAlchemyAuditLog,
    SqlAlchemyCaseStore,
    SqlAlchemyOrderService,
    SqlAlchemyTicketService,
    SqlAlchemyUserRepository,
)
from app.service import CaseService


class SqlAlchemyRepositoryTests(unittest.TestCase):
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
        self.service = CaseService(
            case_store=SqlAlchemyCaseStore(self.session_factory),
            order_service=SqlAlchemyOrderService(self.session_factory),
            ticket_service=SqlAlchemyTicketService(self.session_factory),
            audit_log=self.audit_log,
        )
        self.request = SupportRequest(
            case_id="CASE-100",
            customer_id="customer-1",
            order_id="ORD-100",
            request_type=RequestType.RETURN,
            summary="商品不适合，申请退货。",
            submitted_on=date(2026, 9, 15),
        )

    def tearDown(self) -> None:
        self.engine.dispose()

    def approval(self) -> Approval:
        return Approval(
            case_id="CASE-100",
            approver_id="reviewer-1",
            status=ApprovalStatus.APPROVED,
            decided_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
        )

    def test_case_audit_and_ticket_are_persisted(self) -> None:
        decision = self.service.assess(self.request, request_id="req-1", today=date(2026, 9, 15))
        execution = self.service.apply_approval(
            case_id=self.request.case_id,
            decision=decision,
            approval=self.approval(),
            request_id="req-2",
        )

        self.assertIsNotNone(execution)
        with self.session_factory() as session:
            self.assertIsNotNone(session.get(SupportCaseRecord, "CASE-100"))
            self.assertEqual(len(session.scalars(select(AuditEventRecord)).all()), 8)
            self.assertEqual(len(session.scalars(select(TicketRecord)).all()), 1)

    def test_ticket_idempotency_survives_new_repository_instance(self) -> None:
        decision = self.service.assess(self.request, request_id="req-1", today=date(2026, 9, 15))
        first = self.service.apply_approval(
            case_id=self.request.case_id,
            decision=decision,
            approval=self.approval(),
            request_id="req-2",
        )
        second = SqlAlchemyTicketService(self.session_factory).create_ticket(
            case_id=self.request.case_id,
            ticket_type="return",
            idempotency_key="CASE-100:create_return_ticket",
        )

        self.assertIsNotNone(first)
        self.assertFalse(second.created)
        self.assertEqual(first.ticket.ticket_id, second.ticket.ticket_id)

    def test_user_password_can_be_reset_without_reading_the_old_password(self) -> None:
        users = SqlAlchemyUserRepository(self.session_factory)
        users.create(username="agent-1", password_hash=hash_password("first-password"), role="customer_service")

        self.assertTrue(users.set_password(username="agent-1", password_hash=hash_password("second-password")))
        user = users.get_by_username("agent-1")

        self.assertIsNotNone(user)
        self.assertTrue(verify_password("second-password", user.password_hash))
        self.assertFalse(verify_password("first-password", user.password_hash))


if __name__ == "__main__":
    unittest.main()
