from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ports import AuditSink, CaseStore, UserRepository
from app.repositories import (
    SessionFactory,
    SqlAlchemyAuditLog,
    SqlAlchemyCaseStore,
    SqlAlchemyOrderService,
    SqlAlchemyTicketService,
    SqlAlchemyUserRepository,
)
from app.service import CaseService
from app.workflow import build_workflow


@dataclass(frozen=True, slots=True)
class AppRuntime:
    case_store: CaseStore
    audit_log: AuditSink
    user_repository: UserRepository
    workflow: Any


def build_runtime(session_factory: SessionFactory, checkpointer: Any) -> AppRuntime:
    case_store = SqlAlchemyCaseStore(session_factory)
    audit_log = SqlAlchemyAuditLog(session_factory)
    user_repository = SqlAlchemyUserRepository(session_factory)
    service = CaseService(
        case_store=case_store,
        order_service=SqlAlchemyOrderService(session_factory),
        ticket_service=SqlAlchemyTicketService(session_factory),
        audit_log=audit_log,
    )
    return AppRuntime(
        case_store=case_store,
        audit_log=audit_log,
        user_repository=user_repository,
        workflow=build_workflow(service, checkpointer),
    )
