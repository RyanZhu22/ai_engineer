from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import freeze_payload
from app.db_models import AuditEventRecord, OrderRecord, SupportCaseRecord, TicketRecord, UserRecord
from app.models import (
    AuditEvent,
    Order,
    OrderStatus,
    RequestType,
    SupportRequest,
    Ticket,
    TicketExecution,
    User,
    UserRole,
    new_id,
    utc_now,
)


SessionFactory = Callable[[], Session]


class SqlAlchemyCaseStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def save(self, request: SupportRequest) -> None:
        with self._session_factory.begin() as session:
            existing = session.get(SupportCaseRecord, request.case_id)
            if existing is None:
                session.add(
                    SupportCaseRecord(
                        case_id=request.case_id,
                        customer_id=request.customer_id,
                        order_id=request.order_id,
                        request_type=request.request_type.value,
                        summary=request.summary,
                        submitted_on=request.submitted_on,
                        created_at=utc_now(),
                    )
                )
                return
            if (
                existing.customer_id != request.customer_id
                or existing.order_id != request.order_id
                or existing.request_type != request.request_type.value
                or existing.summary != request.summary
                or existing.submitted_on != request.submitted_on
            ):
                raise ValueError("Case ID already exists with different request data")

    def get(self, case_id: str) -> SupportRequest | None:
        with self._session_factory() as session:
            record = session.get(SupportCaseRecord, case_id)
            if record is None:
                return None
            return SupportRequest(
                case_id=record.case_id,
                customer_id=record.customer_id,
                order_id=record.order_id,
                request_type=RequestType(record.request_type),
                summary=record.summary,
                submitted_on=record.submitted_on,
            )


class SqlAlchemyOrderService:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get_order(self, order_id: str) -> Order | None:
        with self._session_factory() as session:
            record = session.get(OrderRecord, order_id)
            if record is None:
                return None
            return Order(
                order_id=record.order_id,
                customer_id=record.customer_id,
                status=OrderStatus(record.status),
                shipped_on=record.shipped_on,
                delivered_on=record.delivered_on,
            )


class SqlAlchemyUserRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get_by_username(self, username: str) -> User | None:
        with self._session_factory() as session:
            record = session.scalar(select(UserRecord).where(UserRecord.username == username))
            return None if record is None else self._user(record)

    def create(self, *, username: str, password_hash: str, role: str) -> User:
        record = UserRecord(
            user_id=new_id(),
            username=username,
            password_hash=password_hash,
            role=role,
            created_at=utc_now(),
        )
        with self._session_factory.begin() as session:
            session.add(record)
        return self._user(record)

    def set_password(self, *, username: str, password_hash: str) -> bool:
        with self._session_factory.begin() as session:
            record = session.scalar(select(UserRecord).where(UserRecord.username == username))
            if record is None:
                return False
            record.password_hash = password_hash
            return True

    @staticmethod
    def _user(record: UserRecord) -> User:
        return User(
            user_id=record.user_id,
            username=record.username,
            password_hash=record.password_hash,
            role=UserRole(record.role),
        )


class SqlAlchemyTicketService:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def create_ticket(
        self,
        *,
        case_id: str,
        ticket_type: str,
        idempotency_key: str,
    ) -> TicketExecution:
        try:
            with self._session_factory.begin() as session:
                existing = session.scalar(
                    select(TicketRecord).where(TicketRecord.idempotency_key == idempotency_key)
                )
                if existing is not None:
                    return TicketExecution(ticket=self._ticket(existing), created=False)

                record = TicketRecord(
                    ticket_id=f"TKT-{new_id()}",
                    case_id=case_id,
                    ticket_type=ticket_type,
                    idempotency_key=idempotency_key,
                    created_at=utc_now(),
                )
                session.add(record)
                session.flush()
                return TicketExecution(ticket=self._ticket(record), created=True)
        except IntegrityError:
            with self._session_factory() as session:
                existing = session.scalar(
                    select(TicketRecord).where(TicketRecord.idempotency_key == idempotency_key)
                )
                if existing is None:
                    raise
                return TicketExecution(ticket=self._ticket(existing), created=False)

    @staticmethod
    def _ticket(record: TicketRecord) -> Ticket:
        return Ticket(
            ticket_id=record.ticket_id,
            case_id=record.case_id,
            ticket_type=record.ticket_type,
            idempotency_key=record.idempotency_key,
        )


class SqlAlchemyAuditLog:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def append(
        self,
        *,
        case_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=new_id(),
            case_id=case_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=freeze_payload(payload),
            occurred_at=utc_now(),
            request_id=request_id,
        )
        with self._session_factory.begin() as session:
            session.add(
                AuditEventRecord(
                    event_id=event.event_id,
                    case_id=event.case_id,
                    event_type=event.event_type,
                    actor_type=event.actor_type,
                    actor_id=event.actor_id,
                    payload=deepcopy(dict(event.payload)),
                    occurred_at=event.occurred_at,
                    request_id=event.request_id,
                )
            )
        return event

    def events_for_case(self, case_id: str) -> tuple[AuditEvent, ...]:
        with self._session_factory() as session:
            records = session.scalars(
                select(AuditEventRecord)
                .where(AuditEventRecord.case_id == case_id)
                .order_by(AuditEventRecord.occurred_at, AuditEventRecord.event_id)
            ).all()
        return tuple(
            AuditEvent(
                event_id=record.event_id,
                case_id=record.case_id,
                event_type=record.event_type,
                actor_type=record.actor_type,
                actor_id=record.actor_id,
                payload=freeze_payload(record.payload),
                occurred_at=record.occurred_at,
                request_id=record.request_id,
            )
            for record in records
        )
