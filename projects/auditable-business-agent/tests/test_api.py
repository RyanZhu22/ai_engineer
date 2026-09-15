from datetime import date
import unittest

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db_models import Base, OrderRecord
from app.main import create_app
from app.models import OrderStatus, UserRole


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with session_factory.begin() as session:
            session.add_all(
                [
                    OrderRecord(
                        order_id="ORD-100",
                        customer_id="customer-1",
                        status=OrderStatus.DELIVERED.value,
                        shipped_on=date(2026, 9, 7),
                        delivered_on=date(2026, 9, 10),
                    ),
                    OrderRecord(
                        order_id="ORD-101",
                        customer_id="customer-1",
                        status=OrderStatus.SHIPPED.value,
                        shipped_on=date(2026, 9, 14),
                        delivered_on=None,
                    ),
                ]
            )
        self.app = create_app(session_factory=session_factory, checkpointer=InMemorySaver())
        runtime = self.app.state.runtime
        runtime.user_repository.create(
            username="agent-1",
            password_hash=hash_password("customer-service-password"),
            role=UserRole.CUSTOMER_SERVICE.value,
        )
        runtime.user_repository.create(
            username="reviewer-1",
            password_hash=hash_password("approver-password-123"),
            role=UserRole.APPROVER.value,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.engine.dispose()

    def headers_for(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post("/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_create_case_pause_approve_and_read_audit(self) -> None:
        customer_service_headers = self.headers_for("agent-1", "customer-service-password")
        created = self.client.post(
            "/cases",
            json={
                "case_id": "CASE-100",
                "customer_id": "customer-1",
                "order_id": "ORD-100",
                "request_type": "return",
                "summary": "商品不适合，申请退货。",
                "submitted_on": "2026-09-15",
            },
            headers=customer_service_headers,
        )

        self.assertEqual(created.status_code, 202)
        self.assertEqual(created.json()["status"], "pending_approval")
        self.assertEqual(created.json()["approval"]["action"], "create_return_ticket")

        audit_before = self.client.get("/cases/CASE-100/audit", headers=customer_service_headers)
        self.assertEqual(audit_before.status_code, 200)
        self.assertEqual(len(audit_before.json()), 7)
        self.assertEqual(audit_before.json()[-1]["event_type"], "approval_requested")

        approved = self.client.post(
            "/cases/CASE-100/approval",
            json={"status": "approved", "note": "批准退货。"},
            headers=self.headers_for("reviewer-1", "approver-password-123"),
        )

        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "completed")
        self.assertTrue(approved.json()["ticket_id"].startswith("TKT-"))

        case = self.client.get("/cases/CASE-100", headers=customer_service_headers)
        self.assertEqual(case.status_code, 200)
        self.assertEqual(len(case.json()["audit_events"]), 9)

    def test_tracking_case_completes_without_approval(self) -> None:
        created = self.client.post(
            "/cases",
            json={
                "case_id": "CASE-101",
                "customer_id": "customer-1",
                "order_id": "ORD-101",
                "request_type": "tracking",
                "summary": "请查询物流。",
                "submitted_on": "2026-09-15",
            },
            headers=self.headers_for("agent-1", "customer-service-password"),
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["status"], "completed")
        self.assertFalse(created.json()["decision"]["requires_approval"])

    def test_customer_service_cannot_approve(self) -> None:
        customer_service_headers = self.headers_for("agent-1", "customer-service-password")
        self.client.post(
            "/cases",
            json={
                "case_id": "CASE-102",
                "customer_id": "customer-1",
                "order_id": "ORD-100",
                "request_type": "return",
                "summary": "商品不适合，申请退货。",
                "submitted_on": "2026-09-15",
            },
            headers=customer_service_headers,
        )

        approval = self.client.post(
            "/cases/CASE-102/approval",
            json={"status": "approved"},
            headers=customer_service_headers,
        )

        self.assertEqual(approval.status_code, 403)

    def test_completed_case_cannot_be_approved_again(self) -> None:
        customer_service_headers = self.headers_for("agent-1", "customer-service-password")
        approver_headers = self.headers_for("reviewer-1", "approver-password-123")
        self.client.post(
            "/cases",
            json={
                "case_id": "CASE-103",
                "customer_id": "customer-1",
                "order_id": "ORD-100",
                "request_type": "return",
                "summary": "商品不适合，申请退货。",
                "submitted_on": "2026-09-15",
            },
            headers=customer_service_headers,
        )
        self.client.post(
            "/cases/CASE-103/approval",
            json={"status": "approved"},
            headers=approver_headers,
        )

        repeated = self.client.post(
            "/cases/CASE-103/approval",
            json={"status": "approved"},
            headers=approver_headers,
        )

        self.assertEqual(repeated.status_code, 409)


if __name__ == "__main__":
    unittest.main()
