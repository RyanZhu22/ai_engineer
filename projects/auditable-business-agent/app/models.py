from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


class OrderStatus(StrEnum):
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class RequestType(StrEnum):
    TRACKING = "tracking"
    RETURN = "return"
    DEFECT = "defect"


class ActionType(StrEnum):
    ANSWER_ONLY = "answer_only"
    CREATE_RETURN_TICKET = "create_return_ticket"
    CREATE_REPAIR_TICKET = "create_repair_ticket"
    ESCALATE_TO_SPECIALIST = "escalate_to_specialist"


class ApprovalStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class UserRole(StrEnum):
    CUSTOMER_SERVICE = "customer_service"
    APPROVER = "approver"


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    customer_id: str
    status: OrderStatus
    shipped_on: date
    delivered_on: date | None = None


@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    username: str
    password_hash: str
    role: UserRole


@dataclass(frozen=True, slots=True)
class SupportRequest:
    case_id: str
    customer_id: str
    order_id: str
    request_type: RequestType
    summary: str
    submitted_on: date


@dataclass(frozen=True, slots=True)
class Decision:
    action: ActionType
    reason: str
    rule_id: str
    requires_approval: bool


@dataclass(frozen=True, slots=True)
class Approval:
    case_id: str
    approver_id: str
    status: ApprovalStatus
    decided_at: datetime
    note: str = ""


@dataclass(frozen=True, slots=True)
class Ticket:
    ticket_id: str
    case_id: str
    ticket_type: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class TicketExecution:
    ticket: Ticket
    created: bool


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    case_id: str
    event_type: str
    actor_type: str
    actor_id: str
    payload: Mapping[str, Any]
    occurred_at: datetime
    request_id: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())
