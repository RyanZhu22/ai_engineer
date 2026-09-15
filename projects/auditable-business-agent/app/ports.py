from __future__ import annotations

from typing import Any, Mapping, Protocol

from app.models import AuditEvent, Order, SupportRequest, TicketExecution, User


class CaseStore(Protocol):
    def save(self, request: SupportRequest) -> None: ...

    def get(self, case_id: str) -> SupportRequest | None: ...


class OrderReader(Protocol):
    def get_order(self, order_id: str) -> Order | None: ...


class TicketWriter(Protocol):
    def create_ticket(
        self,
        *,
        case_id: str,
        ticket_type: str,
        idempotency_key: str,
    ) -> TicketExecution: ...


class AuditSink(Protocol):
    def append(
        self,
        *,
        case_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> AuditEvent: ...


class UserRepository(Protocol):
    def get_by_username(self, username: str) -> User | None: ...

    def create(self, *, username: str, password_hash: str, role: str) -> User: ...

    def set_password(self, *, username: str, password_hash: str) -> bool: ...
